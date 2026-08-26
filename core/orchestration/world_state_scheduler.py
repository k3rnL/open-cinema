from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum

from wyreplumber.runtime import FrozenDict

from .signal_descriptors import SignalDescriptor


class WorldStateScheduleStatus(StrEnum):
    IGNORED = "ignored"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class WorldStateStabilityPolicy:
    minimum_confidence: float = 0.9
    detection_window_ms: int = 0
    confidence_hysteresis: float = 0.0
    debounce_ms: int = 0
    stable_duration_ms: int = 0
    cooldown_ms: int = 0

    def __post_init__(self) -> None:
        for name in ("minimum_confidence", "confidence_hysteresis"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            value = float(value)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)
        for name in (
            "detection_window_ms",
            "debounce_ms",
            "stable_duration_ms",
            "cooldown_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @property
    def switch_confidence(self) -> float:
        return min(1.0, self.minimum_confidence + self.confidence_hysteresis)

    @property
    def retain_confidence(self) -> float:
        return max(0.0, self.minimum_confidence - self.confidence_hysteresis)

    def to_document(self) -> dict[str, object]:
        return {
            "minimumConfidence": self.minimum_confidence,
            "detectionWindowMs": self.detection_window_ms,
            "confidenceHysteresis": self.confidence_hysteresis,
            "debounceMs": self.debounce_ms,
            "stableDurationMs": self.stable_duration_ms,
            "cooldownMs": self.cooldown_ms,
        }

    @classmethod
    def from_document(cls, document) -> WorldStateStabilityPolicy:
        if not hasattr(document, "get"):
            raise TypeError("stability policy must be an object")
        return cls(
            minimum_confidence=document.get("minimumConfidence", 0.9),
            detection_window_ms=document.get("detectionWindowMs", 0),
            confidence_hysteresis=document.get("confidenceHysteresis", 0.0),
            debounce_ms=document.get("debounceMs", 0),
            stable_duration_ms=document.get("stableDurationMs", 0),
            cooldown_ms=document.get("cooldownMs", 0),
        )


@dataclass(frozen=True, slots=True)
class WorldStateObservation:
    material_key: str
    confidence: float
    observation_window_ms: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.material_key, str) or not self.material_key:
            raise ValueError("material_key must be a non-empty string")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be a number")
        confidence = float(self.confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        for name in ("observation_window_ms", "observed_at_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class WorldStateScheduleState:
    active_key: str | None = None
    active_confidence: float | None = None
    pending_key: str | None = None
    pending_confidence: float | None = None
    pending_since_ms: int | None = None
    last_observed_at_ms: int | None = None
    last_transition_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class WorldStateScheduleDecision:
    status: WorldStateScheduleStatus
    state: WorldStateScheduleState
    schedule_resolution: bool
    reason: str
    reevaluate_at_ms: int | None
    diagnostics: FrozenDict


def signal_descriptor_material_key(descriptor: SignalDescriptor) -> str:
    """Return a stable identity for material signal fields, excluding observation metadata."""

    if not isinstance(descriptor, SignalDescriptor):
        raise TypeError("descriptor must be a SignalDescriptor")
    material = {
        "transport": descriptor.transport.to_document(),
        "content": descriptor.content.to_document(),
        "decodedOutput": (
            descriptor.decoded_output.to_document()
            if descriptor.decoded_output is not None
            else None
        ),
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"signal:{descriptor.content.kind.value}:{hashlib.sha256(encoded).hexdigest()}"


def signal_world_state_observation(
    descriptor: SignalDescriptor,
    *,
    observation_window_ms: int,
    observed_at_ms: int,
) -> WorldStateObservation:
    return WorldStateObservation(
        material_key=signal_descriptor_material_key(descriptor),
        confidence=descriptor.confidence,
        observation_window_ms=observation_window_ms,
        observed_at_ms=observed_at_ms,
    )


def _diagnostics(
    policy: WorldStateStabilityPolicy,
    observation: WorldStateObservation,
    *,
    required_confidence: float,
    pending_since_ms: int | None,
    ready_at_ms: int | None,
    cooldown_until_ms: int | None,
) -> FrozenDict:
    return FrozenDict(
        {
            "observedConfidence": observation.confidence,
            "requiredConfidence": required_confidence,
            "observationWindowMs": observation.observation_window_ms,
            "requiredDetectionWindowMs": policy.detection_window_ms,
            "pendingSinceMs": pending_since_ms,
            "readyAtMs": ready_at_ms,
            "cooldownUntilMs": cooldown_until_ms,
        }
    )


def schedule_world_state_observation(
    policy: WorldStateStabilityPolicy,
    state: WorldStateScheduleState,
    observation: WorldStateObservation,
) -> WorldStateScheduleDecision:
    """Purely decide whether one material world-state change should trigger resolution."""

    if not isinstance(policy, WorldStateStabilityPolicy):
        raise TypeError("policy must be a WorldStateStabilityPolicy")
    if not isinstance(state, WorldStateScheduleState):
        raise TypeError("state must be a WorldStateScheduleState")
    if not isinstance(observation, WorldStateObservation):
        raise TypeError("observation must be a WorldStateObservation")
    if (
        state.last_observed_at_ms is not None
        and observation.observed_at_ms < state.last_observed_at_ms
    ):
        return WorldStateScheduleDecision(
            WorldStateScheduleStatus.IGNORED,
            state,
            False,
            "stale_observation",
            None,
            _diagnostics(
                policy,
                observation,
                required_confidence=policy.minimum_confidence,
                pending_since_ms=state.pending_since_ms,
                ready_at_ms=None,
                cooldown_until_ms=None,
            ),
        )

    same_as_active = observation.material_key == state.active_key
    required_confidence = (
        policy.retain_confidence
        if same_as_active
        else (
            policy.switch_confidence if state.active_key is not None else policy.minimum_confidence
        )
    )
    observed_state = replace(state, last_observed_at_ms=observation.observed_at_ms)
    if observation.confidence + 1e-12 < required_confidence:
        return WorldStateScheduleDecision(
            WorldStateScheduleStatus.IGNORED,
            observed_state,
            False,
            (
                "confidence_below_retain_threshold"
                if same_as_active
                else "confidence_below_switch_threshold"
            ),
            None,
            _diagnostics(
                policy,
                observation,
                required_confidence=required_confidence,
                pending_since_ms=state.pending_since_ms,
                ready_at_ms=None,
                cooldown_until_ms=None,
            ),
        )
    if observation.observation_window_ms < policy.detection_window_ms:
        return WorldStateScheduleDecision(
            WorldStateScheduleStatus.IGNORED,
            observed_state,
            False,
            "detection_window_incomplete",
            None,
            _diagnostics(
                policy,
                observation,
                required_confidence=required_confidence,
                pending_since_ms=state.pending_since_ms,
                ready_at_ms=None,
                cooldown_until_ms=None,
            ),
        )
    if same_as_active:
        unchanged_state = replace(
            observed_state,
            active_confidence=observation.confidence,
            pending_key=None,
            pending_confidence=None,
            pending_since_ms=None,
        )
        return WorldStateScheduleDecision(
            WorldStateScheduleStatus.UNCHANGED,
            unchanged_state,
            False,
            "material_state_unchanged",
            None,
            _diagnostics(
                policy,
                observation,
                required_confidence=required_confidence,
                pending_since_ms=None,
                ready_at_ms=None,
                cooldown_until_ms=None,
            ),
        )

    pending_since_ms = (
        state.pending_since_ms
        if state.pending_key == observation.material_key and state.pending_since_ms is not None
        else observation.observed_at_ms
    )
    cooldown_until_ms = (
        state.last_transition_at_ms + policy.cooldown_ms
        if state.last_transition_at_ms is not None
        else observation.observed_at_ms
    )
    ready_at_ms = max(
        pending_since_ms + policy.debounce_ms,
        pending_since_ms + policy.stable_duration_ms,
        cooldown_until_ms,
    )
    pending_state = replace(
        observed_state,
        pending_key=observation.material_key,
        pending_confidence=observation.confidence,
        pending_since_ms=pending_since_ms,
    )
    if observation.observed_at_ms < ready_at_ms:
        return WorldStateScheduleDecision(
            WorldStateScheduleStatus.PENDING,
            pending_state,
            False,
            "stability_controls_pending",
            ready_at_ms,
            _diagnostics(
                policy,
                observation,
                required_confidence=required_confidence,
                pending_since_ms=pending_since_ms,
                ready_at_ms=ready_at_ms,
                cooldown_until_ms=cooldown_until_ms,
            ),
        )

    scheduled_state = replace(
        pending_state,
        active_key=observation.material_key,
        active_confidence=observation.confidence,
        pending_key=None,
        pending_confidence=None,
        pending_since_ms=None,
        last_transition_at_ms=observation.observed_at_ms,
    )
    return WorldStateScheduleDecision(
        WorldStateScheduleStatus.SCHEDULED,
        scheduled_state,
        True,
        "stable_material_change",
        None,
        _diagnostics(
            policy,
            observation,
            required_confidence=required_confidence,
            pending_since_ms=pending_since_ms,
            ready_at_ms=ready_at_ms,
            cooldown_until_ms=cooldown_until_ms,
        ),
    )
