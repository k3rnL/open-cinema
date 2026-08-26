import copy

from core.orchestration.subgraphs import validate_subgraph_interface


def _subgraph():
    return {
        "schemaVersion": 1,
        "id": "graph:room-filter",
        "kind": "subgraph",
        "metadata": {"name": "Room filter"},
        "parameters": [
            {
                "name": "gain",
                "type": "number",
                "required": False,
                "default": 0.8,
                "minimum": 0,
                "maximum": 1,
            }
        ],
        "publicPorts": [
            {
                "name": "input",
                "direction": "input",
                "contract": {"mediaKind": "audio", "content": "any"},
                "internalBinding": {"node": "node:adapter", "port": "input"},
            },
            {
                "name": "output",
                "direction": "output",
                "contract": {"mediaKind": "audio", "content": "any"},
                "internalBinding": {"node": "node:adapter", "port": "output"},
            },
        ],
        "conditions": [],
        "nodes": [
            {
                "id": "node:adapter",
                "type": "core.explicit-adapter",
                "version": 1,
                "configuration": {"targetContract": {"mediaKind": "audio"}},
            }
        ],
        "edges": [],
        "layout": {},
    }


def _codes(result):
    return {issue.code for issue in result.issues}


def test_subgraph_public_interface_maps_to_typed_internal_ports() -> None:
    result = validate_subgraph_interface(_subgraph())

    assert result.valid is True
    assert [port.name for port in result.interface.ports] == ["input", "output"]
    assert result.interface.ports[0].internal_node == "node:adapter"
    assert [parameter.name for parameter in result.interface.parameters] == ["gain"]


def test_subgraph_requires_an_internal_mapping_for_every_public_port() -> None:
    document = _subgraph()
    del document["publicPorts"][0]["internalBinding"]

    result = validate_subgraph_interface(document)

    assert "missing_internal_binding" in _codes(result)
    assert result.interface is None


def test_subgraph_rejects_wrong_direction_and_incompatible_signal_contract() -> None:
    document = _subgraph()
    document["publicPorts"][0]["direction"] = "output"
    document["publicPorts"][1]["contract"] = {
        "mediaKind": "control",
        "content": "any",
    }

    result = validate_subgraph_interface(document)

    assert "public_port_direction" in _codes(result)
    assert "incompatible_public_contract" in _codes(result)


def test_subgraph_parameter_interface_uses_semantic_constraints() -> None:
    document = copy.deepcopy(_subgraph())
    document["parameters"][0]["minimum"] = 2
    document["parameters"][0]["maximum"] = 1

    result = validate_subgraph_interface(document)

    assert "parameter_invalid_definition" in _codes(result)


def test_top_level_graph_cannot_be_published_as_a_subgraph_interface() -> None:
    document = _subgraph()
    document["kind"] = "graph"

    result = validate_subgraph_interface(document)

    assert "not_a_subgraph" in _codes(result)
