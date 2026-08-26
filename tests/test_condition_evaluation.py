import itertools

import pytest

from core.orchestration.condition_evaluation import (
    EligibilityStatus,
    TruthValue,
    UnknownResult,
    condition_expression_key,
    evaluate_condition_ast,
    evaluate_eligibility,
)


def _document(expression):
    return {"version": 1, "expression": expression}


@pytest.mark.parametrize("left,right", itertools.product(TruthValue, repeat=2))
def test_three_valued_all_and_any_truth_tables(left, right) -> None:
    expressions = {
        TruthValue.TRUE: {"op": "eq", "fact": "value.true", "value": True},
        TruthValue.FALSE: {"op": "eq", "fact": "value.false", "value": True},
        TruthValue.UNKNOWN: {"op": "eq", "fact": "value.missing", "value": True},
    }
    facts = {"value.true": True, "value.false": False}

    all_value = evaluate_condition_ast(
        _document({"op": "all", "args": [expressions[left], expressions[right]]}),
        facts,
    )
    any_value = evaluate_condition_ast(
        _document({"op": "any", "args": [expressions[left], expressions[right]]}),
        facts,
    )

    expected_all = (
        TruthValue.FALSE
        if TruthValue.FALSE in {left, right}
        else TruthValue.UNKNOWN
        if TruthValue.UNKNOWN in {left, right}
        else TruthValue.TRUE
    )
    expected_any = (
        TruthValue.TRUE
        if TruthValue.TRUE in {left, right}
        else TruthValue.UNKNOWN
        if TruthValue.UNKNOWN in {left, right}
        else TruthValue.FALSE
    )
    assert all_value is expected_all
    assert any_value is expected_any


@pytest.mark.parametrize(
    ("truth", "expected"),
    (
        (TruthValue.TRUE, TruthValue.FALSE),
        (TruthValue.FALSE, TruthValue.TRUE),
        (TruthValue.UNKNOWN, TruthValue.UNKNOWN),
    ),
)
def test_not_uses_three_valued_negation(truth, expected) -> None:
    expression = {
        TruthValue.TRUE: {"op": "eq", "fact": "known", "value": 1},
        TruthValue.FALSE: {"op": "eq", "fact": "known", "value": 2},
        TruthValue.UNKNOWN: {"op": "eq", "fact": "missing", "value": 1},
    }[truth]

    assert evaluate_condition_ast(
        _document({"op": "not", "arg": expression}), {"known": 1}
    ) is expected


def test_comparisons_membership_and_existence_are_pure_and_typed() -> None:
    facts = {"volume": 0.5, "codec": "ac3", "nullable": None, "flag": True}
    cases = (
        ({"op": "eq", "fact": "codec", "value": "ac3"}, TruthValue.TRUE),
        ({"op": "ne", "fact": "codec", "value": "dts"}, TruthValue.TRUE),
        ({"op": "gt", "fact": "volume", "value": 0.25}, TruthValue.TRUE),
        ({"op": "lte", "fact": "volume", "value": 0.25}, TruthValue.FALSE),
        ({"op": "in", "fact": "codec", "values": ["ac3", "dts"]}, TruthValue.TRUE),
        ({"op": "not_in", "fact": "codec", "values": ["pcm"]}, TruthValue.TRUE),
        ({"op": "exists", "fact": "nullable"}, TruthValue.TRUE),
        ({"op": "exists", "fact": "missing"}, TruthValue.FALSE),
        ({"op": "gt", "fact": "flag", "value": 0}, TruthValue.UNKNOWN),
        ({"op": "eq", "fact": "flag", "value": 1}, TruthValue.FALSE),
    )

    before = dict(facts)
    for expression, expected in cases:
        assert evaluate_condition_ast(_document(expression), facts) is expected
    assert facts == before


@pytest.mark.parametrize(
    ("policy", "status"),
    (
        (UnknownResult.ELIGIBLE, EligibilityStatus.ELIGIBLE),
        (UnknownResult.INELIGIBLE, EligibilityStatus.INELIGIBLE),
        (UnknownResult.WAITING, EligibilityStatus.WAITING),
        (UnknownResult.ERROR, EligibilityStatus.ERROR),
    ),
)
def test_each_eligibility_context_declares_unknown_behavior(policy, status) -> None:
    decision = evaluate_eligibility(
        _document({"op": "eq", "fact": "missing", "value": True}),
        {},
        unknown_result=policy,
    )

    assert decision.truth is TruthValue.UNKNOWN
    assert decision.status is status
    assert decision.unknown_result is policy


def test_true_and_false_ignore_unknown_policy() -> None:
    true_decision = evaluate_eligibility(
        _document({"op": "eq", "fact": "mode.cinema", "value": True}),
        {"mode.cinema": True},
        unknown_result="error",
    )
    false_decision = evaluate_eligibility(
        _document({"op": "eq", "fact": "mode.cinema", "value": True}),
        {"mode.cinema": False},
        unknown_result="eligible",
    )

    assert true_decision.status is EligibilityStatus.ELIGIBLE
    assert false_decision.status is EligibilityStatus.INELIGIBLE


def test_stable_duration_is_unknown_without_observation_and_then_thresholded() -> None:
    argument = {"op": "eq", "fact": "endpoint.headset.availability", "value": "route-available"}
    document = _document(
        {"op": "stable_for", "arg": argument, "durationMs": 500}
    )
    facts = {"endpoint.headset.availability": "route-available"}

    unknown = evaluate_condition_ast(document, facts)
    pending = evaluate_condition_ast(
        document,
        facts,
        stable_durations_ms={condition_expression_key(argument): 499},
    )
    stable = evaluate_condition_ast(
        document,
        facts,
        stable_durations_ms={condition_expression_key(argument): 500},
    )

    assert unknown is TruthValue.UNKNOWN
    assert pending is TruthValue.FALSE
    assert stable is TruthValue.TRUE


def test_invalid_ast_is_rejected_before_evaluation() -> None:
    with pytest.raises(ValueError, match="invalid condition AST"):
        evaluate_condition_ast(_document({"op": "unknown"}), {})


def test_unknown_policy_is_mandatory_and_validated() -> None:
    document = _document({"op": "exists", "fact": "mode.x"})

    with pytest.raises(TypeError):
        evaluate_eligibility(document, {})
    with pytest.raises(ValueError, match="unknown_result"):
        evaluate_eligibility(document, {}, unknown_result="guess")
