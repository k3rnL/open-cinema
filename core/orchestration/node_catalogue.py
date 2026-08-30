from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

from jsonschema import Draft202012Validator

from .signal_contracts import (
    AudioContent,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)


class PortCardinality(StrEnum):
    SINGLE = "single"
    VARIADIC = "variadic"
    DYNAMIC = "dynamic"


@dataclass(frozen=True, slots=True)
class NodePortDefinition:
    contract: PortContract
    cardinality: PortCardinality = PortCardinality.SINGLE
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cardinality", PortCardinality(self.cardinality))

    def to_document(self) -> dict[str, object]:
        return {
            "name": self.contract.name,
            "direction": self.contract.direction.value,
            "optional": self.contract.optional,
            "cardinality": self.cardinality.value,
            "description": self.description,
            "contract": self.contract.signal.to_document(),
        }


@dataclass(frozen=True, slots=True)
class NodeConfigurationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class NodeTypeDefinition:
    type_id: str
    version: int
    display_name: str
    category: str
    description: str
    ports: tuple[NodePortDefinition, ...]
    configuration_schema: Mapping[str, object]
    requires_subgraph_reference: bool = False
    allows_dynamic_ports: bool = False
    allows_feedback: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.type_id, str)
            or "." not in self.type_id
            or self.type_id.startswith(".")
            or self.type_id.endswith(".")
            or len(self.type_id) > 255
        ):
            raise ValueError("node type IDs must use a non-empty namespace")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("node type version must be a positive integer")
        if not self.display_name or not self.category or not self.description:
            raise ValueError("node type display metadata is required")
        names = [port.contract.name for port in self.ports]
        if len(names) != len(set(names)):
            raise ValueError("node type port names must be unique")
        schema = dict(self.configuration_schema)
        Draft202012Validator.check_schema(schema)
        object.__setattr__(self, "configuration_schema", MappingProxyType(schema))

    def validate_configuration(
        self,
        configuration: object,
    ) -> tuple[NodeConfigurationIssue, ...]:
        errors = sorted(
            Draft202012Validator(dict(self.configuration_schema)).iter_errors(configuration),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        return tuple(
            NodeConfigurationIssue(
                path="$" + "".join(f"[{item!r}]" for item in error.absolute_path),
                code=f"schema_{error.validator}",
                message=error.message,
            )
            for error in errors
        )

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.type_id,
            "version": self.version,
            "displayName": self.display_name,
            "category": self.category,
            "description": self.description,
            "ports": [port.to_document() for port in self.ports],
            "configurationSchema": dict(self.configuration_schema),
            "requiresSubgraphReference": self.requires_subgraph_reference,
            "allowsDynamicPorts": self.allows_dynamic_ports,
            "allowsFeedback": self.allows_feedback,
        }


class NodeTypeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], NodeTypeDefinition] = {}

    def register(self, definition: NodeTypeDefinition) -> None:
        key = (definition.type_id, definition.version)
        if key in self._definitions:
            raise ValueError(
                f"node type {definition.type_id} v{definition.version} is already registered"
            )
        self._definitions[key] = definition

    def get(self, type_id: str, version: int) -> NodeTypeDefinition | None:
        return self._definitions.get((type_id, version))

    def require(self, type_id: str, version: int) -> NodeTypeDefinition:
        definition = self.get(type_id, version)
        if definition is None:
            raise KeyError(f"node type {type_id} v{version} is unavailable")
        return definition

    def latest(self, type_id: str) -> NodeTypeDefinition | None:
        candidates = [
            definition
            for (candidate_id, _), definition in self._definitions.items()
            if candidate_id == type_id
        ]
        return max(candidates, key=lambda item: item.version, default=None)

    def definitions(self) -> tuple[NodeTypeDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )

    def to_document(self) -> list[dict[str, object]]:
        return [definition.to_document() for definition in self.definitions()]


