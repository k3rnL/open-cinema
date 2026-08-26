from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

from .condition_validation import validate_condition_document
from .fact_catalogue import core_fact_catalogue
from .graph_documents import canonical_graph_json
from .graph_schema import desired_graph_envelope_validator
from .node_catalogue import (
    NodePortDefinition,
    NodeTypeDefinition,
    NodeTypeRegistry,
    PortCardinality,
)
from .signal_contracts import PortDirection


class GraphIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class GraphValidationIssue:
    path: str
    code: str
    message: str
    severity: GraphIssueSeverity = GraphIssueSeverity.ERROR

    def to_document(self) -> dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class GraphValidationLimits:
    max_nodes: int
    max_edges: int
    max_path_depth: int
    max_document_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "max_nodes",
            "max_edges",
            "max_path_depth",
            "max_document_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_settings(cls) -> "GraphValidationLimits":
        values = settings.AUDIO_GRAPH_VALIDATION_LIMITS
        expected = {
            "max_nodes",
            "max_edges",
            "max_path_depth",
            "max_document_bytes",
        }
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError(
                "AUDIO_GRAPH_VALIDATION_LIMITS must define exactly "
                f"{', '.join(sorted(expected))}"
            )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class GraphValidationResult:
    valid: bool
    issues: tuple[GraphValidationIssue, ...]
    node_count: int
    edge_count: int
    path_depth: int | None

    def summary(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": [issue.to_document() for issue in self.issues],
            "nodeCount": self.node_count,
            "edgeCount": self.edge_count,
            "pathDepth": self.path_depth,
        }


def _path(prefix: str, parts) -> str:
    return prefix + "".join(f"[{part!r}]" for part in parts)


def _duplicates(values) -> set[object]:
    return {value for value, count in Counter(values).items() if count > 1}


def _port_map(definition: NodeTypeDefinition) -> dict[str, NodePortDefinition]:
    return {port.contract.name: port for port in definition.ports}


