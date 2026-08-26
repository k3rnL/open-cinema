import json
from pathlib import Path

from core.orchestration.graph_schema import (
    DESIRED_GRAPH_SCHEMA_VERSION,
    desired_graph_envelope_validator,
    desired_graph_schema,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "orchestration"
    / "canonical"
    / "desired_graph.json"
)


def _errors(document):
    return list(desired_graph_envelope_validator().iter_errors(document))


def test_canonical_acceptance_graph_conforms_to_v1_schema() -> None:
    graph = json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]

    assert DESIRED_GRAPH_SCHEMA_VERSION == 1
    assert desired_graph_schema()["$schema"].endswith("2020-12/schema")
    assert _errors(graph) == []


def test_schema_rejects_future_version_and_incomplete_envelope() -> None:
    future = {
        "schemaVersion": 2,
        "id": "graph:future",
        "kind": "graph",
    }

    messages = {error.validator for error in _errors(future)}
    assert "const" in messages
    assert "required" in messages


def test_schema_covers_subgraph_ports_parameters_conditions_and_layout() -> None:
    subgraph = {
        "schemaVersion": 1,
        "id": "graph:room-processing",
        "kind": "subgraph",
        "metadata": {"name": "Room processing"},
        "parameters": [
            {
                "name": "gain",
                "type": "number",
                "required": False,
                "default": 0.8,
                "minimum": 0.0,
                "maximum": 1.0,
            }
        ],
        "publicPorts": [
            {
                "name": "output",
                "direction": "output",
                "contract": {"mediaKind": "audio", "content": "pcm"},
                "internalBinding": {"node": "node:processor", "port": "output"},
            }
        ],
        "conditions": [
            {
                "id": "condition:enabled",
                "expression": {
                    "op": "eq",
                    "fact": "parameter.enabled",
                    "value": True,
                },
            }
        ],
        "nodes": [
            {
                "id": "node:processor",
                "type": "plugin.example.processor",
                "version": 3,
                "configuration": {"unknownPluginField": {"preserved": True}},
                "parameterBindings": {"gain": {"parameter": "gain"}},
                "condition": {
                    "reference": "condition:enabled",
                    "unknownResult": "waiting",
                },
                "layout": {"x": 10, "y": 20, "collapsed": False},
            },
            {
                "id": "node:nested",
                "type": "core.subgraph-instance",
                "version": 1,
                "configuration": {},
                "subgraph": {
                    "definitionId": "graph:shared-filter",
                    "revisionId": "revision:shared-filter:4",
                    "parameterBindings": {"gain": {"value": 0.5}},
                    "portBindings": {"output": "output"},
                },
            },
        ],
        "edges": [
            {
                "id": "edge:processor-to-nested",
                "from": {"node": "node:processor", "port": "output"},
                "to": {"node": "node:nested", "port": "input"},
                "policy": {"order": 10},
                "layout": {"label": "PCM"},
            }
        ],
        "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1.0}},
    }

    assert _errors(subgraph) == []


def test_runtime_fields_are_not_part_of_the_desired_node_envelope() -> None:
    graph = json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]
    graph["nodes"][0]["runtimeId"] = 42

    errors = _errors(graph)
    assert any(error.validator == "additionalProperties" for error in errors)
