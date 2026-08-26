from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import uuid

from .graph_validation import (
    GraphValidationIssue,
    GraphValidationResult,
    validate_graph_structure,
)
from .node_catalogue import NodeTypeRegistry
from .parameters import ParameterDefinition, parse_parameter_definitions
from .signal_contracts import (
    PortContract,
    PortDirection,
    SignalContract,
)


@dataclass(frozen=True, slots=True)
class SubgraphInterfacePort:
    name: str
    direction: PortDirection
    contract: SignalContract
    internal_node: str
    internal_port: str


@dataclass(frozen=True, slots=True)
class SubgraphInterface:
    parameters: tuple[ParameterDefinition, ...]
    ports: tuple[SubgraphInterfacePort, ...]


@dataclass(frozen=True, slots=True)
class SubgraphInterfaceValidation:
    valid: bool
    interface: SubgraphInterface | None
    issues: tuple[GraphValidationIssue, ...]
    structural: GraphValidationResult


def validate_pinned_subgraph_references(
    document: Mapping[str, object],
) -> tuple[GraphValidationIssue, ...]:
    """Resolve every instance to one existing immutable subgraph revision."""

    from api.models.orchestration import (
        GraphDefinition,
        GraphDefinitionKind,
        GraphRevision,
        GraphRevisionState,
    )

    issues: list[GraphValidationIssue] = []
    nodes = document.get("nodes", [])
    if not isinstance(nodes, list):
        return ()
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping) or node.get("type") != "core.subgraph-instance":
            continue
        reference = node.get("subgraph")
        if not isinstance(reference, Mapping):
            continue
        try:
            definition_id = uuid.UUID(str(reference.get("definitionId")))
        except (TypeError, ValueError, AttributeError):
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph.definitionId",
                    "invalid_subgraph_definition_id",
                    "Pinned subgraph definition ID must be a UUID.",
                )
            )
            definition_id = None
        try:
            revision_id = uuid.UUID(str(reference.get("revisionId")))
        except (TypeError, ValueError, AttributeError):
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph.revisionId",
                    "invalid_subgraph_revision_id",
                    "Pinned subgraph revision ID must be a UUID.",
                )
            )
            revision_id = None
        definition = (
            GraphDefinition.objects.filter(pk=definition_id).first()
            if definition_id is not None
            else None
        )
        revision = (
            GraphRevision.objects.filter(pk=revision_id).first()
            if revision_id is not None
            else None
        )
        if definition_id is not None and definition is None:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph.definitionId",
                    "missing_subgraph_definition",
                    "Pinned subgraph definition does not exist.",
                )
            )
        elif definition is not None and definition.kind != GraphDefinitionKind.SUBGRAPH:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph.definitionId",
                    "referenced_definition_not_subgraph",
                    "Pinned definition is not a subgraph.",
                )
            )
        if revision_id is not None and revision is None:
            issues.append(
                GraphValidationIssue(
                    f"$.nodes[{index}].subgraph.revisionId",
                    "missing_subgraph_revision",
                    "Pinned subgraph revision does not exist.",
                )
            )
        elif revision is not None:
            if definition is not None and revision.definition_id != definition.pk:
                issues.append(
                    GraphValidationIssue(
                        f"$.nodes[{index}].subgraph.revisionId",
                        "subgraph_revision_definition_mismatch",
                        "Pinned revision belongs to another definition.",
                    )
                )
            if revision.state != GraphRevisionState.PUBLISHED:
                issues.append(
                    GraphValidationIssue(
                        f"$.nodes[{index}].subgraph.revisionId",
                        "mutable_subgraph_revision",
                        "Subgraph instances must pin a published immutable revision.",
                    )
                )
            if revision.content.get("kind") != "subgraph":
                issues.append(
                    GraphValidationIssue(
                        f"$.nodes[{index}].subgraph.revisionId",
                        "revision_content_not_subgraph",
                        "Pinned revision content is not a subgraph document.",
                    )
                )
    return tuple(issues)


def _signal_compatibility(
    public_direction: PortDirection,
    public: SignalContract,
    internal: PortContract,
):
    if public_direction == PortDirection.INPUT:
        external = PortContract("external", PortDirection.OUTPUT, public)
        return external.compatibility_with(internal)
    external = PortContract("external", PortDirection.INPUT, public)
    return internal.compatibility_with(external)


