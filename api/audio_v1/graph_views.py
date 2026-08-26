from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Max
from rest_framework import status
from rest_framework.response import Response

from api.models import (
    GraphActivation,
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.activations import (
    GraphActivationConflict,
    activate_graph,
    deactivate_graph,
)
from core.orchestration.graph_documents import graph_content_digest, normalize_graph_document
from core.orchestration.graph_import_export import (
    GraphImportValidationError,
    export_graph_revision,
    import_graph_bundle,
)
from core.orchestration.graph_validation import validate_graph_structure
from core.orchestration.revisions import (
    GraphPublicationValidationError,
    GraphRevisionConflict,
    GraphRevisionNotDraft,
    compare_graph_revisions,
    edit_draft_revision,
    publish_draft_revision,
)

from .base import (
    AudioAPIProblem,
    AudioV1APIView,
    entity_tag,
    paginated,
    parse_boolean,
    parse_precondition,
    require_object,
)
from .catalogue import api_node_type_registry
from .representations import activation_document, graph_document, revision_document


def _graph_for(request, definition_id):
    return GraphDefinition.objects.visible_to(request.user).get(pk=definition_id)


def _revision_for(request, revision_id):
    return GraphRevision.objects.select_related("definition", "author").get(
        pk=revision_id,
        definition__in=GraphDefinition.objects.visible_to(request.user),
    )


def _publication_issues(error: GraphPublicationValidationError):
    return [
        {"path": issue.path, "code": issue.code, "message": issue.message}
        for issue in error.result.issues
    ]


def _import_issues(issues):
    return [{"path": issue.path, "code": issue.code, "message": issue.message} for issue in issues]


class DefinitionListView(AudioV1APIView):
    route_kind: str | None = None

    def get(self, request):
        queryset = GraphDefinition.objects.visible_to(request.user).select_related("owner")
        kind = self.route_kind or request.query_params.get("kind")
        if kind is not None:
            if kind not in GraphDefinitionKind.values:
                raise AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-filter",
                    "Invalid filter",
                    "kind must be graph or subgraph.",
                )
            queryset = queryset.filter(kind=kind)
        archived = request.query_params.get("archived")
        if archived is not None:
            queryset = queryset.filter(
                archived_at__isnull=not parse_boolean(archived, field="archived")
            )
        label = request.query_params.get("label")
        if label:
            if ":" not in label:
                raise AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-filter",
                    "Invalid filter",
                    "label must use name:value syntax.",
                )
            name, value = label.split(":", 1)
            queryset = queryset.filter(**{f"labels__{name}": value})
        return paginated(request, queryset, graph_document)

    def post(self, request):
        body = require_object(request.data)
        unknown = set(body) - {"name", "kind", "labels"}
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                f"Unsupported definition fields: {', '.join(sorted(unknown))}.",
            )
        kind = self.route_kind or body.get("kind", GraphDefinitionKind.GRAPH)
        graph = GraphDefinition(
            name=body.get("name", ""),
            kind=kind,
            owner=request.user,
            labels=body.get("labels", {}),
        )
        graph.full_clean()
        try:
            graph.save()
        except IntegrityError as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "definition-conflict",
                "Definition conflict",
                "A graph with this name already exists for the owner.",
            ) from error
        response = Response(graph_document(graph), status=status.HTTP_201_CREATED)
        response["Location"] = f"/api/audio/v1/graphs/{graph.pk}"
        return response


class SubgraphListView(DefinitionListView):
    route_kind = GraphDefinitionKind.SUBGRAPH


class DefinitionDetailView(AudioV1APIView):
    def get(self, request, definition_id):
        return Response(graph_document(_graph_for(request, definition_id)))


