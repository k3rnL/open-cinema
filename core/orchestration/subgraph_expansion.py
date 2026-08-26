from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

from django.conf import settings

from .graph_validation import GraphValidationIssue
from .node_catalogue import NodeTypeRegistry
from .parameters import (
    ParameterProvenance,
    ParameterResolution,
    resolve_graph_parameters,
    resolve_subgraph_parameters,
)

SubgraphDocumentLoader = Callable[[str, str], Mapping[str, object] | None]


@dataclass(frozen=True, slots=True)
class ExpandedParameterValue:
    value: object
    provenance: ParameterProvenance


@dataclass(frozen=True, slots=True)
class SubgraphExpansionResult:
    valid: bool
    document: Mapping[str, object]
    parameters: Mapping[str, ExpandedParameterValue]
    issues: tuple[GraphValidationIssue, ...]
    maximum_depth: int


def _database_loader(definition_id: str, revision_id: str):
    from api.models.orchestration import GraphRevision, GraphRevisionState

    try:
        definition_uuid = uuid.UUID(str(definition_id))
        revision_uuid = uuid.UUID(str(revision_id))
    except (TypeError, ValueError, AttributeError):
        return None
    content = (
        GraphRevision.objects.filter(
            pk=revision_uuid,
            definition_id=definition_uuid,
            state=GraphRevisionState.PUBLISHED,
        )
        .values_list("content", flat=True)
        .first()
    )
    return deepcopy(content) if content is not None else None


def _max_depth(value: int | None) -> int:
    candidate = settings.AUDIO_SUBGRAPH_MAX_DEPTH if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 1:
        raise ValueError("subgraph maximum depth must be a positive integer")
    return candidate


def _parameter_issues(prefix, resolution):
    return [
        GraphValidationIssue(
            f"{prefix}{issue.path[1:]}",
            f"parameter_{issue.code}",
            issue.message,
        )
        for issue in resolution.issues
    ]


