from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True, slots=True)
class ActionExecutionLimits:
    max_timeout_seconds: float
    max_attempts: int
    max_retry_delay_seconds: float

    def __post_init__(self) -> None:
        for name in ("max_timeout_seconds", "max_retry_delay_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")

    @classmethod
    def from_settings(cls) -> "ActionExecutionLimits":
        values = settings.AUDIO_ACTION_EXECUTION_LIMITS
        expected = {
            "max_timeout_seconds",
            "max_attempts",
            "max_retry_delay_seconds",
        }
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError(
                "AUDIO_ACTION_EXECUTION_LIMITS must define exactly "
                f"{', '.join(sorted(expected))}"
            )
        return cls(**values)