class RevisionListView(AudioV1APIView):
    def get(self, request, definition_id):
        graph = _graph_for(request, definition_id)
        queryset = graph.revisions.select_related("author")
        state_filter = request.query_params.get("state")
        if state_filter is not None:
            if state_filter not in GraphRevisionState.values:
                raise AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-filter",
                    "Invalid filter",
                    "state must be draft or published.",
                )
            queryset = queryset.filter(state=state_filter)
        return paginated(
            request,
            queryset,
            lambda item: revision_document(item, include_content=False),
        )

    def post(self, request, definition_id):
        graph = _graph_for(request, definition_id)
        body = require_object(request.data)
        content = require_object(body.get("content"), field="content")
        if body.get("schemaVersion", 1) != 1:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unsupported-schema-version",
                "Unsupported schema version",
                "Only desired graph schema version 1 is supported.",
            )
        normalized = normalize_graph_document(content)
        if normalized.get("kind") != graph.kind:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "definition-kind-mismatch",
                "Definition kind mismatch",
                "The graph document kind must match its definition.",
            )
        validation = validate_graph_structure(
            normalized,
            registry=api_node_type_registry(),
        )
        try:
            with transaction.atomic():
                locked = GraphDefinition.objects.select_for_update().get(pk=graph.pk)
                number = (
                    locked.revisions.aggregate(value=Max("revision_number"))["value"] or 0
                ) + 1
                revision = GraphRevision(
                    definition=locked,
                    schema_version=1,
                    revision_number=number,
                    state=GraphRevisionState.DRAFT,
                    author=request.user,
                    content=normalized,
                    content_digest=graph_content_digest(normalized),
                    validation_summary=validation.summary(),
                )
                revision.full_clean()
                revision.save()
        except IntegrityError as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "revision-conflict",
                "Revision conflict",
                "A competing request created the next revision.",
            ) from error
        response = Response(
            revision_document(revision),
            status=status.HTTP_201_CREATED,
        )
        response["ETag"] = entity_tag(revision.update_version)
        response["Location"] = f"/api/audio/v1/revisions/{revision.pk}"
        return response


class RevisionDetailView(AudioV1APIView):
    def get(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        response = Response(revision_document(revision))
        response["ETag"] = entity_tag(revision.update_version)
        return response

    def patch(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        expected = parse_precondition(request, minimum=1)
        body = require_object(request.data)
        if set(body) != {"content"}:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                "Draft updates accept exactly the content field.",
            )
        try:
            revision = edit_draft_revision(
                revision_id=revision.pk,
                expected_update_version=expected,
                content=require_object(body["content"], field="content"),
                registry=api_node_type_registry(),
            )
        except GraphRevisionConflict as error:
            current = GraphRevision.objects.get(pk=revision.pk)
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "revision-precondition-failed",
                "Revision changed",
                str(error),
                current_version=current.update_version,
            ) from error
        except GraphRevisionNotDraft as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "published-revision-immutable",
                "Published revision is immutable",
                str(error),
            ) from error
        response = Response(revision_document(revision))
        response["ETag"] = entity_tag(revision.update_version)
        return response

    def delete(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        expected = parse_precondition(request, minimum=1)
        with transaction.atomic():
            locked = GraphRevision.objects.select_for_update().get(pk=revision.pk)
            if locked.state != GraphRevisionState.DRAFT:
                raise AudioAPIProblem(
                    status.HTTP_409_CONFLICT,
                    "published-revision-immutable",
                    "Published revision is immutable",
                    "Only an unpublished draft may be discarded.",
                )
            if locked.update_version != expected:
                raise AudioAPIProblem(
                    status.HTTP_412_PRECONDITION_FAILED,
                    "revision-precondition-failed",
                    "Revision changed",
                    "The draft changed after it was fetched.",
                    current_version=locked.update_version,
                )
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RevisionValidateView(AudioV1APIView):
    def post(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        body = require_object(request.data or {})
        content = body.get("content", revision.content)
        result = validate_graph_structure(
            require_object(content, field="content"),
            registry=api_node_type_registry(),
        )
        return Response(result.summary())


class RevisionCompareView(AudioV1APIView):
    def get(self, request, revision_id):
        left = _revision_for(request, revision_id)
        right_id = request.query_params.get("other")
        if not right_id:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "missing-comparison-revision",
                "Comparison revision required",
                "Provide the other revision UUID in the other query parameter.",
            )
        right = _revision_for(request, right_id)
        comparison = compare_graph_revisions(left, right)
        return Response(
            {
                "leftRevisionId": str(left.pk),
                "rightRevisionId": str(right.pk),
                "semanticEqual": comparison.semantic_equal,
                "layoutEqual": comparison.layout_equal,
                "leftDigest": comparison.left_digest,
                "rightDigest": comparison.right_digest,
                "metadataChanged": comparison.metadata_changed,
                "collections": {
                    name: {
                        "added": list(difference.added),
                        "removed": list(difference.removed),
                        "changed": list(difference.changed),
                    }
                    for name, difference in comparison.collections.items()
                },
            }
        )


class RevisionPublishView(AudioV1APIView):
    def post(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        expected = parse_precondition(request, minimum=1)
        body = require_object(request.data or {})
        try:
            published = publish_draft_revision(
                revision_id=revision.pk,
                expected_update_version=expected,
                registry=api_node_type_registry(),
                activate=bool(body.get("activate", False)),
                expected_activation_version=body.get("expectedActivationVersion", 0),
                parameter_bindings=body.get("parameterBindings", {}),
                scene_bindings=body.get("sceneBindings", {}),
            )
        except GraphRevisionConflict as error:
            current = GraphRevision.objects.get(pk=revision.pk)
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "revision-precondition-failed",
                "Revision changed",
                str(error),
                current_version=current.update_version,
            ) from error
        except GraphRevisionNotDraft as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "published-revision-immutable",
                "Published revision is immutable",
                str(error),
            ) from error
        except GraphPublicationValidationError as error:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "publication-validation-failed",
                "Publication validation failed",
                "The draft remains unpublished.",
                errors=_publication_issues(error),
            ) from error
        except GraphActivationConflict as error:
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "activation-precondition-failed",
                "Activation changed",
                str(error),
                current_version=error.actual_version,
            ) from error
        response = Response(revision_document(published))
        response["ETag"] = entity_tag(published.update_version)
        return response


