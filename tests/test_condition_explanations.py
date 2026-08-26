import json

import pytest

from core.orchestration.condition_evaluation import (
    TruthValue,
    condition_expression_key,
    explain_condition_ast,
)
from core.orchestration.condition_validation import (
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_GROUP_ARGUMENTS,
    MAX_CONDITION_MEMBERSHIP_VALUES,
    MAX_CONDITION_NODES,
    validate_condition_document,
)


def _document(expression):
    return {"version": 1, "expression": expression}


def test_explanation_tree_records_values_paths_and_three_valued_reasons() -> None:
    document = _document(
        {
            "op": "all",
            "args": [
                {
                    "op": "eq",
                    "fact": "endpoint.headset.availability",
                    "value": "route-available",
                },
                {"op": "eq", "fact": "processor.decoder.health", "value": "ready"},
            ],
        }
    )

    explanation = explain_condition_ast(
        document,
        {"endpoint.headset.availability": "route-available"},
    )
    encoded = explanation.to_document()

    assert explanation.truth is TruthValue.UNKNOWN
    assert explanation.reason == "all_unknown"
    assert encoded["children"][0] == {
        "path": "$.expression.args[0]",
        "operator": "eq",
        "truth": "true",
        "reason": "eq_true",
        "fact": "endpoint.headset.availability",
        "factPresent": True,
        "actual": "route-available",
        "expected": "route-available",
        "expectedValues": [],
        "durationMs": None,
        "observedDurationMs": None,
        "children": [],
    }
    assert encoded["children"][1]["reason"] == "fact_missing"


def test_explanations_are_deterministic_and_json_serializable() -> None:
    expression = {
        "args": [
            {"value": True, "fact": "mode.cinema", "op": "eq"},
            {"fact": "override.output.active", "op": "exists"},
        ],
        "op": "any",
    }
    first = explain_condition_ast(
        {"expression": expression, "version": 1},
        {"override.output.active": False, "mode.cinema": True},
    ).to_document()
    second = explain_condition_ast(
        {"version": 1, "expression": expression},
        {"mode.cinema": True, "override.output.active": False},
    ).to_document()

    assert first == second
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_stable_duration_explanation_distinguishes_unobserved_pending_and_ready() -> None:
    argument = {"op": "eq", "fact": "mode.cinema", "value": True}
    document = _document(
        {"op": "stable_for", "arg": argument, "durationMs": 250}
    )
    facts = {"mode.cinema": True}
    key = condition_expression_key(argument)

    unobserved = explain_condition_ast(document, facts)
    pending = explain_condition_ast(
        document, facts, stable_durations_ms={key: 249}
    )
    ready = explain_condition_ast(
        document, facts, stable_durations_ms={key: 250}
    )

    assert (unobserved.truth, unobserved.reason) == (
        TruthValue.UNKNOWN,
        "duration_unobserved",
    )
    assert (pending.truth, pending.reason, pending.observed_duration_ms) == (
        TruthValue.FALSE,
        "duration_pending",
        249,
    )
    assert (ready.truth, ready.reason, ready.observed_duration_ms) == (
        TruthValue.TRUE,
        "duration_satisfied",
        250,
    )


def _nested_not(depth: int):
    expression = {"op": "exists", "fact": "mode.cinema"}
    for _ in range(depth - 1):
        expression = {"op": "not", "arg": expression}
    return expression


def test_depth_boundary_accepts_limit_and_rejects_one_more() -> None:
    at_limit = validate_condition_document(_document(_nested_not(MAX_CONDITION_DEPTH)))
    over_limit = validate_condition_document(
        _document(_nested_not(MAX_CONDITION_DEPTH + 1))
    )

    assert at_limit.valid
    assert not over_limit.valid
    assert any(issue.code == "depth_limit_exceeded" for issue in over_limit.issues)


def _node_boundary_expression(extra_leaves: int):
    leaf = {"op": "exists", "fact": "mode.cinema"}
    groups = [
        {"op": "any", "args": [leaf for _ in range(MAX_CONDITION_GROUP_ARGUMENTS)]}
        for _ in range(3)
    ]
    # 1 root + 3 groups + 96 group leaves + the direct leaves.
    direct_count = MAX_CONDITION_NODES - 100 + extra_leaves
    return {"op": "all", "args": [*groups, *[leaf for _ in range(direct_count)]]}


def test_node_boundary_accepts_limit_and_rejects_one_more() -> None:
    at_limit = validate_condition_document(_document(_node_boundary_expression(0)))
    over_limit = validate_condition_document(_document(_node_boundary_expression(1)))

    assert at_limit.node_count == MAX_CONDITION_NODES
    assert at_limit.valid
    assert over_limit.node_count == MAX_CONDITION_NODES + 1
    assert any(issue.code == "node_limit_exceeded" for issue in over_limit.issues)


def test_membership_boundary_accepts_limit_and_rejects_one_more() -> None:
    values = [f"mode-{index}" for index in range(MAX_CONDITION_MEMBERSHIP_VALUES)]
    valid = validate_condition_document(
        _document({"op": "in", "fact": "mode.selected", "values": values})
    )
    invalid = validate_condition_document(
        _document(
            {"op": "in", "fact": "mode.selected", "values": [*values, "extra"]}
        )
    )

    assert valid.valid
    assert any(issue.code == "membership_limit_exceeded" for issue in invalid.issues)


@pytest.mark.parametrize(
    ("document", "path", "code"),
    (
        ({}, "$.expression", "missing_expression"),
        ({"version": 1, "expression": []}, "$.expression", "invalid_expression"),
        (
            _document({"op": "not", "arg": 1}),
            "$.expression.arg",
            "invalid_expression",
        ),
        (
            _document({"op": "stable_for", "arg": {"op": "exists", "fact": "mode.x"}}),
            "$.expression.durationMs",
            "invalid_duration",
        ),
    ),
)
def test_malformed_inputs_have_deterministic_field_diagnostics(document, path, code) -> None:
    result = validate_condition_document(document)

    assert (path, code) in {(issue.path, issue.code) for issue in result.issues}
