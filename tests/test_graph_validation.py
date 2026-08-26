import copy
import json
from pathlib import Path

from django.test import override_settings

from core.orchestration.adaptive_decoder import adaptive_decoder_node_type_definition
from core.orchestration.graph_validation import (
    GraphValidationLimits,
    validate_graph_structure,
)
from core.orchestration.node_catalogue import (
    NodePortDefinition,
    NodeTypeDefinition,
    NodeTypeRegistry,
    core_node_type_definitions,
)
from core.orchestration.signal_contracts import (
    AudioContent,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)

FIXTURE = Path(__file__).parent / "fixtures" / "orchestration" / "canonical" / "desired_graph.json"


def _graph():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]


def _port(name, direction, content):
    return NodePortDefinition(
        PortContract(
            name=name,
            direction=direction,
            signal=SignalContract(media_kind=MediaKind.AUDIO, content=content),
        )
    )


def _processor(type_id, *, input_content, output_content):
    return NodeTypeDefinition(
        type_id=type_id,
        version=1,
        display_name=type_id,
        category="test processor",
        description="Acceptance-fixture processor contract.",
        ports=(
            _port("input", PortDirection.INPUT, input_content),
            _port("output", PortDirection.OUTPUT, output_content),
        ),
        configuration_schema={"type": "object"},
    )


def _registry():
    registry = NodeTypeRegistry()
    for definition in core_node_type_definitions():
        registry.register(definition)
    registry.register(adaptive_decoder_node_type_definition())
    registry.register(
        _processor(
            "processor.camilladsp-profile-selector",
            input_content=AudioContent.PCM,
            output_content=AudioContent.PCM,
        )
    )
    return registry


def _codes(result):
    return [issue.code for issue in result.issues]


def test_canonical_graph_is_structurally_valid_without_runtime_inventory() -> None:
    result = validate_graph_structure(_graph(), registry=_registry())

    assert result.valid is True
    assert result.issues == ()
    assert result.node_count == 4
    assert result.edge_count == 3
    assert result.path_depth == 4


def test_managed_processor_catalogue_validates_canonical_graph_by_default() -> None:
    result = validate_graph_structure(_graph())

    assert result.valid is True
    assert result.issues == ()


def test_node_types_ids_configuration_and_ports_are_checked() -> None:
    graph = _graph()
    graph["nodes"][0]["id"] = graph["nodes"][1]["id"]
    graph["nodes"][1]["type"] = "plugin.missing"
    graph["nodes"][2]["configuration"] = {"mode": "exclusive", "candidates": []}
    graph["edges"][0]["from"]["port"] = "missing"

    result = validate_graph_structure(graph, registry=_registry())

    assert {
        "duplicate_id",
        "node_type_unavailable",
        "configuration_schema_minItems",
        "unknown_source_port",
    } <= set(_codes(result))


def test_edge_direction_compatibility_duplicates_and_cardinality_are_checked() -> None:
    graph = _graph()
    graph["edges"].append(
        {
            **copy.deepcopy(graph["edges"][0]),
            "id": "edge:duplicate-shape",
        }
    )
    graph["edges"][1] = {
        "id": "edge:wrong-direction",
        "from": {"node": "node:adaptive-decoder", "port": "input"},
        "to": {"node": "node:output-processing", "port": "output"},
    }
    graph["nodes"][1]["type"] = "processor.camilladsp-profile-selector"
    graph["nodes"][1]["configuration"] = {}
    encoded_source = _processor(
        "test.encoded-source",
        input_content=AudioContent.ANY,
        output_content=AudioContent.ENCODED,
    )
    registry = _registry()
    registry.register(encoded_source)
    graph["nodes"][0]["type"] = "test.encoded-source"
    graph["nodes"][0]["configuration"] = {}
    graph["edges"][0]["from"]["port"] = "output"
    graph["edges"][3]["from"]["port"] = "output"

    result = validate_graph_structure(graph, registry=registry)

    assert {
        "duplicate_edge",
        "source_port_direction",
        "target_port_direction",
        "incompatible_ports",
        "port_cardinality_exceeded",
    } <= set(_codes(result))


def test_required_connectivity_and_unsupported_feedback_are_reported() -> None:
    graph = _graph()
    graph["nodes"].append(
        {
            "id": "node:unconnected-adapter",
            "type": "core.explicit-adapter",
            "version": 1,
            "configuration": {"targetContract": {"mediaKind": "audio"}},
        }
    )
    graph["edges"] = [
        {
            "id": "edge:decoder-processing",
            "from": {"node": "node:adaptive-decoder", "port": "output"},
            "to": {"node": "node:output-processing", "port": "input"},
        },
        {
            "id": "edge:processing-decoder",
            "from": {"node": "node:output-processing", "port": "output"},
            "to": {"node": "node:adaptive-decoder", "port": "input"},
        },
    ]

    result = validate_graph_structure(graph, registry=_registry())

    assert "required_port_unconnected" in _codes(result)
    cycle_issues = [issue for issue in result.issues if issue.code == "unsupported_feedback_cycle"]
    assert len(cycle_issues) == 2
    assert {issue.path for issue in cycle_issues} == {"$.edges[0]", "$.edges[1]"}
    assert result.path_depth is None


def test_graph_limits_are_configurable_and_report_all_crossed_bounds() -> None:
    limits = GraphValidationLimits(
        max_nodes=2,
        max_edges=2,
        max_path_depth=2,
        max_document_bytes=100,
    )

    result = validate_graph_structure(_graph(), registry=_registry(), limits=limits)

    assert {
        "node_limit_exceeded",
        "edge_limit_exceeded",
        "path_depth_exceeded",
        "document_size_exceeded",
    } <= set(_codes(result))


@override_settings(
    AUDIO_GRAPH_VALIDATION_LIMITS={
        "max_nodes": 0,
        "max_edges": 1,
        "max_path_depth": 1,
        "max_document_bytes": 1,
    }
)
def test_invalid_deployment_limit_is_rejected() -> None:
    try:
        validate_graph_structure(_graph(), registry=_registry())
    except ValueError as error:
        assert "max_nodes" in str(error)
    else:
        raise AssertionError("invalid graph limit was accepted")


def test_endpoint_runtime_availability_is_not_a_structural_input() -> None:
    graph = _graph()
    graph["nodes"][0] = {
        "id": "node:unavailable-headset",
        "type": "core.endpoint-reference",
        "version": 1,
        "configuration": {
            "logicalEndpointId": "endpoint:not-currently-connected",
            "direction": "output",
        },
    }
    graph["nodes"] = [graph["nodes"][0]]
    graph["edges"] = []

    result = validate_graph_structure(graph, registry=_registry())

    assert result.valid is True
    assert result.issues == ()


def test_conditions_are_semantically_validated_with_field_paths() -> None:
    graph = _graph()
    graph["nodes"][0]["configuration"]["candidates"][0]["eligibleWhen"] = {
        "op": "gt",
        "fact": "endpoint.endpoint:headset.availability",
        "value": "loud",
    }

    result = validate_graph_structure(graph, registry=_registry())

    issues = [issue for issue in result.issues if issue.code.startswith("condition_")]
    assert {issue.code for issue in issues} == {
        "condition_numeric_fact_required",
        "condition_numeric_value_required",
    }
    assert all(
        issue.path.startswith("$.nodes[0].configuration.candidates[0].eligibleWhen")
        for issue in issues
    )