class RevisionActivateView(AudioV1APIView):
    def post(self, request, revision_id):
        revision = _revision_for(request, revision_id)
        expected = parse_precondition(request, minimum=0)
        body = require_object(request.data or {})
        try:
            activation = activate_graph(
                definition=revision.definition,
                revision=revision,
                expected_version=expected,
                parameter_bindings=dict(body.get("parameterBindings", {})),
                scene_bindings=dict(body.get("sceneBindings", {})),
            )
        except GraphActivationConflict as error:
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "activation-precondition-failed",
                "Activation changed",
                str(error),
                current_version=error.actual_version,
            ) from error
        response = Response(activation_document(activation))
        response["ETag"] = entity_tag(activation.desired_state_version)
        return response


class DefinitionActivationView(AudioV1APIView):
    def get(self, request, definition_id):
        graph = _graph_for(request, definition_id)
        try:
            activation = GraphActivation.objects.select_related("revision").get(definition=graph)
        except GraphActivation.DoesNotExist:
            return Response(
                {
                    "definitionId": str(graph.pk),
                    "revisionId": None,
                    "desiredStateVersion": 0,
                }
            )
        response = Response(activation_document(activation))
        response["ETag"] = entity_tag(activation.desired_state_version)
        return response

    def delete(self, request, definition_id):
        graph = _graph_for(request, definition_id)
        expected = parse_precondition(request, minimum=0)
        try:
            activation = deactivate_graph(
                definition=graph,
                expected_version=expected,
            )
        except GraphActivationConflict as error:
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "activation-precondition-failed",
                "Activation changed",
                str(error),
                current_version=error.actual_version,
            ) from error
        if activation is None:
            return Response(
                {
                    "definitionId": str(graph.pk),
                    "revisionId": None,
                    "desiredStateVersion": 0,
                }
            )
        response = Response(activation_document(activation))
        response["ETag"] = entity_tag(activation.desired_state_version)
        return response


class RevisionExportView(AudioV1APIView):
    def get(self, request, revision_id):
        return Response(export_graph_revision(_revision_for(request, revision_id)))


class GraphImportView(AudioV1APIView):
    def post(self, request):
        dry_run = parse_boolean(
            request.query_params.get("dryRun", "false"),
            field="dryRun",
        )
        try:
            result = import_graph_bundle(
                require_object(request.data),
                owner=request.user,
                dry_run=dry_run,
            )
        except GraphImportValidationError as error:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "graph-import-invalid",
                "Graph import invalid",
                "The import bundle was not written.",
                errors=_import_issues(error.issues),
            ) from error
        document = {
            "valid": result.valid,
            "dryRun": result.dry_run,
            "created": result.created,
            "definitionId": str(result.definition_id) if result.definition_id else None,
            "revisionId": str(result.revision_id) if result.revision_id else None,
            "issues": _import_issues(result.issues),
        }
        return Response(
            document,
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )
