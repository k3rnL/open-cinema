from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

from api.models.orchestration import (
    GraphActivation,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)

from .graph_documents import graph_content_digest
from .graph_validation import GraphValidationIssue, validate_graph_structure
from .node_catalogue import NodeTypeRegistry
from .subgraph_compatibility import (
    SubgraphInterfaceComparison,
    compare_subgraph_interfaces,
)
from .subgraph_expansion import expand_subgraphs
from .subgraphs import validate_pinned_subgraph_references


@dataclass(frozen=True, slots=True)
class ParentUpgradeDryRun:
    parent_revision_id: object
    parent_definition_id: object
    valid: bool
    issues: tuple[GraphValidationIssue, ...]
    proposed_document: Mapping[str, object]
    expanded_digest: str | None


@dataclass(frozen=True, slots=True)
class SubgraphUpgradeDryRun:
    valid: bool
    comparison: SubgraphInterfaceComparison
    parents: tuple[ParentUpgradeDryRun, ...]


def _matching_nodes(document, *, definition_id, revision_id):
    nodes = document.get("nodes", [])
    if not isinstance(nodes, list):
        return []
    return [
        node
        for node in nodes
        if isinstance(node, dict)
        and node.get("type") == "core.subgraph-instance"
        and isinstance(node.get("subgraph"), dict)
        and str(node["subgraph"].get("definitionId")) == str(definition_id)
        and str(node["subgraph"].get("revisionId")) == str(revision_id)
    ]


def _deduplicate(issues):
    unique = {}
    for issue in issues:
        unique[(issue.path, issue.code, issue.message)] = issue
    return tuple(unique.values())


def dry_run_subgraph_upgrade(
    *,
    previous_revision: GraphRevision,
    candidate_revision: GraphRevision,
    registry: NodeTypeRegistry | None = None,
) -> SubgraphUpgradeDryRun:
    """Validate all direct parents without changing any immutable pin."""

    if previous_revision.definition_id != candidate_revision.definition_id:
        raise ValueError("subgraph upgrade revisions must belong to one definition")
    if previous_revision.definition.kind != GraphDefinitionKind.SUBGRAPH:
        raise ValueError("upgrade target must be a subgraph definition")
    if previous_revision.state != GraphRevisionState.PUBLISHED:
        raise ValueError("previous subgraph revision must be published")
    if candidate_revision.state != GraphRevisionState.PUBLISHED:
        raise ValueError("candidate subgraph revision must be published")

    affected_revisions = []
    for revision in GraphRevision.objects.select_related("definition").all():
        if _matching_nodes(
            revision.content,
            definition_id=previous_revision.definition_id,
            revision_id=previous_revision.pk,
        ):
            affected_revisions.append(revision)
    comparison = compare_subgraph_interfaces(
        previous_revision.content,
        candidate_revision.content,
        parent_documents=[revision.content for revision in affected_revisions],
        definition_id=str(previous_revision.definition_id),
        previous_revision_id=str(previous_revision.pk),
        registry=registry,
    )

    parent_results = []
    for parent_revision in affected_revisions:
        proposed = deepcopy(parent_revision.content)
        for node in _matching_nodes(
            proposed,
            definition_id=previous_revision.definition_id,
            revision_id=previous_revision.pk,
        ):
            node["subgraph"]["revisionId"] = str(candidate_revision.pk)
        activation = GraphActivation.objects.filter(
            definition_id=parent_revision.definition_id
        ).first()
        activation_bindings = activation.parameter_bindings if activation is not None else {}
        structural = validate_graph_structure(proposed, registry=registry)
        reference_issues = validate_pinned_subgraph_references(proposed)
        expansion = expand_subgraphs(
            proposed,
            activation_bindings=activation_bindings,
            registry=registry,
        )
        expanded_structural = validate_graph_structure(
            dict(expansion.document),
            registry=registry,
        )
        issues = _deduplicate(
            (*structural.issues, *reference_issues, *expansion.issues, *expanded_structural.issues)
        )
        valid = not issues
        parent_results.append(
            ParentUpgradeDryRun(
                parent_revision_id=parent_revision.pk,
                parent_definition_id=parent_revision.definition_id,
                valid=valid,
                issues=issues,
                proposed_document=MappingProxyType(proposed),
                expanded_digest=(graph_content_digest(expansion.document) if valid else None),
            )
        )
    immutable_parents = tuple(parent_results)
    return SubgraphUpgradeDryRun(
        valid=comparison.compatible and all(parent.valid for parent in immutable_parents),
        comparison=comparison,
        parents=immutable_parents,
    )
