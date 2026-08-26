from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api.models.orchestration import GraphRevision, GraphRevisionState

from .activations import activate_graph
from .graph_documents import (
    canonical_graph_json,
    graph_content_digest,
    normalize_graph_document,
)
from .graph_validation import GraphValidationResult, validate_graph_structure
from .node_catalogue import NodeTypeRegistry
from .subgraphs import validate_pinned_subgraph_references


class GraphRevisionConflict(RuntimeError):
    pass


class GraphRevisionNotDraft(RuntimeError):
    pass


class GraphPublicationValidationError(ValidationError):
    def __init__(self, result: GraphValidationResult):
        self.result = result
        super().__init__({issue.path: issue.message for issue in result.issues})


@dataclass(frozen=True, slots=True)
class CollectionDifference:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphRevisionComparison:
    semantic_equal: bool
    layout_equal: bool
    left_digest: str
    right_digest: str
    metadata_changed: bool
    collections: Mapping[str, CollectionDifference]


def _collection_by_identity(document, collection, identity):
    values = document.get(collection, [])
    if not isinstance(values, list):
        return {}
    return {
        str(item[identity]): item
        for item in values
        if isinstance(item, Mapping) and identity in item
    }


def compare_graph_revisions(
    left: GraphRevision | Mapping[str, object],
    right: GraphRevision | Mapping[str, object],
) -> GraphRevisionComparison:
    left_document = left.content if isinstance(left, GraphRevision) else left
    right_document = right.content if isinstance(right, GraphRevision) else right
    collections = {}
    for collection, identity in (
        ("parameters", "name"),
        ("publicPorts", "name"),
        ("conditions", "id"),
        ("nodes", "id"),
        ("edges", "id"),
    ):
        left_items = _collection_by_identity(left_document, collection, identity)
        right_items = _collection_by_identity(right_document, collection, identity)
        shared = set(left_items) & set(right_items)
        collections[collection] = CollectionDifference(
            added=tuple(sorted(set(right_items) - set(left_items))),
            removed=tuple(sorted(set(left_items) - set(right_items))),
            changed=tuple(
                sorted(
                    name
                    for name in shared
                    if canonical_graph_json({"item": left_items[name]})
                    != canonical_graph_json({"item": right_items[name]})
                )
            ),
        )
    left_normalized = normalize_graph_document(left_document)
    right_normalized = normalize_graph_document(right_document)
    return GraphRevisionComparison(
        semantic_equal=(
            graph_content_digest(left_document) == graph_content_digest(right_document)
        ),
        layout_equal=(
            canonical_graph_json(left_normalized) == canonical_graph_json(right_normalized)
        ),
        left_digest=graph_content_digest(left_document),
        right_digest=graph_content_digest(right_document),
        metadata_changed=(left_document.get("metadata") != right_document.get("metadata")),
        collections=collections,
    )


def edit_draft_revision(
    *,
    revision_id,
    expected_update_version: int,
    content: Mapping[str, object],
    registry: NodeTypeRegistry | None = None,
) -> GraphRevision:
    if not isinstance(content, Mapping):
        raise ValidationError({"content": "Graph content must be an object."})
    normalized = normalize_graph_document(content)
    validation = validate_graph_structure(normalized, registry=registry)
    digest = graph_content_digest(normalized)
    with transaction.atomic():
        current = (
            GraphRevision.objects.filter(pk=revision_id).values("state", "update_version").first()
        )
        if current is None:
            raise GraphRevision.DoesNotExist(revision_id)
        if current["state"] != GraphRevisionState.DRAFT:
            raise GraphRevisionNotDraft("Published revisions are immutable.")
        if current["update_version"] != expected_update_version:
            raise GraphRevisionConflict(
                f"Expected draft version {expected_update_version}, "
                f"found {current['update_version']}."
            )
        updated = GraphRevision.objects.filter(
            pk=revision_id,
            state=GraphRevisionState.DRAFT,
            update_version=expected_update_version,
        ).update(
            content=normalized,
            content_digest=digest,
            validation_summary=validation.summary(),
            update_version=F("update_version") + 1,
        )
        if updated != 1:
            raise GraphRevisionConflict("Draft changed during the optimistic update.")
    return GraphRevision.objects.get(pk=revision_id)


def publish_draft_revision(
    *,
    revision_id,
    expected_update_version: int,
    registry: NodeTypeRegistry | None = None,
    activate: bool = False,
    expected_activation_version: int = 0,
    parameter_bindings: Mapping[str, object] | None = None,
    scene_bindings: Mapping[str, object] | None = None,
) -> GraphRevision:
    """Publish by compare-and-swap and optionally activate in one transaction."""

    with transaction.atomic():
        revision = GraphRevision.objects.select_related("definition").get(pk=revision_id)
        if revision.state != GraphRevisionState.DRAFT:
            if revision.update_version != expected_update_version:
                raise GraphRevisionConflict("The draft was published by another request.")
            raise GraphRevisionNotDraft("Revision is already published.")
        if revision.update_version != expected_update_version:
            raise GraphRevisionConflict(
                f"Expected draft version {expected_update_version}, "
                f"found {revision.update_version}."
            )
        validation = validate_graph_structure(revision.content, registry=registry)
        reference_issues = validate_pinned_subgraph_references(revision.content)
        if reference_issues:
            validation = GraphValidationResult(
                valid=False,
                issues=validation.issues + reference_issues,
                node_count=validation.node_count,
                edge_count=validation.edge_count,
                path_depth=validation.path_depth,
            )
        if not validation.valid:
            raise GraphPublicationValidationError(validation)
        now = timezone.now()
        updated = GraphRevision.objects.filter(
            pk=revision.pk,
            state=GraphRevisionState.DRAFT,
            update_version=expected_update_version,
        ).update(
            state=GraphRevisionState.PUBLISHED,
            published_at=now,
            validation_summary=validation.summary(),
            update_version=F("update_version") + 1,
        )
        if updated != 1:
            raise GraphRevisionConflict("Draft changed during publication.")
        revision.refresh_from_db()
        if activate:
            activate_graph(
                definition=revision.definition,
                revision=revision,
                expected_version=expected_activation_version,
                parameter_bindings=dict(parameter_bindings or {}),
                scene_bindings=dict(scene_bindings or {}),
            )
        return revision