def _dynamic_subgraph_port(node, port_name):
    from api.models.orchestration import GraphRevision, GraphRevisionState

    reference = node.get("subgraph")
    if not isinstance(reference, Mapping):
        return None
    aliases = reference.get("portBindings", {})
    aliases = aliases if isinstance(aliases, Mapping) else {}
    public_name = aliases.get(port_name, port_name)
    try:
        revision_id = uuid.UUID(str(reference.get("revisionId")))
    except (TypeError, ValueError, AttributeError):
        return None
    content = (
        GraphRevision.objects.filter(
            pk=revision_id,
            state=GraphRevisionState.PUBLISHED,
        )
        .values_list("content", flat=True)
        .first()
    )
    if not isinstance(content, Mapping):
        return None
    for public_port in content.get("publicPorts", []):
        if isinstance(public_port, Mapping) and public_port.get("name") == public_name:
            try:
                return PortContract(
                    name=str(port_name),
                    direction=PortDirection(public_port.get("direction")),
                    signal=SignalContract.from_document(public_port.get("contract")),
                )
            except (TypeError, ValueError):
                return None
    return None


def validate_subgraph_interface(
    document: Mapping[str, object],
    *,
    registry: NodeTypeRegistry | None = None,
) -> SubgraphInterfaceValidation:
    """Validate the reusable boundary in addition to ordinary graph structure."""

    structural = validate_graph_structure(document, registry=registry)
    issues = list(structural.issues)
    interface_valid = True
    if document.get("kind") != "subgraph":
        interface_valid = False
        issues.append(
            GraphValidationIssue(
                "$.kind",
                "not_a_subgraph",
                "Reusable interfaces require graph kind 'subgraph'.",
            )
        )

    parameter_definitions, parameter_issues = parse_parameter_definitions(document)
    if parameter_issues:
        interface_valid = False
    issues.extend(
        GraphValidationIssue(issue.path, f"parameter_{issue.code}", issue.message)
        for issue in parameter_issues
    )

    node_types = {}
    node_ports = {}
    node_documents = {}
    effective_registry = registry
    if effective_registry is None:
        from .audio_node_catalogue import audio_node_type_registry

        effective_registry = audio_node_type_registry()
    nodes = document.get("nodes", [])
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            node_id = node.get("id")
            definition = effective_registry.get(node.get("type"), node.get("version"))
            if isinstance(node_id, str) and definition is not None:
                node_types[node_id] = definition
                node_documents[node_id] = node
                node_ports[node_id] = {
                    port.contract.name: port.contract for port in definition.ports
                }

    interface_ports: list[SubgraphInterfacePort] = []
    public_ports = document.get("publicPorts", [])
    if isinstance(public_ports, list):
        for index, public_port in enumerate(public_ports):
            if not isinstance(public_port, Mapping):
                continue
            binding = public_port.get("internalBinding")
            if not isinstance(binding, Mapping):
                interface_valid = False
                issues.append(
                    GraphValidationIssue(
                        f"$.publicPorts[{index}].internalBinding",
                        "missing_internal_binding",
                        "Every subgraph public port must map to an internal port.",
                    )
                )
                continue
            node_id = binding.get("node")
            port_name = binding.get("port")
            internal = node_ports.get(node_id, {}).get(port_name)
            definition = node_types.get(node_id)
            if internal is None and definition is not None and definition.allows_dynamic_ports:
                internal = _dynamic_subgraph_port(
                    node_documents[node_id],
                    port_name,
                )
            if internal is None:
                if definition is not None and definition.allows_dynamic_ports:
                    interface_valid = False
                    issues.append(
                        GraphValidationIssue(
                            f"$.publicPorts[{index}].internalBinding",
                            "unresolved_dynamic_public_binding",
                            "Nested subgraph public port could not be resolved from its pin.",
                        )
                    )
                continue
            try:
                direction = PortDirection(public_port.get("direction"))
                contract = SignalContract.from_document(public_port.get("contract"))
            except (TypeError, ValueError) as error:
                interface_valid = False
                issues.append(
                    GraphValidationIssue(
                        f"$.publicPorts[{index}].contract",
                        "invalid_public_contract",
                        str(error),
                    )
                )
                continue
            if direction != internal.direction:
                interface_valid = False
                continue
            compatibility = _signal_compatibility(direction, contract, internal)
            if not compatibility.compatible:
                interface_valid = False
                issues.append(
                    GraphValidationIssue(
                        f"$.publicPorts[{index}].contract",
                        "incompatible_public_contract",
                        "Public and internal signal contracts are incompatible: "
                        f"{', '.join(compatibility.reasons)}.",
                    )
                )
                continue
            interface_ports.append(
                SubgraphInterfacePort(
                    name=public_port["name"],
                    direction=direction,
                    contract=contract,
                    internal_node=node_id,
                    internal_port=port_name,
                )
            )

    immutable_issues = tuple(issues)
    interface = None
    if interface_valid:
        interface = SubgraphInterface(
            parameters=tuple(parameter_definitions[name] for name in sorted(parameter_definitions)),
            ports=tuple(sorted(interface_ports, key=lambda port: port.name)),
        )
    return SubgraphInterfaceValidation(
        valid=not immutable_issues,
        interface=interface,
        issues=immutable_issues,
        structural=structural,
    )
