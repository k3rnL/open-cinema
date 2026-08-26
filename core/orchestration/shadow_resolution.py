from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from django.db import transaction
from wyreplumber.runtime import FrozenDict

from api.models import (
    GraphActivation,
    GraphDefinition,
    GraphRevision,
    ResolvedPlan,
    ResolvedPlanMode,
    ShadowResolutionComparison,
)
from api.audio_v1.catalogue import api_node_type_registry

from .feature_flags import (
    AudioOrchestrationFeatureFlags,
    get_audio_orchestration_feature_flags,
)
from .node_catalogue import NodeTypeRegistry
from .resolution_context import build_resolver_inputs
from .resolved_plan import RESOLVED_PLAN_SCHEMA_VERSION, ResolvedPlanOutput, resolve_plan
from .resolver_inputs import ResolverInputs, ResolverSignalFactsInput
from .runtime_world import OrchestratorWorldSnapshot


class ShadowResolutionDisabled(RuntimeError):
    pass


class InactiveShadowGraph(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ShadowPlanDifference:
    equivalent: bool
    document: FrozenDict


@dataclass(frozen=True, slots=True)
class ShadowResolutionOutcome:
    shadow_plan_id: uuid.UUID
    comparison_id: uuid.UUID
    status: str
    plan_digest: str
    baseline_plan_id: uuid.UUID | None
    equivalent: bool
    differences: FrozenDict

    @property
    def driver_actions(self) -> tuple[()]:
        """Shadow resolution deliberately exposes no executable driver actions."""

        return ()


def _selected_edges(document: Mapping[str, object]) -> tuple[str, ...]:
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        return ()
    selected = paths.get("selectedEdgeIds", ())
    if not isinstance(selected, (list, tuple)):
        return ()
    return tuple(sorted(item for item in selected if isinstance(item, str)))


def _endpoint_targets(document: Mapping[str, object]) -> dict[str, object]:
    bindings = document.get("endpointBindings", ())
    if not isinstance(bindings, (list, tuple)):
        return {}
    return {
        item["logicalEndpointId"]: {
            "status": item.get("status"),
            "runtimeKey": item.get("runtimeKey"),
        }
        for item in bindings
        if isinstance(item, Mapping) and isinstance(item.get("logicalEndpointId"), str)
    }


def _diagnostic_codes(document: Mapping[str, object], name: str) -> tuple[str, ...]:
    diagnostics = document.get(name, ())
    if not isinstance(diagnostics, (list, tuple)):
        return ()
    return tuple(
        sorted(
            item["code"]
            for item in diagnostics
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
        )
    )


def compare_shadow_plan(
    shadow: ResolvedPlanOutput,
    baseline: ResolvedPlan | None,
) -> ShadowPlanDifference:
    if not isinstance(shadow, ResolvedPlanOutput):
        raise TypeError("shadow must be ResolvedPlanOutput")
    candidate_document = shadow.document.to_dict()
    if baseline is None:
        return ShadowPlanDifference(
            equivalent=False,
            document=FrozenDict(
                {
                    "baselinePresent": False,
                    "status": {"baseline": None, "shadow": shadow.status.value},
                    "selectedEdgeIds": {
                        "added": list(_selected_edges(candidate_document)),
                        "removed": [],
                    },
                    "endpointTargetsChanged": sorted(_endpoint_targets(candidate_document)),
                    "warningCodes": {
                        "baseline": [],
                        "shadow": list(_diagnostic_codes(candidate_document, "warnings")),
                    },
                    "errorCodes": {
                        "baseline": [],
                        "shadow": list(_diagnostic_codes(candidate_document, "errors")),
                    },
                }
            ),
        )
    baseline_document = baseline.document
    shadow_edges = set(_selected_edges(candidate_document))
    baseline_edges = set(_selected_edges(baseline_document))
    baseline_targets = _endpoint_targets(baseline_document)
    shadow_targets = _endpoint_targets(candidate_document)
    changed_targets = sorted(
        endpoint_id
        for endpoint_id in set(baseline_targets) | set(shadow_targets)
        if baseline_targets.get(endpoint_id) != shadow_targets.get(endpoint_id)
    )
    differences = {
        "baselinePresent": True,
        "status": {"baseline": baseline.status, "shadow": shadow.status.value},
        "selectedEdgeIds": {
            "added": sorted(shadow_edges - baseline_edges),
            "removed": sorted(baseline_edges - shadow_edges),
        },
        "endpointTargetsChanged": changed_targets,
        "warningCodes": {
            "baseline": list(_diagnostic_codes(baseline_document, "warnings")),
            "shadow": list(_diagnostic_codes(candidate_document, "warnings")),
        },
        "errorCodes": {
            "baseline": list(_diagnostic_codes(baseline_document, "errors")),
            "shadow": list(_diagnostic_codes(candidate_document, "errors")),
        },
    }
    equivalent = bool(
        baseline.plan_digest == shadow.digest
        and baseline.status == shadow.status.value
        and baseline.document == candidate_document
        and baseline.explanation == shadow.explanation.to_dict()
    )
    return ShadowPlanDifference(equivalent, FrozenDict(differences))


def persist_shadow_resolution(
    inputs: ResolverInputs,
    *,
    graph_definition: GraphDefinition,
    graph_revision: GraphRevision,
    baseline_plan: ResolvedPlan | None = None,
    registry: NodeTypeRegistry | None = None,
    flags: AudioOrchestrationFeatureFlags | None = None,
) -> ShadowResolutionOutcome:
    """Resolve and persist diagnostics only; this API has no driver dependency."""

    active_flags = flags or get_audio_orchestration_feature_flags()
    if not active_flags.shadow_resolution:
        raise ShadowResolutionDisabled("Shadow resolution is disabled by feature flags")
    if str(graph_definition.pk) != inputs.graph.definition_id:
        raise ValueError("graph_definition does not match resolver inputs")
    if str(graph_revision.pk) != inputs.graph.revision_id:
        raise ValueError("graph_revision does not match resolver inputs")
    if graph_revision.definition_id != graph_definition.pk:
        raise ValueError("graph_revision belongs to another graph definition")
    if baseline_plan is not None and baseline_plan.graph_definition_id != graph_definition.pk:
        raise ValueError("baseline_plan belongs to another graph definition")

    resolved = resolve_plan(inputs, registry=registry)
    comparison = compare_shadow_plan(resolved, baseline_plan)
    with transaction.atomic():
        persisted = ResolvedPlan(
            schema_version=RESOLVED_PLAN_SCHEMA_VERSION,
            graph_definition=graph_definition,
            graph_revision=graph_revision,
            desired_state_version=inputs.activation.desired_state_version,
            world_generation=inputs.world_version.runtime_generation,
            world_sequence=inputs.world_version.runtime_sequence,
            resolution_mode=ResolvedPlanMode.SHADOW,
            status=resolved.status.value,
            document=resolved.document.to_dict(),
            explanation=resolved.explanation.to_dict(),
            plan_digest=resolved.digest,
        )
        persisted.full_clean()
        persisted.save()
        if persisted.plan_digest != resolved.digest:
            raise ValueError("persisted plan digest differs from pure resolver output")
        comparison_record = ShadowResolutionComparison(
            shadow_plan=persisted,
            baseline_plan=baseline_plan,
            equivalent=comparison.equivalent,
            differences=comparison.document.to_dict(),
        )
        comparison_record.full_clean()
        comparison_record.save()
    return ShadowResolutionOutcome(
        shadow_plan_id=persisted.pk,
        comparison_id=comparison_record.pk,
        status=persisted.status,
        plan_digest=persisted.plan_digest,
        baseline_plan_id=baseline_plan.pk if baseline_plan is not None else None,
        equivalent=comparison_record.equivalent,
        differences=FrozenDict(comparison_record.differences),
    )


class ShadowGraphResolver:
    """Persist resolver evidence for an active graph without constructing a driver."""

    def __init__(self, *, registry=None, signal_facts_provider=None) -> None:
        self.registry = registry or api_node_type_registry()
        self.signal_facts_provider = signal_facts_provider or (
            lambda: ResolverSignalFactsInput(0, {})
        )

    def resolve(
        self,
        definition_id: str,
        world: OrchestratorWorldSnapshot,
    ) -> ShadowResolutionOutcome:
        if not isinstance(world, OrchestratorWorldSnapshot):
            raise TypeError("world must be an OrchestratorWorldSnapshot")
        activation = GraphActivation.objects.select_related(
            "definition", "definition__owner", "revision"
        ).get(definition_id=definition_id)
        if not activation.enabled:
            raise InactiveShadowGraph("Shadow resolution only evaluates active graphs")
        inputs = build_resolver_inputs(
            activation,
            world,
            signal_facts_provider=self.signal_facts_provider,
        )
        baseline = (
            ResolvedPlan.objects.filter(
                graph_definition=activation.definition,
                resolution_mode=ResolvedPlanMode.LIVE,
            )
            .order_by("-created_at", "id")
            .first()
        )
        return persist_shadow_resolution(
            inputs,
            graph_definition=activation.definition,
            graph_revision=activation.revision,
            baseline_plan=baseline,
            registry=self.registry,
        )
