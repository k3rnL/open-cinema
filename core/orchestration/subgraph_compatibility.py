from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .node_catalogue import NodeTypeRegistry
from .parameters import ParameterDefinition
from .subgraphs import SubgraphInterface, validate_subgraph_interface


@dataclass(frozen=True, slots=True)
class InterfaceChange:
    resource: str
    name: str
    field: str
    compatible: bool
    message: str


@dataclass(frozen=True, slots=True)
class AffectedParentBinding:
    parent_graph_id: str
    instance_id: str
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class SubgraphInterfaceComparison:
    compatible: bool
    changes: tuple[InterfaceChange, ...]
    affected_bindings: tuple[AffectedParentBinding, ...]


def _parameter_changes(
    previous: Mapping[str, ParameterDefinition],
    candidate: Mapping[str, ParameterDefinition],
) -> list[InterfaceChange]:
    changes = []
    for name in sorted(set(previous) - set(candidate)):
        changes.append(
            InterfaceChange(
                "parameter",
                name,
                "removed",
                False,
                f"Parameter {name!r} was removed.",
            )
        )
    for name in sorted(set(candidate) - set(previous)):
        definition = candidate[name]
        compatible = not definition.required or definition.has_default
        changes.append(
            InterfaceChange(
                "parameter",
                name,
                "added",
                compatible,
                (
                    f"Required parameter {name!r} was added without a default."
                    if not compatible
                    else f"Optional/defaulted parameter {name!r} was added."
                ),
            )
        )
    fields = (
        ("parameter_type", "type"),
        ("required", "required"),
        ("enum", "enum"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("min_length", "minLength"),
        ("max_length", "maxLength"),
        ("items", "items"),
    )
    for name in sorted(set(previous) & set(candidate)):
        old = previous[name]
        new = candidate[name]
        for attribute, label in fields:
            if getattr(old, attribute) != getattr(new, attribute):
                changes.append(
                    InterfaceChange(
                        "parameter",
                        name,
                        label,
                        False,
                        f"Parameter {name!r} changed {label}.",
                    )
                )
        if old.has_default != new.has_default or (old.has_default and old.default != new.default):
            changes.append(
                InterfaceChange(
                    "parameter",
                    name,
                    "default",
                    False,
                    f"Parameter {name!r} changed its default.",
                )
            )
    return changes


def _interface(document, registry) -> SubgraphInterface:
    validation = validate_subgraph_interface(document, registry=registry)
    if validation.interface is None:
        messages = "; ".join(issue.message for issue in validation.issues)
        raise ValueError(f"cannot compare invalid subgraph interface: {messages}")
    return validation.interface


def compare_subgraph_interfaces(
    previous_document: Mapping[str, object],
    candidate_document: Mapping[str, object],
    *,
    parent_documents: Iterable[Mapping[str, object]] = (),
    definition_id: str | None = None,
    previous_revision_id: str | None = None,
    registry: NodeTypeRegistry | None = None,
) -> SubgraphInterfaceComparison:
    previous = _interface(previous_document, registry)
    candidate = _interface(candidate_document, registry)
    previous_ports = {port.name: port for port in previous.ports}
    candidate_ports = {port.name: port for port in candidate.ports}
    changes: list[InterfaceChange] = []
    for name in sorted(set(previous_ports) - set(candidate_ports)):
        changes.append(
            InterfaceChange("port", name, "removed", False, f"Port {name!r} was removed.")
        )
    for name in sorted(set(candidate_ports) - set(previous_ports)):
        changes.append(InterfaceChange("port", name, "added", True, f"Port {name!r} was added."))
    for name in sorted(set(previous_ports) & set(candidate_ports)):
        old = previous_ports[name]
        new = candidate_ports[name]
        if old.direction != new.direction:
            changes.append(
                InterfaceChange(
                    "port", name, "direction", False, f"Port {name!r} changed direction."
                )
            )
        if old.contract.to_document() != new.contract.to_document():
            changes.append(
                InterfaceChange(
                    "port",
                    name,
                    "contract",
                    False,
                    f"Port {name!r} changed its signal contract.",
                )
            )
    previous_parameters = {parameter.name: parameter for parameter in previous.parameters}
    candidate_parameters = {parameter.name: parameter for parameter in candidate.parameters}
    changes.extend(_parameter_changes(previous_parameters, candidate_parameters))

    affected_names = {(change.resource, change.name) for change in changes if not change.compatible}
    affected: list[AffectedParentBinding] = []
    for parent in parent_documents:
        parent_id = str(parent.get("id", "unknown-parent"))
        nodes = parent.get("nodes", [])
        if not isinstance(nodes, list):
            continue
        for node_index, node in enumerate(nodes):
            if not isinstance(node, Mapping) or node.get("type") != "core.subgraph-instance":
                continue
            reference = node.get("subgraph")
            if not isinstance(reference, Mapping):
                continue
            if definition_id is not None and str(reference.get("definitionId")) != str(
                definition_id
            ):
                continue
            if previous_revision_id is not None and str(reference.get("revisionId")) != str(
                previous_revision_id
            ):
                continue
            instance_id = str(node.get("id", f"node-{node_index}"))
            parameter_bindings = reference.get("parameterBindings", {})
            parameter_bindings = (
                parameter_bindings if isinstance(parameter_bindings, Mapping) else {}
            )
            port_bindings = reference.get("portBindings", {})
            port_bindings = port_bindings if isinstance(port_bindings, Mapping) else {}
            for resource, name in sorted(affected_names):
                if resource == "parameter" and name in parameter_bindings:
                    affected.append(
                        AffectedParentBinding(
                            parent_id,
                            instance_id,
                            f"$.nodes[{node_index}].subgraph.parameterBindings[{name!r}]",
                            f"Binding uses changed parameter {name!r}.",
                        )
                    )
                if resource == "parameter" and name in candidate_parameters:
                    definition = candidate_parameters[name]
                    if (
                        definition.required
                        and not definition.has_default
                        and name not in parameter_bindings
                    ):
                        affected.append(
                            AffectedParentBinding(
                                parent_id,
                                instance_id,
                                f"$.nodes[{node_index}].subgraph.parameterBindings",
                                f"New required parameter {name!r} is unbound.",
                            )
                        )
                if resource == "port" and name in port_bindings.values():
                    aliases = [
                        alias for alias, public_name in port_bindings.items() if public_name == name
                    ]
                    for alias in sorted(aliases):
                        affected.append(
                            AffectedParentBinding(
                                parent_id,
                                instance_id,
                                f"$.nodes[{node_index}].subgraph.portBindings[{alias!r}]",
                                f"Binding uses changed public port {name!r}.",
                            )
                        )
    return SubgraphInterfaceComparison(
        compatible=all(change.compatible for change in changes) and not affected,
        changes=tuple(changes),
        affected_bindings=tuple(affected),
    )
