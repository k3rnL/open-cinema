from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Event, RLock

from .driver_actions import (
    ActionFailure,
    ActionFailureClassification,
    DriverAction,
    DriverActionError,
)
from .execution_limits import ActionExecutionLimits


class ActionFailureHandling(StrEnum):
    RETRY_SAME_ACTION = "retry-same-action"
    RERESOLVE = "reresolve"
    SAFE_RECOVERY = "safe-recovery"
    STOP_PERMANENT = "stop-permanent"
    RETRIES_EXHAUSTED = "retries-exhausted"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ActionRetryDecision:
    handling: ActionFailureHandling
    failed_attempt: int
    next_attempt: int | None
    delay_seconds: float | None
    failure: ActionFailure
    reason: str


@dataclass(frozen=True, slots=True)
class ActionRetryPolicy:
    max_attempts: int
    initial_seconds: float
    max_seconds: float
    multiplier: float = 2.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        limits = ActionExecutionLimits.from_settings()
        if self.max_attempts > limits.max_attempts:
            raise ValueError(
                f"max_attempts exceeds configured maximum ({limits.max_attempts})"
            )
        for field in (
            "initial_seconds",
            "max_seconds",
            "multiplier",
            "jitter_ratio",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field} must be a number")
        if self.initial_seconds <= 0 or self.max_seconds < self.initial_seconds:
            raise ValueError("action retry backoff bounds are invalid")
        if self.max_seconds > limits.max_retry_delay_seconds:
            raise ValueError(
                "max_seconds exceeds configured retry delay maximum "
                f"({limits.max_retry_delay_seconds})"
            )
        if self.multiplier < 1:
            raise ValueError("action retry multiplier must be at least one")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("action retry jitter_ratio must be between zero and one")


class ActionRetryController:
    def __init__(
        self,
        policy: ActionRetryPolicy,
        *,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if not isinstance(policy, ActionRetryPolicy):
            raise TypeError("policy must be an ActionRetryPolicy")
        if not callable(random_value):
            raise TypeError("random_value must be callable")
        self.policy = policy
        self.random_value = random_value
        self._lock = RLock()
        self._failed_attempts: dict[str, int] = {}

    def clear(self, action: DriverAction) -> None:
        if not isinstance(action, DriverAction):
            raise TypeError("action must be a DriverAction")
        with self._lock:
            self._failed_attempts.pop(action.idempotency_key, None)

    def _retry_delay(self, failed_attempt: int, failure: ActionFailure) -> float:
        base = min(
            self.policy.max_seconds,
            self.policy.initial_seconds * (self.policy.multiplier ** max(0, failed_attempt - 1)),
        )
        jitter = base * self.policy.jitter_ratio
        randomized = base - jitter + (2 * jitter * self.random_value())
        delay = max(0.0, randomized)
        if failure.retry_after_seconds is not None:
            delay = max(delay, failure.retry_after_seconds)
        return min(self.policy.max_seconds, delay)

    def record_failure(
        self,
        action: DriverAction,
        failure: ActionFailure,
    ) -> ActionRetryDecision:
        if not isinstance(action, DriverAction):
            raise TypeError("action must be a DriverAction")
        if not isinstance(failure, ActionFailure):
            raise TypeError("failure must be an ActionFailure")
        with self._lock:
            attempt = self._failed_attempts.get(action.idempotency_key, 0) + 1
            self._failed_attempts[action.idempotency_key] = attempt

        if failure.classification is ActionFailureClassification.STALE_PRECONDITION:
            return ActionRetryDecision(
                ActionFailureHandling.RERESOLVE,
                attempt,
                None,
                None,
                failure,
                "Observed preconditions changed; discard this action and resolve again.",
            )
        if failure.classification is ActionFailureClassification.SAFETY:
            return ActionRetryDecision(
                ActionFailureHandling.SAFE_RECOVERY,
                attempt,
                None,
                None,
                failure,
                "Safety verification failed; keep suppression and run declared recovery.",
            )
        if failure.classification is ActionFailureClassification.PERMANENT:
            return ActionRetryDecision(
                ActionFailureHandling.STOP_PERMANENT,
                attempt,
                None,
                None,
                failure,
                "The current action cannot succeed until intent or implementation changes.",
            )
        if attempt >= self.policy.max_attempts:
            return ActionRetryDecision(
                ActionFailureHandling.RETRIES_EXHAUSTED,
                attempt,
                None,
                None,
                failure,
                "The bounded retry budget is exhausted.",
            )
        delay = self._retry_delay(attempt, failure)
        return ActionRetryDecision(
            ActionFailureHandling.RETRY_SAME_ACTION,
            attempt,
            attempt + 1,
            delay,
            failure,
            "Retry the identical idempotent action after bounded backoff.",
        )


class ActionRetryTerminated(RuntimeError):
    def __init__(self, action: DriverAction, decision: ActionRetryDecision) -> None:
        self.action = action
        self.decision = decision
        super().__init__(
            f"action retry ended with {decision.handling.value} after "
            f"attempt {decision.failed_attempt}: {decision.failure.message}"
        )


def run_with_action_retry(
    action: DriverAction,
    operation: Callable[[DriverAction], object],
    controller: ActionRetryController,
    *,
    wait: Callable[[float], object],
    stop_event: Event | None = None,
):
    if not isinstance(action, DriverAction):
        raise TypeError("action must be a DriverAction")
    if not callable(operation) or not callable(wait):
        raise TypeError("operation and wait must be callable")
    if not isinstance(controller, ActionRetryController):
        raise TypeError("controller must be an ActionRetryController")
    while True:
        if stop_event is not None and stop_event.is_set():
            failure = ActionFailure(
                ActionFailureClassification.TRANSIENT,
                "retry-interrupted",
                "Action retry was interrupted by shutdown.",
            )
            decision = ActionRetryDecision(
                ActionFailureHandling.INTERRUPTED,
                0,
                None,
                None,
                failure,
                "Shutdown interrupted retry before another mutation.",
            )
            raise ActionRetryTerminated(action, decision)
        try:
            result = operation(action)
        except DriverActionError as error:
            if error.action != action:
                raise ValueError("driver reported a failure for another action") from error
            decision = controller.record_failure(action, error.failure)
            if decision.handling is not ActionFailureHandling.RETRY_SAME_ACTION:
                raise ActionRetryTerminated(action, decision) from error
            if stop_event is not None:
                if stop_event.wait(timeout=decision.delay_seconds):
                    interrupted = ActionRetryDecision(
                        ActionFailureHandling.INTERRUPTED,
                        decision.failed_attempt,
                        None,
                        None,
                        error.failure,
                        "Shutdown interrupted the bounded retry wait.",
                    )
                    raise ActionRetryTerminated(action, interrupted) from error
            else:
                wait(decision.delay_seconds)
            continue
        controller.clear(action)
        return result
