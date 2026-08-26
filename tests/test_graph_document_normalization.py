import copy
import json
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from core.orchestration.graph_documents import (
    canonical_graph_json,
    graph_content_digest,
    normalize_graph_document,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "orchestration"
    / "canonical"
    / "desired_graph.json"
)


def _graph():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]


@given(
    node_order=st.permutations(range(4)),
    edge_order=st.permutations(range(3)),
    parameter_order=st.permutations(range(2)),
)
def test_declaration_permutations_have_one_semantic_digest(
    node_order,
    edge_order,
    parameter_order,
) -> None:
    graph = _graph()
    shuffled = copy.deepcopy(graph)
    shuffled["nodes"] = [graph["nodes"][index] for index in node_order]
    shuffled["edges"] = [graph["edges"][index] for index in edge_order]
    shuffled["parameters"] = [
        graph["parameters"][index] for index in parameter_order
    ]

    assert graph_content_digest(shuffled) == graph_content_digest(graph)
    assert normalize_graph_document(shuffled) == normalize_graph_document(graph)


@given(
    x=st.floats(allow_nan=False, allow_infinity=False),
    y=st.floats(allow_nan=False, allow_infinity=False),
    zoom=st.floats(min_value=0.01, max_value=10, allow_nan=False),
)
def test_editor_layout_does_not_change_semantic_digest(x, y, zoom) -> None:
    graph = _graph()
    edited = copy.deepcopy(graph)
    edited["layout"]["viewport"] = {"x": x, "y": y, "zoom": zoom}
    edited["nodes"][0]["layout"] = {"x": y, "y": x, "collapsed": True}

    assert graph_content_digest(edited) == graph_content_digest(graph)
    assert canonical_graph_json(edited) != canonical_graph_json(graph)


def test_ordered_selector_candidates_remain_semantic() -> None:
    graph = _graph()
    reordered = copy.deepcopy(graph)
    candidates = reordered["nodes"][0]["configuration"]["candidates"]
    candidates.reverse()

    assert graph_content_digest(reordered) != graph_content_digest(graph)


def test_normalization_is_detached_and_idempotent() -> None:
    graph = _graph()
    original = copy.deepcopy(graph)

    first = normalize_graph_document(graph)
    second = normalize_graph_document(first)
    first["metadata"]["name"] = "Changed detached copy"

    assert graph == original
    assert second == normalize_graph_document(graph)


def test_commutative_condition_arguments_and_set_contracts_are_normalized() -> None:
    graph = _graph()
    graph["conditions"] = [
        {
            "id": "condition:test",
            "expression": {
                "op": "all",
                "args": [
                    {"op": "eq", "fact": "parameter.a", "value": 1},
                    {"op": "eq", "fact": "parameter.b", "value": 2},
                ],
            },
        }
    ]
    graph["publicPorts"] = [
        {
            "name": "audio",
            "direction": "output",
            "contract": {
                "mediaKind": "audio",
                "rates": [96000, 48000],
                "capabilities": ["volume", "mute"],
            },
        }
    ]
    reordered = copy.deepcopy(graph)
    reordered["conditions"][0]["expression"]["args"].reverse()
    reordered["publicPorts"][0]["contract"]["rates"].reverse()
    reordered["publicPorts"][0]["contract"]["capabilities"].reverse()

    assert graph_content_digest(reordered) == graph_content_digest(graph)
