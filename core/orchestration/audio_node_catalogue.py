from __future__ import annotations

from .adaptive_decoder import adaptive_decoder_node_type_definition
from .node_catalogue import (
    NodePortDefinition,
    NodeTypeDefinition,
    NodeTypeRegistry,
    core_node_type_definitions,
)
from .signal_contracts import (
    AudioContent,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)


def camilladsp_node_type_definition() -> NodeTypeDefinition:
    """Describe the stable graph contract for one managed CamillaDSP profile."""

    pcm = SignalContract(media_kind=MediaKind.AUDIO, content=AudioContent.PCM)
    return NodeTypeDefinition(
        type_id="processor.camilladsp-profile-selector",
        version=1,
        display_name="CamillaDSP profile",
        category="processing",
        description=(
            "Applies one immutable CamillaDSP profile after endpoint and signal "
            "resolution has selected concrete device-independent parameters."
        ),
        ports=(
            NodePortDefinition(
                PortContract("input", PortDirection.INPUT, pcm),
                description="PCM signal entering the selected profile.",
            ),
            NodePortDefinition(
                PortContract("output", PortDirection.OUTPUT, pcm),
                description="PCM signal produced by the selected profile.",
            ),
        ),
        configuration_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "oneOf": [
                {"required": ["profileId", "profileVersion"]},
                {"required": ["profiles"]},
            ],
            "properties": {
                "profileId": {"type": "string", "format": "uuid"},
                "profileVersion": {"type": "integer", "minimum": 1},
                "parameterBindings": {"type": "object"},
                "profiles": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "required": ["output", "profile"],
                        "additionalProperties": False,
                        "properties": {
                            "output": {"type": "string", "minLength": 1},
                            "profile": {"type": "string", "minLength": 1},
                            "profileVersion": {"type": "integer", "minimum": 1},
                            "parameterBindings": {"type": "object"},
                            "volume": {},
                            "eligibleWhen": {"type": "object"},
                            "priority": {"type": "integer"},
                        },
                    },
                },
                "bypassAllowed": {"type": "boolean"},
                "resourcePriority": {"type": "integer"},
                "channelAdaptation": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "required": ["mixer"],
                    "properties": {
                        "mixer": {"type": "string", "minLength": 1},
                        "reason": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    )


def audio_node_type_registry(*, plugin_registry=None) -> NodeTypeRegistry:
    """Build an isolated catalogue containing core, managed, and plugin nodes."""

    registry = NodeTypeRegistry()
    for definition in core_node_type_definitions():
        registry.register(definition)
    registry.register(adaptive_decoder_node_type_definition())
    registry.register(camilladsp_node_type_definition())
    if plugin_registry is not None:
        plugin_registry.register_node_types(registry)
    return registry
