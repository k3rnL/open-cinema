import pytest

from core.orchestration.node_catalogue import (
    NodeTypeDefinition,
    NodeTypeRegistry,
    core_node_type_registry,
)

EXPECTED_CORE_TYPES = {
    "core.endpoint-reference",
    "core.ordered-selector",
    "core.fallback-selector",
    "core.exclusive-choice",
    "core.fan-out",
    "core.mixer-intent",
    "core.conditional-bypass",
    "core.subgraph-instance",
    "core.explicit-adapter",
}


def test_all_required_builtin_node_types_are_registered() -> None:
    registry = core_node_type_registry()

    assert {definition.type_id for definition in registry.definitions()} == EXPECTED_CORE_TYPES
    assert all(definition.version == 1 for definition in registry.definitions())
    assert registry.latest("core.fan-out").type_id == "core.fan-out"


def test_catalogue_exposes_typed_ports_and_display_metadata() -> None:
    catalogue = core_node_type_registry().to_document()

    assert all(item["displayName"] and item["description"] for item in catalogue)
    ports = [port for item in catalogue for port in item["ports"]]
    assert ports
    assert {port["direction"] for port in ports} == {"input", "output"}
    assert all(port["contract"]["mediaKind"] == "audio" for port in ports)
    subgraph = next(item for item in catalogue if item["id"] == "core.subgraph-instance")
    assert subgraph["requiresSubgraphReference"] is True
    assert subgraph["allowsDynamicPorts"] is True


def test_endpoint_selector_ports_match_the_live_routing_contract() -> None:
    catalogue = core_node_type_registry().to_document()

    for type_id in {
        "core.ordered-selector",
        "core.fallback-selector",
        "core.exclusive-choice",
    }:
        definition = next(item for item in catalogue if item["id"] == type_id)
        assert [port["name"] for port in definition["ports"]] == ["input", "audio"]


def test_builtin_configuration_schemas_accept_canonical_examples() -> None:
    registry = core_node_type_registry()
    examples = {
        "core.endpoint-reference": {
            "logicalEndpointId": "endpoint:main-speakers",
            "direction": "output",
        },
        "core.ordered-selector": {
            "mode": "exclusive",
            "candidates": [
                {
                    "endpointSelector": {
                        "version": 1,
                        "direction": "output",
                        "requiredTags": ["preferred-output"],
                        "orderedGroups": ["headsets", "room-speakers"],
                    },
                    "priority": 200,
                },
                {"endpoint": "endpoint:speakers", "priority": 100},
            ],
        },
        "core.fallback-selector": {
            "mode": "fallback",
            "candidates": [{"endpoint": "endpoint:speakers", "priority": 1}],
        },
        "core.exclusive-choice": {
            "mode": "exclusive",
            "candidates": [{"endpoint": "endpoint:tv", "priority": 1}],
        },
        "core.fan-out": {"failureMode": "best-effort"},
        "core.mixer-intent": {"headroomDb": -3, "normalization": "peak"},
        "core.conditional-bypass": {
            "condition": {"op": "exists", "fact": "signal.input.codec"},
            "unknownResult": "bypass",
        },
        "core.subgraph-instance": {},
        "core.explicit-adapter": {
            "targetContract": {"mediaKind": "audio", "content": "pcm"},
            "strategy": "resample",
        },
    }

    for type_id, configuration in examples.items():
        assert registry.require(type_id, 1).validate_configuration(configuration) == ()


def test_configuration_errors_have_stable_paths_and_codes() -> None:
    definition = core_node_type_registry().require("core.ordered-selector", 1)

    issues = definition.validate_configuration(
        {"mode": "exclusive", "candidates": [{"endpoint": "headset"}]}
    )

    assert issues[0].path == "$['candidates'][0]"
    assert issues[0].code == "schema_required"


def test_selector_candidate_rejects_conflicting_endpoint_reference_forms() -> None:
    definition = core_node_type_registry().require("core.ordered-selector", 1)

    issues = definition.validate_configuration(
        {
            "mode": "exclusive",
            "candidates": [
                {
                    "endpoint": "endpoint:headset",
                    "endpointSelector": {
                        "version": 1,
                        "orderedGroups": ["headsets"],
                    },
                    "priority": 100,
                }
            ],
        }
    )

    assert any(issue.code == "schema_oneOf" for issue in issues)


def test_registry_rejects_duplicate_type_versions() -> None:
    definition = core_node_type_registry().require("core.fan-out", 1)
    registry = NodeTypeRegistry()
    registry.register(definition)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(definition)


def test_node_type_metadata_and_schema_are_validated_at_registration_time() -> None:
    with pytest.raises(ValueError, match="namespace"):
        NodeTypeDefinition(
            type_id="invalid",
            version=1,
            display_name="Invalid",
            category="test",
            description="Missing a namespace.",
            ports=(),
            configuration_schema={"type": "object"},
        )