def _strongly_connected_components(
    node_ids: set[str],
    adjacency: Mapping[str, list[str]],
) -> list[set[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[set[str]] = []

    def connect(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in adjacency.get(node_id, []):
            if target not in indices:
                connect(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] == indices[node_id]:
            component = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node_id:
                    break
            components.append(component)

    for node_id in sorted(node_ids):
        if node_id not in indices:
            connect(node_id)
    return components


def _path_depth(node_ids: set[str], adjacency: Mapping[str, list[str]]) -> int | None:
    indegrees = {node_id: 0 for node_id in node_ids}
    for targets in adjacency.values():
        for target in targets:
            if target in indegrees:
                indegrees[target] += 1
    queue = deque(sorted(node_id for node_id, degree in indegrees.items() if degree == 0))
    depths = {node_id: 1 for node_id in queue}
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for target in adjacency.get(node_id, []):
            if target not in indegrees:
                continue
            depths[target] = max(depths.get(target, 1), depths[node_id] + 1)
            indegrees[target] -= 1
            if indegrees[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        return None
    return max(depths.values(), default=0)


def validate_graph_structure(
    document: Mapping[str, object],
    *,
    registry: NodeTypeRegistry | None = None,
    limits: GraphValidationLimits | None = None,
) -> GraphValidationResult:
    """Validate persisted structure without observing runtime availability."""

    if registry is None:
        from .audio_node_catalogue import audio_node_type_registry

        registry = audio_node_type_registry()
    limits = limits or GraphValidationLimits.from_settings()
    issues: list[GraphValidationIssue] = []
    if not isinstance(document, Mapping):
        return GraphValidationResult(
            valid=False,
            issues=(GraphValidationIssue("$", "invalid_document", "Graph must be an object."),),
            node_count=0,
            edge_count=0,
            path_depth=None,
        )

    for error in sorted(
        desired_graph_envelope_validator().iter_errors(dict(document)),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        issues.append(
            GraphValidationIssue(
                _path("$", error.absolute_path),
                f"schema_{error.validator}",
                error.message,
            )
        )
    try:
        document_size = len(canonical_graph_json(document).encode("utf-8"))
    except (TypeError, ValueError) as error:
        issues.append(GraphValidationIssue("$", "invalid_json", str(error)))
        document_size = 0
    if document_size > limits.max_document_bytes:
        issues.append(
            GraphValidationIssue(
                "$",
                "document_size_exceeded",
                f"Graph uses {document_size} bytes; limit is {limits.max_document_bytes}.",
            )
        )

    nodes = document.get("nodes")
    edges = document.get("edges")
    nodes = nodes if isinstance(nodes, list) else []
    edges = edges if isinstance(edges, list) else []

    parameter_definitions = [
        parameter
        for parameter in document.get("parameters", [])
        if isinstance(parameter, Mapping)
        and isinstance(parameter.get("name"), str)
        and parameter.get("type")
        in {"boolean", "integer", "number", "string", "enum", "object", "array"}
        and (parameter.get("type") != "enum" or isinstance(parameter.get("enum"), list))
    ]
    try:
        fact_catalogue = core_fact_catalogue().with_graph_parameters(parameter_definitions)
    except ValueError:
        fact_catalogue = core_fact_catalogue()

    def validate_condition(expression: object, path: str) -> None:
        result = validate_condition_document(
            {"version": 1, "expression": expression},
            catalogue=fact_catalogue,
        )
        for issue in result.issues:
            if issue.path == "$.expression":
                issue_path = path
            elif issue.path.startswith("$.expression"):
                issue_path = path + issue.path.removeprefix("$.expression")
            elif issue.path == "$":
                issue_path = path
            else:
                issue_path = path + issue.path.removeprefix("$")
            issues.append(
                GraphValidationIssue(
                    issue_path,
                    f"condition_{issue.code}",
                    issue.message,
                )
            )

    conditions = document.get("conditions")
    if isinstance(conditions, list):
        for index, condition in enumerate(conditions):
            if isinstance(condition, Mapping) and "expression" in condition:
                validate_condition(
                    condition["expression"],
                    f"$.conditions[{index}].expression",
                )
    if len(nodes) > limits.max_nodes:
        issues.append(
            GraphValidationIssue(
                "$.nodes",
                "node_limit_exceeded",
                f"Graph has {len(nodes)} nodes; limit is {limits.max_nodes}.",
            )
        )
    if len(edges) > limits.max_edges:
        issues.append(
            GraphValidationIssue(
                "$.edges",
                "edge_limit_exceeded",
                f"Graph has {len(edges)} edges; limit is {limits.max_edges}.",
            )
        )

    for collection, identity in (
        ("parameters", "name"),
        ("publicPorts", "name"),
        ("conditions", "id"),
        ("nodes", "id"),
        ("edges", "id"),
    ):
        values = document.get(collection)
        if not isinstance(values, list):
            continue
        identities = [
            item.get(identity)
            for item in values
            if isinstance(item, Mapping) and isinstance(item.get(identity), str)
        ]
        for duplicate in sorted(_duplicates(identities), key=str):
            issues.append(
                GraphValidationIssue(
                    f"$.{collection}",
                    f"duplicate_{identity}",
                    f"Duplicate {identity} {duplicate!r}.",
                )
            )

    node_by_id = {
        node.get("id"): node
        for node in nodes
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    }
    node_index = {
        node.get("id"): index
        for index, node in enumerate(nodes)
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    }
    definitions: dict[str, NodeTypeDefinition] = {}
    ports: dict[str, dict[str, NodePortDefinition]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        type_id = node.get("type")
        version = node.get("version")
        if not isinstance(node_id, str) or not isinstance(type_id, str):
            continue
        condition_use = node.get("condition")
        if isinstance(condition_use, Mapping) and "expression" in condition_use:
            validate_condition(
                condition_use["expression"],
                f"$.nodes[{index}].condition.expression",
            )
        definition = (
            registry.get(type_id, version)
            if isinstance(version, int) and not isinstance(version, bool)
            else None
        )
        if definition is None:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].type",
                    "node_type_unavailable",
                    f"Node type {type_id!r} v{version!r} is not registered.",
                )
            )
            continue
        definitions[node_id] = definition
        ports[node_id] = _port_map(definition)
        for config_issue in definition.validate_configuration(node.get("configuration")):
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].configuration{config_issue.path[1:]}",
                    f"configuration_{config_issue.code}",
                    config_issue.message,
                )
            )
        configuration = node.get("configuration")
        if isinstance(configuration, Mapping):
            embedded_condition = configuration.get("condition")
            if isinstance(embedded_condition, Mapping):
                validate_condition(
                    embedded_condition,
                    f"$.nodes[{index}].configuration.condition",
                )
            candidates = configuration.get("candidates")
            if isinstance(candidates, list):
                for candidate_index, candidate in enumerate(candidates):
                    if isinstance(candidate, Mapping) and isinstance(
                        candidate.get("eligibleWhen"), Mapping
                    ):
                        validate_condition(
                            candidate["eligibleWhen"],
                            f"$.nodes[{index}].configuration.candidates"
                            f"[{candidate_index}].eligibleWhen",
                        )
        has_subgraph = isinstance(node.get("subgraph"), Mapping)
        if definition.requires_subgraph_reference and not has_subgraph:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph",
                    "missing_subgraph_reference",
                    "This node type requires a pinned subgraph reference.",
                )
            )
        if not definition.requires_subgraph_reference and has_subgraph:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph",
                    "unexpected_subgraph_reference",
                    "This node type cannot contain a subgraph reference.",
                )
            )

    incoming = Counter()
    outgoing = Counter()
    edge_shapes = []
    adjacency: dict[str, list[str]] = defaultdict(list)
    structurally_linked_edges: list[tuple[int, str, str]] = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            continue
        condition_use = edge.get("condition")
        if isinstance(condition_use, Mapping) and "expression" in condition_use:
            validate_condition(
                condition_use["expression"],
                f"$.edges[{index}].condition.expression",
            )
        source = edge.get("from")
        target = edge.get("to")
        if not isinstance(source, Mapping) or not isinstance(target, Mapping):
            continue
        source_node = source.get("node")
        source_port_name = source.get("port")
        target_node = target.get("node")
        target_port_name = target.get("port")
        shape = (source_node, source_port_name, target_node, target_port_name)
        if all(isinstance(value, str) for value in shape):
            edge_shapes.append(shape)
        source_exists = isinstance(source_node, str) and source_node in node_by_id
        target_exists = isinstance(target_node, str) and target_node in node_by_id
        if not source_exists:
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].from.node",
                    "unknown_source_node",
                    f"Source node {source_node!r} does not exist.",
                )
            )
        if not target_exists:
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].to.node",
                    "unknown_target_node",
                    f"Target node {target_node!r} does not exist.",
                )
            )
        source_definition = definitions.get(source_node) if source_exists else None
        target_definition = definitions.get(target_node) if target_exists else None
        source_port = (
            ports.get(source_node, {}).get(source_port_name)
            if source_exists and isinstance(source_port_name, str)
            else None
        )
        target_port = (
            ports.get(target_node, {}).get(target_port_name)
            if target_exists and isinstance(target_port_name, str)
            else None
        )
        if (
            source_exists
            and source_definition
            and source_port is None
            and not source_definition.allows_dynamic_ports
        ):
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].from.port",
                    "unknown_source_port",
                    f"Source port {source_port_name!r} is not declared.",
                )
            )
        if (
            target_exists
            and target_definition
            and target_port is None
            and not target_definition.allows_dynamic_ports
        ):
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].to.port",
                    "unknown_target_port",
                    f"Target port {target_port_name!r} is not declared.",
                )
            )
        if source_port and source_port.contract.direction != PortDirection.OUTPUT:
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].from.port",
                    "source_port_direction",
                    "An edge source must be an output port.",
                )
            )
        if target_port and target_port.contract.direction != PortDirection.INPUT:
            issues.append(
                GraphValidationIssue(
                    f"$.edges[{index}].to.port",
                    "target_port_direction",
                    "An edge target must be an input port.",
                )
            )
        if source_port and target_port:
            compatibility = source_port.contract.compatibility_with(target_port.contract)
            for reason in compatibility.reasons:
                if reason in {"source_direction", "target_direction"}:
                    continue
                issues.append(
                    GraphValidationIssue(
                        f"$.edges[{index}]",
                        "incompatible_ports",
                        f"Port contracts are incompatible: {reason}.",
                    )
                )
        if source_port:
            outgoing[(source_node, source_port_name)] += 1
        if target_port:
            incoming[(target_node, target_port_name)] += 1
        if source_exists and target_exists:
            adjacency[source_node].append(target_node)
            structurally_linked_edges.append((index, source_node, target_node))

    for duplicate in _duplicates(edge_shapes):
        issues.append(
            GraphValidationIssue(
                "$.edges",
                "duplicate_edge",
                f"Duplicate connection from {duplicate[0]!r}:{duplicate[1]!r} "
                f"to {duplicate[2]!r}:{duplicate[3]!r}.",
            )
        )

    public_ports = document.get("publicPorts")
    if isinstance(public_ports, list):
        for index, public_port in enumerate(public_ports):
            if not isinstance(public_port, Mapping):
                continue
            binding = public_port.get("internalBinding")
            if not isinstance(binding, Mapping):
                continue
            node_id = binding.get("node")
            port_name = binding.get("port")
            port = ports.get(node_id, {}).get(port_name)
            direction = public_port.get("direction")
            if port is None:
                definition = definitions.get(node_id)
                if definition is None or not definition.allows_dynamic_ports:
                    issues.append(
                        GraphValidationIssue(
                            f"$.publicPorts[{index}].internalBinding",
                            "unknown_public_port_binding",
                            "Public port binding does not resolve to a node port.",
                        )
                    )
                continue
            if port.contract.direction.value != direction:
                issues.append(
                    GraphValidationIssue(
                        f"$.publicPorts[{index}].internalBinding",
                        "public_port_direction",
                        "Public and internal port directions must match.",
                    )
                )
            if direction == PortDirection.INPUT.value:
                incoming[(node_id, port_name)] += 1
            elif direction == PortDirection.OUTPUT.value:
                outgoing[(node_id, port_name)] += 1

    for node_id, definition in definitions.items():
        for port in definition.ports:
            key = (node_id, port.contract.name)
            count = (
                incoming[key] if port.contract.direction == PortDirection.INPUT else outgoing[key]
            )
            path = f"$.nodes[{node_index[node_id]}]"
            if not port.contract.optional and count == 0:
                issues.append(
                    GraphValidationIssue(
                        path,
                        "required_port_unconnected",
                        f"Required {port.contract.direction.value} port "
                        f"{port.contract.name!r} is unconnected.",
                    )
                )
            if port.cardinality == PortCardinality.SINGLE and count > 1:
                issues.append(
                    GraphValidationIssue(
                        path,
                        "port_cardinality_exceeded",
                        f"Single port {port.contract.name!r} has {count} connections.",
                    )
                )

    components = _strongly_connected_components(set(node_by_id), adjacency)
    for component in components:
        component_edges = [
            edge
            for edge in structurally_linked_edges
            if edge[1] in component and edge[2] in component
        ]
        has_cycle = len(component) > 1 or any(
            source == target for _, source, target in component_edges
        )
        if has_cycle and not all(
            definitions.get(node_id) and definitions[node_id].allows_feedback
            for node_id in component
        ):
            participants = ", ".join(sorted(component))
            for edge_index, _, _ in component_edges:
                issues.append(
                    GraphValidationIssue(
                        f"$.edges[{edge_index}]",
                        "unsupported_feedback_cycle",
                        f"Unsupported feedback cycle includes {participants}.",
                    )
                )

    path_depth = _path_depth(set(node_by_id), adjacency)
    if path_depth is not None and path_depth > limits.max_path_depth:
        issues.append(
            GraphValidationIssue(
                "$.nodes",
                "path_depth_exceeded",
                f"Graph path depth is {path_depth}; limit is {limits.max_path_depth}.",
            )
        )
    immutable_issues = tuple(issues)
    return GraphValidationResult(
        valid=not any(issue.severity == GraphIssueSeverity.ERROR for issue in issues),
        issues=immutable_issues,
        node_count=len(nodes),
        edge_count=len(edges),
        path_depth=path_depth,
    )
