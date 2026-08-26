from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from api.models import AppliedPlanState, GraphDefinition, ResolvedPlan
from core.orchestration.resolver_replay import (
    ResolverReplayError,
    replay_resolver_bundle,
)

from .base import AudioAPIProblem, AudioV1APIView, paginated, require_object
from .catalogue import api_node_type_registry
from .representations import applied_state_document, plan_document


def _visible_plans(request):
    return ResolvedPlan.objects.filter(
        graph_definition__in=GraphDefinition.objects.visible_to(request.user)
    ).select_related("graph_definition", "graph_revision")


class PlanHistoryView(AudioV1APIView):
    def get(self, request):
        queryset = _visible_plans(request)
        filters = {
            "graphId": "graph_definition_id",
            "status": "status",
            "mode": "resolution_mode",
            "correlationId": "correlation_id",
        }
        for parameter, field in filters.items():
            value = request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        states = {
            state.graph_definition_id: state
            for state in AppliedPlanState.objects.filter(
                graph_definition__in=GraphDefinition.objects.visible_to(request.user)
            )
        }
        return paginated(
            request,
            queryset,
            lambda plan: plan_document(
                plan,
                applied_state=states.get(plan.graph_definition_id),
            ),
        )


class PlanDetailView(AudioV1APIView):
    def get(self, request, plan_id):
        plan = _visible_plans(request).get(pk=plan_id)
        state = AppliedPlanState.objects.filter(
            graph_definition_id=plan.graph_definition_id
        ).first()
        return Response(plan_document(plan, applied_state=state))


class CurrentPlanView(AudioV1APIView):
    def get(self, request):
        graphs = GraphDefinition.objects.visible_to(request.user)
        graph_id = request.query_params.get("graphId")
        if graph_id:
            graphs = graphs.filter(pk=graph_id)
        states = AppliedPlanState.objects.filter(graph_definition__in=graphs).select_related(
            "current_plan",
            "previous_plan",
            "graph_definition",
        )
        documents = []
        represented = set()
        for state in states:
            represented.add(state.graph_definition_id)
            documents.append(
                {
                    "definitionId": str(state.graph_definition_id),
                    "applied": applied_state_document(state),
                    "plan": (
                        plan_document(state.current_plan, applied_state=state)
                        if state.current_plan is not None
                        else None
                    ),
                }
            )
        for graph in graphs.exclude(pk__in=represented):
            latest = graph.resolved_plans.first()
            documents.append(
                {
                    "definitionId": str(graph.pk),
                    "applied": applied_state_document(None),
                    "plan": plan_document(latest) if latest is not None else None,
                }
            )
        documents.sort(key=lambda item: item["definitionId"])
        if graph_id and not documents:
            GraphDefinition.objects.visible_to(request.user).get(pk=graph_id)
        return Response({"items": documents})


class PlanDryRunView(AudioV1APIView):
    def post(self, request, revision_id=None):
        bundle = require_object(request.data)
        if revision_id is not None:
            from .graph_views import _revision_for

            revision = _revision_for(request, revision_id)
            desired = bundle.get("desired")
            graph_revision = desired.get("graphRevision") if isinstance(desired, dict) else None
            if not isinstance(graph_revision, dict) or graph_revision.get("revisionId") != str(
                revision.pk
            ):
                raise AudioAPIProblem(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "dry-run-revision-mismatch",
                    "Dry-run revision mismatch",
                    "The replay input must reference the revision in the request path.",
                )
        try:
            replay = replay_resolver_bundle(
                bundle,
                registry=api_node_type_registry(),
                verify_expected=False,
            )
        except (KeyError, TypeError, ValueError, ResolverReplayError) as error:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "dry-run-input-invalid",
                "Dry-run input invalid",
                str(error),
            ) from error
        return Response(
            {
                "dryRun": True,
                "persisted": False,
                "audioMutated": False,
                "status": replay.plan.status.value,
                "planDigest": replay.plan.digest,
                "document": replay.plan.document.to_dict(),
                "explanation": replay.plan.explanation.to_dict(),
                "versions": {
                    "desiredState": replay.inputs.activation.desired_state_version,
                    "world": replay.inputs.world_version.token,
                    "runtimeGeneration": replay.inputs.world_version.runtime_generation,
                    "runtimeSequence": replay.inputs.world_version.runtime_sequence,
                },
            }
        )
