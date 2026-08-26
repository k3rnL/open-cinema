import pytest

from core.orchestration.condition_evaluation import (
    TruthValue,
    condition_expression_key,
    evaluate_condition_ast,
)
from core.orchestration.stable_duration import StableDurationTracker


FACT = "endpoint.headset.availability"
ARGUMENT = {"op": "eq", "fact": FACT, "value": "route-available"}
DOCUMENT = {
    "version": 1,
    "expression": {
        "op": "stable_for",
        "arg": ARGUMENT,
        "durationMs": 500,
    },
}


def test_stability_uses_supplied_monotonic_observations_without_sleeping() -> None:
    tracker = StableDurationTracker()
    facts = {FACT: "route-available"}

    started = tracker.observe(DOCUMENT, facts, observed_at_ms=10_000)
    pending = tracker.observe(DOCUMENT, facts, observed_at_ms=10_499)
    ready = tracker.observe(DOCUMENT, facts, observed_at_ms=10_500)

    key = condition_expression_key(ARGUMENT)
    assert started.durations_ms[key] == 0
    assert pending.durations_ms[key] == 499
    assert ready.durations_ms[key] == 500
    assert evaluate_condition_ast(
        DOCUMENT, facts, stable_durations_ms=pending.durations_ms
    ) is TruthValue.FALSE
    assert evaluate_condition_ast(
        DOCUMENT, facts, stable_durations_ms=ready.durations_ms
    ) is TruthValue.TRUE


def test_false_and_unknown_observations_reset_true_stability() -> None:
    tracker = StableDurationTracker()
    key = condition_expression_key(ARGUMENT)
    tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=100)
    stable = tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=700)
    false = tracker.observe(DOCUMENT, {FACT: "unavailable"}, observed_at_ms=800)
    unknown = tracker.observe(DOCUMENT, {}, observed_at_ms=900)
    restarted = tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=1_000)

    assert stable.durations_ms[key] == 600
    assert key not in false.durations_ms
    assert false.truths[key] is TruthValue.FALSE
    assert key not in unknown.durations_ms
    assert unknown.truths[key] is TruthValue.UNKNOWN
    assert restarted.durations_ms[key] == 0


def test_unrelated_fact_changes_do_not_reset_tracked_expression() -> None:
    tracker = StableDurationTracker()
    key = condition_expression_key(ARGUMENT)
    tracker.observe(
        DOCUMENT,
        {FACT: "route-available", "mode.cinema": False},
        observed_at_ms=1_000,
    )

    snapshot = tracker.observe(
        DOCUMENT,
        {FACT: "route-available", "mode.cinema": True},
        observed_at_ms=1_250,
    )

    assert snapshot.durations_ms[key] == 250


def test_backwards_observation_is_rejected_without_changing_state() -> None:
    tracker = StableDurationTracker()
    key = condition_expression_key(ARGUMENT)
    tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=500)

    with pytest.raises(ValueError, match="backwards"):
        tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=499)

    snapshot = tracker.observe(
        DOCUMENT, {FACT: "route-available"}, observed_at_ms=750
    )
    assert snapshot.durations_ms[key] == 250


def test_nested_stable_duration_is_evaluated_inside_out() -> None:
    inner = {"op": "stable_for", "arg": ARGUMENT, "durationMs": 100}
    document = {
        "version": 1,
        "expression": {"op": "stable_for", "arg": inner, "durationMs": 200},
    }
    tracker = StableDurationTracker()
    facts = {FACT: "route-available"}

    first = tracker.observe(document, facts, observed_at_ms=0)
    inner_ready = tracker.observe(document, facts, observed_at_ms=100)
    outer_ready = tracker.observe(document, facts, observed_at_ms=300)

    assert evaluate_condition_ast(
        document, facts, stable_durations_ms=first.durations_ms
    ) is TruthValue.FALSE
    assert evaluate_condition_ast(
        document, facts, stable_durations_ms=inner_ready.durations_ms
    ) is TruthValue.FALSE
    assert evaluate_condition_ast(
        document, facts, stable_durations_ms=outer_ready.durations_ms
    ) is TruthValue.TRUE


def test_reset_drops_stability_across_runtime_generation_change() -> None:
    tracker = StableDurationTracker()
    key = condition_expression_key(ARGUMENT)
    tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=100)
    tracker.observe(DOCUMENT, {FACT: "route-available"}, observed_at_ms=700)

    tracker.reset()
    snapshot = tracker.observe(
        DOCUMENT, {FACT: "route-available"}, observed_at_ms=10
    )

    assert tracker.last_observed_at_ms == 10
    assert snapshot.durations_ms[key] == 0


def test_snapshot_mappings_are_immutable() -> None:
    snapshot = StableDurationTracker().observe(
        DOCUMENT, {FACT: "route-available"}, observed_at_ms=0
    )

    with pytest.raises(TypeError):
        snapshot.durations_ms["other"] = 1
    with pytest.raises(TypeError):
        snapshot.truths["other"] = TruthValue.TRUE
