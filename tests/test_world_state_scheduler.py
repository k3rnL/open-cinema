from dataclasses import replace

import pytest

from core.orchestration.world_state_scheduler import (
    WorldStateObservation,
    WorldStateScheduleState,
    WorldStateScheduleStatus,
    WorldStateStabilityPolicy,
    schedule_world_state_observation,
    signal_descriptor_material_key,
)
from tests.test_adaptive_decoder import _descriptor


def _observation(key, at, confidence=0.99, window=500):
    return WorldStateObservation(key, confidence, window, at)


def test_stability_policy_round_trips_every_configurable_control() -> None:
    document = {
        "minimumConfidence": 0.8,
        "detectionWindowMs": 250,
        "confidenceHysteresis": 0.1,
        "debounceMs": 50,
        "stableDurationMs": 300,
        "cooldownMs": 1_000,
    }

    assert WorldStateStabilityPolicy.from_document(document).to_document() == document


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("minimum_confidence", 1.1),
        ("confidence_hysteresis", -0.1),
        ("detection_window_ms", -1),
        ("debounce_ms", True),
        ("stable_duration_ms", -1),
        ("cooldown_ms", -1),
    ),
)
def test_stability_policy_rejects_invalid_controls(field, value) -> None:
    with pytest.raises((TypeError, ValueError)):
        WorldStateStabilityPolicy(**{field: value})


def test_low_confidence_false_preamble_keeps_active_state_and_is_explained() -> None:
    policy = WorldStateStabilityPolicy(
        minimum_confidence=0.9,
        confidence_hysteresis=0.05,
    )
    state = WorldStateScheduleState(
        active_key="pcm",
        active_confidence=0.99,
        last_observed_at_ms=1_000,
        last_transition_at_ms=1_000,
    )

    decision = schedule_world_state_observation(
        policy,
        state,
        _observation("ac3", 1_010, confidence=0.4),
    )

    assert decision.status is WorldStateScheduleStatus.IGNORED
    assert decision.state.active_key == "pcm"
    assert decision.state.pending_key is None
    assert decision.reason == "confidence_below_switch_threshold"
    assert decision.diagnostics["requiredConfidence"] == pytest.approx(0.95)


def test_detection_window_must_cover_the_configured_amount_of_audio() -> None:
    policy = WorldStateStabilityPolicy(detection_window_ms=500)

    decision = schedule_world_state_observation(
        policy,
        WorldStateScheduleState(),
        _observation("ac3", 1_000, window=499),
    )

    assert decision.status is WorldStateScheduleStatus.IGNORED
    assert decision.reason == "detection_window_incomplete"
    assert decision.diagnostics["requiredDetectionWindowMs"] == 500


def test_hysteresis_requires_more_confidence_to_switch_than_to_retain() -> None:
    policy = WorldStateStabilityPolicy(
        minimum_confidence=0.9,
        confidence_hysteresis=0.05,
    )
    state = WorldStateScheduleState(active_key="pcm", active_confidence=0.99)

    rejected = schedule_world_state_observation(
        policy,
        state,
        _observation("ac3", 100, confidence=0.94),
    )
    accepted = schedule_world_state_observation(
        policy,
        rejected.state,
        _observation("ac3", 101, confidence=0.95),
    )
    retained = schedule_world_state_observation(
        policy,
        accepted.state,
        _observation("ac3", 102, confidence=0.86),
    )

    assert rejected.status is WorldStateScheduleStatus.IGNORED
    assert accepted.status is WorldStateScheduleStatus.SCHEDULED
    assert retained.status is WorldStateScheduleStatus.UNCHANGED


def test_debounce_and_stable_duration_hold_then_schedule_once() -> None:
    policy = WorldStateStabilityPolicy(debounce_ms=50, stable_duration_ms=300)

    first = schedule_world_state_observation(
        policy,
        WorldStateScheduleState(),
        _observation("ac3", 1_000),
    )
    before = schedule_world_state_observation(
        policy,
        first.state,
        _observation("ac3", 1_299),
    )
    ready = schedule_world_state_observation(
        policy,
        before.state,
        _observation("ac3", 1_300),
    )
    unchanged = schedule_world_state_observation(
        policy,
        ready.state,
        _observation("ac3", 1_301),
    )

    assert first.reevaluate_at_ms == 1_300
    assert before.status is WorldStateScheduleStatus.PENDING
    assert ready.schedule_resolution is True
    assert ready.status is WorldStateScheduleStatus.SCHEDULED
    assert unchanged.status is WorldStateScheduleStatus.UNCHANGED


def test_new_candidate_restarts_stable_duration() -> None:
    policy = WorldStateStabilityPolicy(stable_duration_ms=100)
    first = schedule_world_state_observation(
        policy,
        WorldStateScheduleState(),
        _observation("ac3", 1_000),
    )

    changed = schedule_world_state_observation(
        policy,
        first.state,
        _observation("dts", 1_050),
    )

    assert changed.state.pending_key == "dts"
    assert changed.state.pending_since_ms == 1_050
    assert changed.reevaluate_at_ms == 1_150


def test_cooldown_delays_an_otherwise_stable_switch() -> None:
    policy = WorldStateStabilityPolicy(cooldown_ms=1_000)
    state = WorldStateScheduleState(
        active_key="pcm",
        active_confidence=1.0,
        last_transition_at_ms=1_000,
    )

    pending = schedule_world_state_observation(
        policy,
        state,
        _observation("ac3", 1_100),
    )
    ready = schedule_world_state_observation(
        policy,
        pending.state,
        _observation("ac3", 2_000),
    )

    assert pending.reevaluate_at_ms == 2_000
    assert pending.diagnostics["cooldownUntilMs"] == 2_000
    assert ready.status is WorldStateScheduleStatus.SCHEDULED


def test_stale_observation_cannot_replace_newer_scheduler_state() -> None:
    state = WorldStateScheduleState(last_observed_at_ms=2_000)

    decision = schedule_world_state_observation(
        WorldStateStabilityPolicy(),
        state,
        _observation("ac3", 1_999),
    )

    assert decision.reason == "stale_observation"
    assert decision.state is state


def test_signal_material_key_ignores_confidence_source_sequence_and_time() -> None:
    original = _descriptor(confidence=0.99)
    later = replace(
        original,
        confidence=0.91,
        source=replace(original.source, sequence=99),
        observed_at="2026-08-22T17:00:00Z",
    )

    assert signal_descriptor_material_key(original) == signal_descriptor_material_key(later)
    assert signal_descriptor_material_key(original) != signal_descriptor_material_key(
        _descriptor(codec="dts")
    )
