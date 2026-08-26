import json
from copy import deepcopy
from pathlib import Path

from core.orchestration.condition_evaluation import evaluate_eligibility
from core.orchestration.path_selection import (
    PathCandidate,
    PathSelectionStatus,
    resolve_exclusive_selection,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "orchestration" / "canonical"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _facts(world: dict) -> dict[str, object]:
    return {
        f"endpoint.{endpoint_id}.{name}": value
        for endpoint_id, endpoint in world["endpoints"].items()
        for name, value in endpoint.items()
    }


def _select(selector: dict, world: dict) -> str:
    candidates = []
    for order, candidate in enumerate(selector["configuration"]["candidates"]):
        eligibility = evaluate_eligibility(
            {"version": 1, "expression": candidate["eligibleWhen"]},
            _facts(world),
            unknown_result=candidate["unknownResult"],
        )
        candidates.append(
            PathCandidate(
                reference_id=candidate["endpoint"],
                priority=candidate["priority"],
                declaration_order=order,
                eligibility=eligibility.status,
                evidence=(f"condition:{eligibility.truth.value}",),
            )
        )
    decision = resolve_exclusive_selection(
        candidates,
        mode=selector["configuration"]["mode"],
        tie_break=selector["configuration"].get("tieBreak", "declaration-order"),
    )
    assert decision.status is PathSelectionStatus.RESOLVED
    return decision.selected[0].reference_id


def _execute_case(graph: dict, case: dict) -> dict[str, str]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    selected_input = _select(nodes["node:programme-selector"], case["world"])
    selected_output = _select(nodes["node:output-selector"], case["world"])
    profile = next(
        item["profile"]
        for item in nodes["node:output-processing"]["configuration"]["profiles"]
        if item["output"] == selected_output
    )
    return {
        "selectedInput": selected_input,
        "selectedOutput": selected_output,
        "camillaProfile": profile,
    }


def test_canonical_world_sequence_executes_graph_conditions_and_priorities() -> None:
    graph = _load("desired_graph.json")["graph"]
    original_graph = deepcopy(graph)

    actual = {}
    for case in _load("cases.json")["cases"]:
        actual[case["id"]] = _execute_case(graph, case)
        expected = case["expectedPlan"]
        assert actual[case["id"]] == {
            "selectedInput": expected["selectedInput"],
            "selectedOutput": expected["selectedOutput"],
            "camillaProfile": expected["camillaProfile"],
        }

    assert actual["case:tv-pcm-main-speakers"]["selectedOutput"] == ("endpoint:main-speakers")
    assert actual["case:bluetooth-main-speakers"]["selectedInput"] == (
        "endpoint:bluetooth-programme"
    )
    assert actual["case:headset-overrides-output"]["selectedOutput"] == ("endpoint:headset")
    assert actual["case:headset-removed-restores-speakers"]["selectedOutput"] == (
        "endpoint:main-speakers"
    )
    assert graph == original_graph


def test_headset_return_path_is_derived_without_reapplying_desired_graph() -> None:
    graph = _load("desired_graph.json")["graph"]
    cases = {case["id"]: case for case in _load("cases.json")["cases"]}
    graph_identity = id(graph)

    connected = _execute_case(graph, cases["case:headset-overrides-output"])
    disconnected = _execute_case(
        graph,
        cases["case:headset-removed-restores-speakers"],
    )

    assert connected["selectedOutput"] == "endpoint:headset"
    assert disconnected["selectedOutput"] == "endpoint:main-speakers"
    assert connected["selectedInput"] == disconnected["selectedInput"]
    assert graph_identity == id(graph)
