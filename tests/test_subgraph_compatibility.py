import copy

from core.orchestration.subgraph_compatibility import compare_subgraph_interfaces
from tests.test_subgraph_interface import _subgraph


def _parent():
    return {
        "id": "graph:parent-using-filter",
        "nodes": [
            {
                "id": "node:filter",
                "type": "core.subgraph-instance",
                "version": 1,
                "configuration": {},
                "subgraph": {
                    "definitionId": "definition:filter",
                    "revisionId": "revision:old",
                    "parameterBindings": {"gain": {"value": 0.5}},
                    "portBindings": {"input": "input", "output": "output"},
                },
            }
        ],
    }


def test_identical_interfaces_are_compatible() -> None:
    comparison = compare_subgraph_interfaces(_subgraph(), copy.deepcopy(_subgraph()))

    assert comparison.compatible is True
    assert comparison.changes == ()
    assert comparison.affected_bindings == ()


def test_changed_ports_parameters_and_parent_bindings_are_reported() -> None:
    previous = _subgraph()
    candidate = copy.deepcopy(previous)
    candidate["publicPorts"] = [candidate["publicPorts"][0]]
    candidate["parameters"][0]["maximum"] = 0.9
    candidate["parameters"].append(
        {"name": "mode", "type": "string", "required": True}
    )

    comparison = compare_subgraph_interfaces(
        previous,
        candidate,
        parent_documents=[_parent()],
        definition_id="definition:filter",
        previous_revision_id="revision:old",
    )

    assert comparison.compatible is False
    assert {(change.resource, change.name, change.field) for change in comparison.changes} >= {
        ("port", "output", "removed"),
        ("parameter", "gain", "maximum"),
        ("parameter", "mode", "added"),
    }
    assert {binding.reason for binding in comparison.affected_bindings} == {
        "Binding uses changed public port 'output'.",
        "Binding uses changed parameter 'gain'.",
        "New required parameter 'mode' is unbound.",
    }


def test_added_optional_port_and_defaulted_parameter_are_compatible() -> None:
    previous = _subgraph()
    candidate = copy.deepcopy(previous)
    candidate["publicPorts"].append(
        {
            "name": "monitor",
            "direction": "output",
            "contract": {"mediaKind": "audio"},
            "internalBinding": {"node": "node:adapter", "port": "output"},
        }
    )
    candidate["parameters"].append(
        {
            "name": "enabled",
            "type": "boolean",
            "required": False,
            "default": True,
        }
    )

    comparison = compare_subgraph_interfaces(previous, candidate)

    assert comparison.compatible is True
    assert all(change.compatible for change in comparison.changes)
