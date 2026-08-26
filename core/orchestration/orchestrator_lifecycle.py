from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock

from wyreplumber.runtime import FrozenDict


class DependencyHealth(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class OrchestratorLifecycleState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OrchestratorHealthSnapshot:
    sequence: int
    state: OrchestratorLifecycleState
    live: bool
    ready: bool
    dependencies: FrozenDict
    last_success_at: str | None
    last_failure: FrozenDict | None
    next_retry_seconds: float | None

    def to_document(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "state": self.state.value,
            "live": self.live,
            "ready": self.ready,
            "dependencies": self.dependencies.to_dict(),
            "lastSuccessAt": self.last_success_at,
            "lastFailure": (self.last_failure.to_dict() if self.last_failure is not None else None),
            "nextRetrySeconds": self.next_retry_seconds,
        }


class BoundedReconnectBackoff:
    def __init__(
        self,
        *,
        initial_seconds: float,
        max_seconds: float,
        multiplier: float = 2.0,
        jitter_ratio: float = 0.2,
        random_value=random.random,
    ) -> None:
        for name, value in (
            ("initial_seconds", initial_seconds),
            ("max_seconds", max_seconds),
            ("multiplier", multiplier),
            ("jitter_ratio", jitter_ratio),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
        if initial_seconds <= 0 or max_seconds < initial_seconds:
            raise ValueError("backoff bounds are invalid")
        if multiplier < 1:
            raise ValueError("multiplier must be at least one")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")
        self.initial_seconds = float(initial_seconds)
        self.max_seconds = float(max_seconds)
        self.multiplier = float(multiplier)
        self.jitter_ratio = float(jitter_ratio)
        self.random_value = random_value
        self.attempt = 0

    def next_delay(self) -> float:
        base = min(
            self.max_seconds,
            self.initial_seconds * (self.multiplier**self.attempt),
        )
        self.attempt += 1
        jitter = base * self.jitter_ratio
        return min(
            self.max_seconds,
            max(0.0, base - jitter + (2 * jitter * self.random_value())),
        )

    def reset(self) -> None:
        self.attempt = 0


class OrchestratorLifecycle:
    REQUIRED_DEPENDENCIES = ("database", "pipewire", "wireplumber")
    OPTIONAL_DEPENDENCIES = ("redis",)

    def __init__(self, *, clock=None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._sequence = 0
        self._state = OrchestratorLifecycleState.STARTING
        self._dependencies = {
            name: {"health": DependencyHealth.UNKNOWN.value, "reason": None}
            for name in (*self.REQUIRED_DEPENDENCIES, *self.OPTIONAL_DEPENDENCIES)
        }
        self._last_success_at = None
        self._last_failure = None
        self._next_retry_seconds = None

    def _timestamp(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat()

    def _derive(self) -> None:
        if self._state in {
            OrchestratorLifecycleState.RECONNECTING,
            OrchestratorLifecycleState.STOPPING,
            OrchestratorLifecycleState.STOPPED,
            OrchestratorLifecycleState.FAILED,
        }:
            return
        required_ready = all(
            self._dependencies[name]["health"] == DependencyHealth.READY.value
            for name in self.REQUIRED_DEPENDENCIES
        )
        any_problem = any(
            value["health"] in {DependencyHealth.DEGRADED.value, DependencyHealth.UNAVAILABLE.value}
            for value in self._dependencies.values()
        )
        if required_ready and not any_problem:
            self._state = OrchestratorLifecycleState.READY
            self._last_success_at = self._timestamp()
        elif required_ready or any_problem:
            self._state = OrchestratorLifecycleState.DEGRADED
        else:
            self._state = OrchestratorLifecycleState.STARTING

    @property
    def snapshot(self) -> OrchestratorHealthSnapshot:
        with self._lock:
            required_ready = all(
                self._dependencies[name]["health"] == DependencyHealth.READY.value
                for name in self.REQUIRED_DEPENDENCIES
            )
            live = self._state not in {
                OrchestratorLifecycleState.STOPPED,
                OrchestratorLifecycleState.FAILED,
            }
            return OrchestratorHealthSnapshot(
                sequence=self._sequence,
                state=self._state,
                live=live,
                ready=required_ready
                and self._state
                in {
                    OrchestratorLifecycleState.READY,
                    OrchestratorLifecycleState.DEGRADED,
                },
                dependencies=FrozenDict(self._dependencies),
                last_success_at=self._last_success_at,
                last_failure=(
                    FrozenDict(self._last_failure) if self._last_failure is not None else None
                ),
                next_retry_seconds=self._next_retry_seconds,
            )

    def dependency(
        self,
        name: str,
        health: DependencyHealth,
        *,
        reason: str | None = None,
    ) -> OrchestratorHealthSnapshot:
        if name not in self._dependencies:
            raise ValueError(f"unknown dependency {name!r}")
        health = DependencyHealth(health)
        with self._lock:
            self._dependencies[name] = {"health": health.value, "reason": reason}
            self._sequence += 1
            if (
                self._state is OrchestratorLifecycleState.RECONNECTING
                and health is DependencyHealth.READY
            ):
                self._state = OrchestratorLifecycleState.STARTING
                self._next_retry_seconds = None
            self._derive()
            return self.snapshot

    def reconnecting(
        self,
        dependency: str,
        *,
        reason: str,
        next_retry_seconds: float,
    ) -> OrchestratorHealthSnapshot:
        if dependency not in self._dependencies:
            raise ValueError(f"unknown dependency {dependency!r}")
        if (
            isinstance(next_retry_seconds, bool)
            or not isinstance(next_retry_seconds, (int, float))
            or next_retry_seconds < 0
        ):
            raise ValueError("next_retry_seconds must be a non-negative number")
        with self._lock:
            self._dependencies[dependency] = {
                "health": DependencyHealth.UNAVAILABLE.value,
                "reason": reason,
            }
            self._state = OrchestratorLifecycleState.RECONNECTING
            self._next_retry_seconds = float(next_retry_seconds)
            self._last_failure = {
                "dependency": dependency,
                "reason": reason,
                "occurredAt": self._timestamp(),
            }
            self._sequence += 1
            return self.snapshot

    def stopping(self) -> OrchestratorHealthSnapshot:
        with self._lock:
            self._state = OrchestratorLifecycleState.STOPPING
            self._sequence += 1
            return self.snapshot

    def stopped(self) -> OrchestratorHealthSnapshot:
        with self._lock:
            self._state = OrchestratorLifecycleState.STOPPED
            self._sequence += 1
            return self.snapshot