def _namespace_document(document: dict[str, object], prefix: str) -> dict[str, object]:
    namespaced = deepcopy(document)
    nodes = namespaced.get("nodes", [])
    node_ids = {
        node["id"]: f"{prefix}/{node['id']}"
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    for node in nodes:
        if isinstance(node, dict) and node.get("id") in node_ids:
            node["id"] = node_ids[node["id"]]
    edges = namespaced.get("edges", [])
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if isinstance(edge.get("id"), str):
            edge["id"] = f"{prefix}/{edge['id']}"
        for endpoint in (edge.get("from"), edge.get("to")):
            if isinstance(endpoint, dict) and endpoint.get("node") in node_ids:
                endpoint["node"] = node_ids[endpoint["node"]]
    public_ports = namespaced.get("publicPorts", [])
    for public_port in public_ports:
        if not isinstance(public_port, dict):
            continue
        binding = public_port.get("internalBinding")
        if isinstance(binding, dict) and binding.get("node") in node_ids:
            binding["node"] = node_ids[binding["node"]]
    return namespaced


def _public_mapping(
    document: Mapping[str, object],
) -> dict[str, tuple[str, Mapping[str, object]]]:
    result = {}
    ports = document.get("publicPorts", [])
    if not isinstance(ports, list):
        return result
    for port in ports:
        if (
            isinstance(port, Mapping)
            and isinstance(port.get("name"), str)
            and isinstance(port.get("internalBinding"), Mapping)
        ):
            result[port["name"]] = (port.get("direction"), port["internalBinding"])
    return result


def _expand_document(
    document: Mapping[str, object],
    *,
    parameters: ParameterResolution,
    loader: SubgraphDocumentLoader,
    registry: NodeTypeRegistry | None,
    depth: int,
    maximum_depth: int,
    revision_stack: tuple[str, ...],
    namespace: str,
    expanded_parameters: dict[str, ExpandedParameterValue],
) -> tuple[dict[str, object], list[GraphValidationIssue], int]:
    expanded = deepcopy(dict(document))
    issues: list[GraphValidationIssue] = []
    deepest = depth
    nodes = expanded.get("nodes", [])
    edges = expanded.get("edges", [])
    public_ports = expanded.get("publicPorts", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return expanded, issues, deepest

    for node in list(nodes):
        if not isinstance(node, dict) or node.get("type") != "core.subgraph-instance":
            continue
        instance_id = node.get("id")
        reference = node.get("subgraph")
        if not isinstance(instance_id, str) or not isinstance(reference, Mapping):
            continue
        instance_path = f"{namespace}/{instance_id}" if namespace else instance_id
        next_depth = depth + 1
        deepest = max(deepest, next_depth)
        if next_depth > maximum_depth:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{instance_id!r}].subgraph",
                    "subgraph_depth_exceeded",
                    f"Subgraph depth {next_depth} exceeds limit {maximum_depth}.",
                )
            )
            continue
        definition_id = str(reference.get("definitionId"))
        revision_id = str(reference.get("revisionId"))
        if revision_id in revision_stack:
            chain = " -> ".join((*revision_stack, revision_id))
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{instance_id!r}].subgraph.revisionId",
                    "subgraph_cycle",
                    f"Recursive subgraph revision cycle: {chain}.",
                )
            )
            continue
        child = loader(definition_id, revision_id)
        if child is None:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{instance_id!r}].subgraph.revisionId",
                    "subgraph_revision_unavailable",
                    "Pinned published subgraph revision could not be loaded.",
                )
            )
            continue
        child_parameters = resolve_subgraph_parameters(
            child,
            reference,
            parent=parameters,
        )
        issues.extend(
            _parameter_issues(
                f"$.nodes[{instance_id!r}].subgraph",
                child_parameters,
            )
        )
        for name, value in child_parameters.values.items():
            expanded_parameters[f"{instance_path}.{name}"] = ExpandedParameterValue(
                value=deepcopy(value),
                provenance=child_parameters.provenance[name],
            )
        child_expanded, child_issues, child_depth = _expand_document(
            child,
            parameters=child_parameters,
            loader=loader,
            registry=registry,
            depth=next_depth,
            maximum_depth=maximum_depth,
            revision_stack=(*revision_stack, revision_id),
            namespace=instance_path,
            expanded_parameters=expanded_parameters,
        )
        deepest = max(deepest, child_depth)
        issues.extend(child_issues)
        child_namespaced = _namespace_document(child_expanded, instance_id)
        child_mapping = _public_mapping(child_namespaced)
        aliases = reference.get("portBindings", {})
        aliases = aliases if isinstance(aliases, Mapping) else {}

        def internal_binding(instance_port, expected_direction, path):
            public_name = aliases.get(instance_port, instance_port)
            mapped = child_mapping.get(public_name)
            if mapped is None:
                issues.append(
                    GraphValidationIssue(
                        path,
                        "missing_subgraph_port_binding",
                        f"Instance port {instance_port!r} does not map to a public subgraph port.",
                    )
                )
                return None
            direction, binding = mapped
            if direction != expected_direction:
                issues.append(
                    GraphValidationIssue(
                        path,
                        "subgraph_port_direction",
                        f"Instance port {instance_port!r} maps to a {direction!r} public port.",
                    )
                )
                return None
            return deepcopy(dict(binding))

        for edge_index, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            source = edge.get("from")
            target = edge.get("to")
            if isinstance(source, dict) and source.get("node") == instance_id:
                replacement = internal_binding(
                    source.get("port"),
                    "output",
                    f"$.edges[{edge_index}].from",
                )
                if replacement is not None:
                    edge["from"] = replacement
            if isinstance(target, dict) and target.get("node") == instance_id:
                replacement = internal_binding(
                    target.get("port"),
                    "input",
                    f"$.edges[{edge_index}].to",
                )
                if replacement is not None:
                    edge["to"] = replacement
        if isinstance(public_ports, list):
            for port_index, public_port in enumerate(public_ports):
                if not isinstance(public_port, dict):
                    continue
                binding = public_port.get("internalBinding")
                if isinstance(binding, dict) and binding.get("node") == instance_id:
                    replacement = internal_binding(
                        binding.get("port"),
                        public_port.get("direction"),
                        f"$.publicPorts[{port_index}].internalBinding",
                    )
                    if replacement is not None:
                        public_port["internalBinding"] = replacement

        nodes.remove(node)
        nodes.extend(child_namespaced.get("nodes", []))
        edges.extend(child_namespaced.get("edges", []))

    return expanded, issues, deepest


def expand_subgraphs(
    document: Mapping[str, object],
    *,
    activation_bindings: Mapping[str, object] | None = None,
    loader: SubgraphDocumentLoader | None = None,
    registry: NodeTypeRegistry | None = None,
    maximum_depth: int | None = None,
) -> SubgraphExpansionResult:
    """Expand pinned subgraphs into one namespaced detached graph document."""

    limit = _max_depth(maximum_depth)
    root_parameters = resolve_graph_parameters(document, activation_bindings)
    expanded_parameters = {
        f"$root.{name}": ExpandedParameterValue(
            value=deepcopy(value),
            provenance=root_parameters.provenance[name],
        )
        for name, value in root_parameters.values.items()
    }
    expanded, issues, deepest = _expand_document(
        document,
        parameters=root_parameters,
        loader=loader or _database_loader,
        registry=registry,
        depth=0,
        maximum_depth=limit,
        revision_stack=(),
        namespace="",
        expanded_parameters=expanded_parameters,
    )
    issues = _parameter_issues("$", root_parameters) + issues
    return SubgraphExpansionResult(
        valid=not issues,
        document=MappingProxyType(expanded),
        parameters=MappingProxyType(expanded_parameters),
        issues=tuple(issues),
        maximum_depth=deepest,
    )
