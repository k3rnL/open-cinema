from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from wyreplumber.runtime import FrozenDict

from .node_catalogue import NodeTypeRegistry
from .signal_contracts import (
    AudioContent,
    LatencyRange,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from .signal_descriptors import AudioFormatDescriptor, SignalContentKind, SignalDescriptor


@dataclass(frozen=True, slots=True)
class SignalNegotiationResult:
    compatible: bool
    contract: SignalContract | None
    reasons: tuple[str, ...]
    decisions: FrozenDict


@dataclass(frozen=True, slots=True)
class SignalPropagationIssue:
    edge_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignalPropagationResult:
    compatible: bool
    edge_contracts: FrozenDict
    port_contracts: FrozenDict
    issues: tuple[SignalPropagationIssue, ...]


def _intersection(first: tuple[object, ...], second: tuple[object, ...]):
    if first and second:
        return tuple(sorted(set(first).intersection(second)))
    return first or second


def _latency_intersection(
    first: LatencyRange | None,
    second: LatencyRange | None,
) -> LatencyRange | None:
    if first is None:
        return second
    if second is None:
        return first
    minimums = [value for value in (first.minimum_ms, second.minimum_ms) if value is not None]
    maximums = [value for value in (first.maximum_ms, second.maximum_ms) if value is not None]
    minimum = max(minimums) if minimums else None
    maximum = min(maximums) if maximums else None
    if minimum is not None and maximum is not None and minimum > maximum:
        return None
    return LatencyRange(minimum, maximum)


def negotiate_signal_contracts(
    source: SignalContract,
    target: SignalContract,
) -> SignalNegotiationResult:
    """Narrow two compatible contracts without choosing by iteration order."""

    if not isinstance(source, SignalContract) or not isinstance(target, SignalContract):
        raise TypeError("source and target must be SignalContract values")
    reasons = []
    if source.media_kind != target.media_kind:
        reasons.append("media_kind")
    concrete_content = {
        content for content in (source.content, target.content) if content is not AudioContent.ANY
    }
    if len(concrete_content) > 1:
        reasons.append("content")
    dimensions = {
        "codecs": _intersection(source.codecs, target.codecs),
        "sampleFormats": _intersection(source.sample_formats, target.sample_formats),
        "rates": _intersection(source.rates, target.rates),
        "layouts": _intersection(source.layouts, target.layouts),
    }
    for reason, source_values, target_values, name in (
        ("codec", source.codecs, target.codecs, "codecs"),
        (
            "sample_format",
            source.sample_formats,
            target.sample_formats,
            "sampleFormats",
        ),
        ("rate", source.rates, target.rates, "rates"),
        ("layout", source.layouts, target.layouts, "layouts"),
    ):
        if source_values and target_values and not dimensions[name]:
            reasons.append(reason)
    latency = _latency_intersection(source.latency, target.latency)
    if source.latency is not None and target.latency is not None and latency is None:
        reasons.append("latency")
    if not set(target.required_capabilities).issubset(source.capabilities):
        reasons.append("source_capability")
    if not set(source.required_capabilities).issubset(target.capabilities):
        reasons.append("target_capability")
    content = next(iter(concrete_content)) if concrete_content else AudioContent.ANY
    decisions = FrozenDict(
        {
            "mediaKind": (
                source.media_kind.value if source.media_kind == target.media_kind else None
            ),
            "content": content.value if "content" not in reasons else None,
            **{
                name: [
                    item.to_document() if hasattr(item, "to_document") else item for item in values
                ]
                for name, values in dimensions.items()
            },
            "latencyMs": latency.to_document() if latency is not None else None,
        }
    )
    if reasons:
        return SignalNegotiationResult(False, None, tuple(reasons), decisions)
    capabilities = _intersection(source.capabilities, target.capabilities)
    contract = SignalContract(
        media_kind=source.media_kind,
        content=content,
        codecs=dimensions["codecs"],
        sample_formats=dimensions["sampleFormats"],
        rates=dimensions["rates"],
        layouts=dimensions["layouts"],
        latency=latency,
        capabilities=capabilities,
        required_capabilities=tuple(
            sorted(set(source.required_capabilities).union(target.required_capabilities))
        ),
    )
    return SignalNegotiationResult(True, contract, (), decisions)


def negotiate_port_contracts(
    source: PortContract,
    target: PortContract,
) -> SignalNegotiationResult:
    if not isinstance(source, PortContract) or not isinstance(target, PortContract):
        raise TypeError("source and target must be PortContract values")
    direction_reasons = []
    if source.direction is not PortDirection.OUTPUT:
        direction_reasons.append("source_direction")
    if target.direction is not PortDirection.INPUT:
        direction_reasons.append("target_direction")
    negotiated = negotiate_signal_contracts(source.signal, target.signal)
    reasons = (*direction_reasons, *negotiated.reasons)
    return SignalNegotiationResult(
        compatible=not reasons,
        contract=negotiated.contract if not reasons else None,
        reasons=reasons,
        decisions=negotiated.decisions,
    )


def signal_contract_from_descriptor(
    descriptor: SignalDescriptor,
    *,
    decoded_output: bool = False,
) -> SignalContract:
    if not isinstance(descriptor, SignalDescriptor):
        raise TypeError("descriptor must be a SignalDescriptor")
    if decoded_output:
        if descriptor.decoded_output is None:
            raise ValueError("descriptor has no observed decoded output")
        format_value = descriptor.decoded_output
        content = AudioContent.PCM
        codecs = ()
    else:
        format_value = descriptor.transport.format
        content = {
            SignalContentKind.ENCODED: AudioContent.ENCODED,
            SignalContentKind.PCM: AudioContent.PCM,
            SignalContentKind.UNKNOWN: AudioContent.ANY,
            SignalContentKind.SILENCE: AudioContent.PCM,
        }[descriptor.content.kind]
        codecs = (descriptor.content.codec,) if descriptor.content.codec else ()
    return SignalContract(
        media_kind=MediaKind.AUDIO,
        content=content,
        codecs=codecs,
        sample_formats=(format_value.sample_format,) if format_value.sample_format else (),
        rates=(format_value.rate,) if format_value.rate else (),
        layouts=(format_value.layout,) if format_value.layout else (),
    )


def signal_contract_from_audio_format(
    descriptor: AudioFormatDescriptor,
) -> SignalContract:
    """Build the PCM contract of a processor's normalized working output."""

    if not isinstance(descriptor, AudioFormatDescriptor):
        raise TypeError("descriptor must be an AudioFormatDescriptor")
    return SignalContract(
        media_kind=MediaKind.AUDIO,
        content=AudioContent.PCM,
        sample_formats=(descriptor.sample_format,) if descriptor.sample_format else (),
        rates=(descriptor.rate,) if descriptor.rate else (),
        layouts=(descriptor.layout,) if descriptor.layout else (),
    )


def _specialize_output(
    declared: SignalContract,
    incoming: SignalContract,
) -> SignalContract:
    """Carry unchanged dimensions through a processor's wildcard output fields."""

    same_content = (
        declared.content is AudioContent.ANY
        or incoming.content is AudioContent.ANY
        or declared.content is incoming.content
    )
    return SignalContract(
        media_kind=declared.media_kind,
        content=(incoming.content if declared.content is AudioContent.ANY else declared.content),
        codecs=(declared.codecs or incoming.codecs) if same_content else declared.codecs,
        sample_formats=declared.sample_formats or incoming.sample_formats,
        rates=declared.rates or incoming.rates,
        layouts=declared.layouts or incoming.layouts,
        latency=declared.latency or incoming.latency,
        capabilities=declared.capabilities or incoming.capabilities,
        required_capabilities=declared.required_capabilities,
    )


def propagate_graph_signal_contracts(
    document: Mapping[str, object],
    *,
    registry: NodeTypeRegistry,
    edge_ids: set[str] | frozenset[str] | None = None,
    observed_outputs: Mapping[tuple[str, str], SignalContract] | None = None,
) -> SignalPropagationResult:
    """Propagate narrowed contracts over selected edges without runtime side effects."""

    if not isinstance(document, Mapping):
        raise TypeError("document must be an object")
    if not isinstance(registry, NodeTypeRegistry):
        raise TypeError("registry must be a NodeTypeRegistry")
    selected = set(edge_ids) if edge_ids is not None else None
    nodes = {
        node["id"]: node
        for node in document.get("nodes", ())
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    }
    definitions = {
        node_id: registry.get(node.get("type"), node.get("version"))
        for node_id, node in nodes.items()
    }
    ports = {
        (node_id, port.contract.name): port.contract
        for node_id, definition in definitions.items()
        if definition is not None
        for port in definition.ports
    }
    observed = dict(observed_outputs or {})
    if any(not isinstance(value, SignalContract) for value in observed.values()):
        raise TypeError("observed_outputs values must be SignalContract instances")
    states = {
        key: port.signal for key, port in ports.items() if port.direction is PortDirection.OUTPUT
    }
    states.update(observed)
    edges = tuple(
        sorted(
            (
                edge
                for edge in document.get("edges", ())
                if isinstance(edge, Mapping)
                and isinstance(edge.get("id"), str)
                and (selected is None or edge["id"] in selected)
            ),
            key=lambda edge: edge["id"],
        )
    )
    edge_results: dict[str, SignalNegotiationResult] = {}
    for _ in range(max(1, len(nodes) + len(edges))):
        changed = False
        incoming_by_node: dict[str, list[SignalContract]] = {}
        for edge in edges:
            source = edge.get("from")
            target = edge.get("to")
            if not isinstance(source, Mapping) or not isinstance(target, Mapping):
                continue
            source_key = (source.get("node"), source.get("port"))
            target_key = (target.get("node"), target.get("port"))
            source_port = ports.get(source_key)
            target_port = ports.get(target_key)
            source_signal = states.get(source_key)
            if source_port is None or target_port is None or source_signal is None:
                continue
            result = negotiate_port_contracts(
                PortContract(
                    name=source_port.name,
                    direction=source_port.direction,
                    signal=source_signal,
                    optional=source_port.optional,
                ),
                target_port,
            )
            edge_results[edge["id"]] = result
            if not result.compatible or result.contract is None:
                continue
            previous = states.get(target_key)
            if previous != result.contract:
                states[target_key] = result.contract
                changed = True
            incoming_by_node.setdefault(target_key[0], []).append(result.contract)
        for node_id, incoming_values in sorted(incoming_by_node.items()):
            incoming = incoming_values[0]
            for other in incoming_values[1:]:
                merged = negotiate_signal_contracts(incoming, other)
                if not merged.compatible or merged.contract is None:
                    incoming = None
                    break
                incoming = merged.contract
            if incoming is None:
                continue
            definition = definitions.get(node_id)
            if definition is None:
                continue
            for output in definition.ports:
                if output.contract.direction is not PortDirection.OUTPUT:
                    continue
                key = (node_id, output.contract.name)
                if key in observed:
                    continue
                specialized = _specialize_output(output.contract.signal, incoming)
                if states.get(key) != specialized:
                    states[key] = specialized
                    changed = True
        if not changed:
            break
    edge_documents = {}
    issues = []
    for edge in edges:
        result = edge_results.get(edge["id"])
        if result is None:
            continue
        source = edge["from"]
        target = edge["to"]
        source_port = ports[(source["node"], source["port"])]
        target_port = ports[(target["node"], target["port"])]
        edge_documents[edge["id"]] = {
            "source": source_port.signal.to_document(),
            "target": target_port.signal.to_document(),
            "negotiated": (result.contract.to_document() if result.contract is not None else None),
            "compatible": result.compatible,
            "reasons": list(result.reasons),
            "decisions": result.decisions.to_dict(),
        }
        if not result.compatible:
            issues.append(SignalPropagationIssue(edge["id"], result.reasons))
    port_documents = {
        f"{node_id}.{port_name}": contract.to_document()
        for (node_id, port_name), contract in sorted(states.items())
    }
    return SignalPropagationResult(
        compatible=not issues,
        edge_contracts=FrozenDict(edge_documents),
        port_contracts=FrozenDict(port_documents),
        issues=tuple(issues),
    )