_AUDIO_ANY = SignalContract(media_kind=MediaKind.AUDIO, content=AudioContent.ANY)
_AUDIO_PCM = SignalContract(media_kind=MediaKind.AUDIO, content=AudioContent.PCM)


def _port(
    name: str,
    direction: PortDirection,
    *,
    signal: SignalContract = _AUDIO_ANY,
    optional: bool = False,
    cardinality: PortCardinality = PortCardinality.SINGLE,
    description: str,
) -> NodePortDefinition:
    return NodePortDefinition(
        contract=PortContract(
            name=name,
            direction=direction,
            signal=signal,
            optional=optional,
        ),
        cardinality=cardinality,
        description=description,
    )


_CONDITION = {
    "type": "object",
    "required": ["op"],
    "properties": {"op": {"type": "string", "minLength": 1}},
    "additionalProperties": True,
}


def _logical_endpoint_selector_schema() -> dict[str, object]:
    selector_values = {
        "type": "array",
        "minItems": 1,
        "maxItems": 32,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 128},
    }
    return {
        "type": "object",
        "required": ["version"],
        "anyOf": [
            {"required": ["requiredTags"]},
            {"required": ["orderedGroups"]},
        ],
        "additionalProperties": False,
        "properties": {
            "version": {"const": 1},
            "direction": {"enum": ["input", "output"]},
            "requiredTags": selector_values,
            "orderedGroups": selector_values,
        },
    }


def _selector_schema(*, modes: tuple[str, ...]) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["mode", "candidates"],
        "additionalProperties": False,
        "properties": {
            "mode": {"enum": list(modes)},
            "tieBreak": {"enum": ["declaration-order", "reference-id", "conflict"]},
            "candidates": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["priority"],
                    "oneOf": [
                        {"required": ["endpoint"]},
                        {"required": ["endpointSelector"]},
                    ],
                    "additionalProperties": False,
                    "dependentRequired": {"eligibleWhen": ["unknownResult"]},
                    "properties": {
                        "endpoint": {"type": "string", "minLength": 1},
                        "endpointSelector": _logical_endpoint_selector_schema(),
                        "priority": {"type": "integer"},
                        "eligibleWhen": _CONDITION,
                        "unknownResult": {"enum": ["eligible", "ineligible", "waiting", "error"]},
                    },
                },
            },
        },
    }


def _definition(
    type_id: str,
    display_name: str,
    category: str,
    description: str,
    ports: tuple[NodePortDefinition, ...],
    configuration_schema: Mapping[str, object],
    **kwargs,
) -> NodeTypeDefinition:
    return NodeTypeDefinition(
        type_id=type_id,
        version=1,
        display_name=display_name,
        category=category,
        description=description,
        ports=ports,
        configuration_schema=configuration_schema,
        **kwargs,
    )


