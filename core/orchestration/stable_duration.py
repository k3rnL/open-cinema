from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .condition_ast import ConditionOperator, validate_condition_ast
from .condition_evaluation import (
    TruthValue,
    condition_expression_key,
    evaluate_condition_expression,
)


@dataclass(frozen=True, slots=True)
class StableDurationState:
    expression_key: str
    truth: TruthValue
    stable_since_ms: int


@dataclass(frozen=True, slots=True)
class StableDurationSnapshot:
    observed_at_ms: int
    durations_ms: Mapping[str, int]
    truths: Mapping[str, TruthValue]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "durations_ms",
            MappingProxyType(dict(self.durations_ms)),
        )
        object.__setattr__(self, "truths", MappingProxyType(dict(self.truths)))


def _stable_arguments(expression: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    seen: set[str] = set()

    def visit(current: Mapping[str, object]) -> None:
        operator = ConditionOperator(current["op"])
        if operator in {ConditionOperator.ALL, ConditionOperator.ANY}:
            for argument in current["args"]:
                visit(argument)
        elif operator is ConditionOperator.NOT:
            visit(current["arg"])
        elif operator is ConditionOperator.STABLE_FOR:
            argument = current["arg"]
            visit(argument)
            key = condition_expression_key(argument)
            if key not in seen:
                seen.add(key)
                result.append(argument)

    visit(expression)
    return tuple(result)


class StableDurationTracker:
    """Track expression stability from caller-supplied monotonic observations."""

    def __init__(self) -> None:
        self._states: dict[str, StableDurationState] = {}
        self._last_observed_at_ms: int | None = None

    @property
    def last_observed_at_ms(self) -> int | None:
        return self._last_observed_at_ms

    def reset(self) -> None:
        self._states.clear()
        self._last_observed_at_ms = None

    def observe(
        self,
        document: Mapping[str, object],
        facts: Mapping[str, object],
        *,
        observed_at_ms: int,
    ) -> StableDurationSnapshot:
        if isinstance(observed_at_ms, bool) or not isinstance(observed_at_ms, int):
            raise TypeError("observed_at_ms must be an integer")
        if observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        if self._last_observed_at_ms is not None and observed_at_ms < self._last_observed_at_ms:
            raise ValueError("monotonic observation time moved backwards")
        validation = validate_condition_ast(document)
        if not validation.valid:
            raise ValueError("cannot track an invalid condition AST")

        arguments = _stable_arguments(document["expression"])
        active_keys = {condition_expression_key(argument) for argument in arguments}
        next_states = {key: state for key, state in self._states.items() if key in active_keys}
        durations = {
            key: observed_at_ms - state.stable_since_ms
            for key, state in next_states.items()
            if state.truth is TruthValue.TRUE
        }
        truths: dict[str, TruthValue] = {}

        # Arguments are post-ordered, so an outer stable expression can consume
        # the freshly updated duration of a nested stable expression.
        for argument in arguments:
            key = condition_expression_key(argument)
            truth = evaluate_condition_expression(
                argument,
                facts,
                stable_durations_ms=durations,
            )
            previous = next_states.get(key)
            if previous is None or previous.truth is not truth:
                state = StableDurationState(key, truth, observed_at_ms)
            else:
                state = previous
            next_states[key] = state
            truths[key] = truth
            if truth is TruthValue.TRUE:
                durations[key] = observed_at_ms - state.stable_since_ms
            else:
                durations.pop(key, None)

        self._states = next_states
        self._last_observed_at_ms = observed_at_ms
        return StableDurationSnapshot(
            observed_at_ms=observed_at_ms,
            durations_ms=durations,
            truths=truths,
        )