def core_node_type_definitions() -> tuple[NodeTypeDefinition, ...]:
    selector_ports = (
        _port(
            "input",
            PortDirection.INPUT,
            optional=True,
            description="Programme audio sent to the selected output endpoint.",
        ),
        _port(
            "audio",
            PortDirection.OUTPUT,
            optional=True,
            description="Audio received from the selected input endpoint.",
        ),
    )
    return (
        _definition(
            "core.endpoint-reference",
            "Endpoint reference",
            "routing",
            "References a durable logical endpoint or a safe endpoint selector.",
            (
                _port(
                    "input",
                    PortDirection.INPUT,
                    optional=True,
                    description="Audio delivered to an output endpoint.",
                ),
                _port(
                    "output",
                    PortDirection.OUTPUT,
                    optional=True,
                    description="Audio produced by an input endpoint.",
                ),
            ),
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "oneOf": [
                    {"required": ["logicalEndpointId"]},
                    {"required": ["selector"]},
                    {"required": ["endpointSelector"]},
                ],
                "properties": {
                    "logicalEndpointId": {"type": "string", "minLength": 1},
                    "selector": {"type": "object"},
                    "endpointSelector": _logical_endpoint_selector_schema(),
                    "direction": {"enum": ["input", "output"]},
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        ),
        _definition(
            "core.ordered-selector",
            "Ordered selector",
            "routing",
            "Chooses the highest-priority eligible endpoint in declared order.",
            selector_ports,
            _selector_schema(modes=("exclusive", "first-available")),
        ),
        _definition(
            "core.fallback-selector",
            "Fallback selector",
            "routing",
            "Keeps a preferred route and applies ordered fallbacks when unavailable.",
            selector_ports,
            _selector_schema(modes=("fallback",)),
        ),
        _definition(
            "core.exclusive-choice",
            "Exclusive choice",
            "routing",
            "Selects exactly one eligible input and reports ties as conflicts.",
            selector_ports,
            _selector_schema(modes=("exclusive",)),
        ),
        _definition(
            "core.fan-out",
            "Fan-out",
            "routing",
            "Replicates one signal to multiple planned outputs.",
            (
                _port("input", PortDirection.INPUT, description="Signal to replicate."),
                _port(
                    "outputs",
                    PortDirection.OUTPUT,
                    cardinality=PortCardinality.VARIADIC,
                    description="Replicated output branches.",
                ),
            ),
            {
                "type": "object",
                "properties": {"failureMode": {"enum": ["all-required", "best-effort"]}},
                "additionalProperties": False,
            },
        ),
        _definition(
            "core.mixer-intent",
            "Mixer intent",
            "processing",
            "Declares that multiple inputs must be mixed into one PCM signal.",
            (
                _port(
                    "inputs",
                    PortDirection.INPUT,
                    signal=_AUDIO_PCM,
                    cardinality=PortCardinality.VARIADIC,
                    description="PCM inputs to mix.",
                ),
                _port(
                    "output",
                    PortDirection.OUTPUT,
                    signal=_AUDIO_PCM,
                    description="Mixed PCM output.",
                ),
            ),
            {
                "type": "object",
                "properties": {
                    "headroomDb": {"type": "number", "maximum": 0},
                    "normalization": {"enum": ["none", "peak", "loudness"]},
                },
                "additionalProperties": False,
            },
        ),
        _definition(
            "core.conditional-bypass",
            "Conditional bypass",
            "control",
            "Selects a processed path or an explicit bypass from a safe condition.",
            (
                _port("input", PortDirection.INPUT, description="Original signal."),
                _port(
                    "processed",
                    PortDirection.INPUT,
                    description="Processed alternative.",
                ),
                _port("output", PortDirection.OUTPUT, description="Selected path."),
            ),
            {
                "type": "object",
                "required": ["condition", "unknownResult"],
                "properties": {
                    "condition": _CONDITION,
                    "unknownResult": {"enum": ["bypass", "processed", "waiting", "error"]},
                },
                "additionalProperties": False,
            },
        ),
        _definition(
            "core.subgraph-instance",
            "Subgraph instance",
            "structure",
            "Pins one immutable reusable subgraph revision and exposes its public ports.",
            (),
            {"type": "object", "additionalProperties": False},
            requires_subgraph_reference=True,
            allows_dynamic_ports=True,
        ),
        _definition(
            "core.explicit-adapter",
            "Explicit signal adapter",
            "processing",
            "Declares an intentional format, rate, channel-layout, or codec conversion.",
            (
                _port("input", PortDirection.INPUT, description="Signal to convert."),
                _port("output", PortDirection.OUTPUT, description="Converted signal."),
            ),
            {
                "type": "object",
                "required": ["targetContract"],
                "properties": {
                    "targetContract": {
                        "type": "object",
                        "required": ["mediaKind"],
                    },
                    "strategy": {"enum": ["automatic", "resample", "remap", "decode", "encode"]},
                },
                "additionalProperties": False,
            },
        ),
    )


@lru_cache(maxsize=1)
def core_node_type_registry() -> NodeTypeRegistry:
    registry = NodeTypeRegistry()
    for definition in core_node_type_definitions():
        registry.register(definition)
    return registry
