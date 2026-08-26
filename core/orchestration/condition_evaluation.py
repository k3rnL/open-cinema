from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .condition_ast import ConditionOperator, validate_condition_ast


class TruthValue(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def negate(self) -> TruthValue:
        return {
            TruthValue.TRUE: TruthValue.FALSE,
            TruthValue.FALSE: TruthValue.TRUE,
            TruthValue.UNKNOWN: TruthValue.UNKNOWN,
        }[self]


class UnknownResult(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    WAITING = "waiting"
    ERROR = "error"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    WAITING = "waiting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    truth: TruthValue
    status: EligibilityStatus
    unknown_result: UnknownResult


@dataclass(frozen=True, slots=True)
class ConditionExplanation:
    path: str
    operator: ConditionOperator
    truth: TruthValue
    reason: str
    fact: str | None = None
    fact_present: bool | None = None
    actual: object = None
    expected: object = None
    expected_values: tuple[object, ...] = ()
    duration_ms: int | None = None
    observed_duration_ms: int | None = None
    children: tuple[ConditionExplanation, ...] = ()

    def to_document(self) -> dict[str, object]:
        return {
            "path": self.path,
            "operator": self.operator.value,
            "truth": self.truth.value,
            "reason": self.reason,
            "fact": self.fact,
            "factPresent": self.fact_present,
            "actual": self.actual,
            "expected": self.expected,
            "expectedValues": list(self.expected_values),
            "durationMs": self.duration_ms,
            "observedDurationMs": self.observed_duration_ms,
            "children": [child.to_document() for child in self.children],
        }


def _same(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _number(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def condition_expression_key(expression: Mapping[str, object]) -> str:
    """Return a stable identity for duration observations of one expression."""

    encoded = json.dumps(
        expression,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _group_all(values: tuple[TruthValue, ...]) -> TruthValue:
    if TruthValue.FALSE in values:
        return TruthValue.FALSE
    if TruthValue.UNKNOWN in values:
        return TruthValue.UNKNOWN
    return TruthValue.TRUE


def _group_any(values: tuple[TruthValue, ...]) -> TruthValue:
    if TruthValue.TRUE in values:
        return TruthValue.TRUE
    if TruthValue.UNKNOWN in values:
        return TruthValue.UNKNOWN
    return TruthValue.FALSE


def evaluate_condition_expression(
    expression: Mapping[str, object],
    facts: Mapping[str, object],
    *,
    stable_durations_ms: Mapping[str, int] | None = None,
) -> TruthValue:
    """Evaluate a schema-valid expression without I/O or hidden state."""

    operator = ConditionOperator(expression["op"])
    durations = stable_durations_ms or {}
    if operator in {ConditionOperator.ALL, ConditionOperator.ANY}:
        values = tuple(
            evaluate_condition_expression(
                argument,
                facts,
                stable_durations_ms=durations,
            )
            for argument in expression["args"]
        )
        return _group_all(values) if operator is ConditionOperator.ALL else _group_any(values)
    if operator is ConditionOperator.NOT:
        return evaluate_condition_expression(
            expression["arg"],
            facts,
            stable_durations_ms=durations,
        ).negate()
    if operator is ConditionOperator.EXISTS:
        return TruthValue.TRUE if expression["fact"] in facts else TruthValue.FALSE
    if operator is ConditionOperator.STABLE_FOR:
        argument = expression["arg"]
        current = evaluate_condition_expression(
            argument,
            facts,
            stable_durations_ms=durations,
        )
        if current is not TruthValue.TRUE:
            return current
        observed_duration = durations.get(condition_expression_key(argument))
        if observed_duration is None:
            return TruthValue.UNKNOWN
        return (
            TruthValue.TRUE if observed_duration >= expression["durationMs"] else TruthValue.FALSE
        )

    fact_path = expression["fact"]
    if fact_path not in facts:
        return TruthValue.UNKNOWN
    actual = facts[fact_path]
    if operator in {ConditionOperator.EQUAL, ConditionOperator.NOT_EQUAL}:
        equal = _same(actual, expression["value"])
        if operator is ConditionOperator.NOT_EQUAL:
            equal = not equal
        return TruthValue.TRUE if equal else TruthValue.FALSE
    if operator in {
        ConditionOperator.LESS_THAN,
        ConditionOperator.LESS_THAN_OR_EQUAL,
        ConditionOperator.GREATER_THAN,
        ConditionOperator.GREATER_THAN_OR_EQUAL,
    }:
        left = _number(actual)
        right = _number(expression["value"])
        if left is None or right is None:
            return TruthValue.UNKNOWN
        result = {
            ConditionOperator.LESS_THAN: left < right,
            ConditionOperator.LESS_THAN_OR_EQUAL: left <= right,
            ConditionOperator.GREATER_THAN: left > right,
            ConditionOperator.GREATER_THAN_OR_EQUAL: left >= right,
        }[operator]
        return TruthValue.TRUE if result else TruthValue.FALSE
    if operator in {ConditionOperator.IN, ConditionOperator.NOT_IN}:
        contained = any(_same(actual, expected) for expected in expression["values"])
        if operator is ConditionOperator.NOT_IN:
            contained = not contained
        return TruthValue.TRUE if contained else TruthValue.FALSE
    raise AssertionError(f"unhandled condition operator: {operator}")


def evaluate_condition_ast(
    document: Mapping[str, object],
    facts: Mapping[str, object],
    *,
    stable_durations_ms: Mapping[str, int] | None = None,
) -> TruthValue:
    validation = validate_condition_ast(document)
    if not validation.valid:
        summary = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"invalid condition AST: {summary}")
    return evaluate_condition_expression(
        document["expression"],
        facts,
        stable_durations_ms=stable_durations_ms,
    )


def evaluate_eligibility(
    document: Mapping[str, object],
    facts: Mapping[str, object],
    *,
    unknown_result: UnknownResult | str,
    stable_durations_ms: Mapping[str, int] | None = None,
) -> EligibilityDecision:
    """Resolve truth into eligibility; the unknown policy is intentionally required."""

    try:
        policy = UnknownResult(unknown_result)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "unknown_result must be eligible, ineligible, waiting, or error"
        ) from error
    truth = evaluate_condition_ast(
        document,
        facts,
        stable_durations_ms=stable_durations_ms,
    )
    if truth is TruthValue.TRUE:
        status = EligibilityStatus.ELIGIBLE
    elif truth is TruthValue.FALSE:
        status = EligibilityStatus.INELIGIBLE
    else:
        status = EligibilityStatus(policy.value)
    return EligibilityDecision(truth, status, policy)


def _explanation_reason(
    operator: ConditionOperator,
    truth: TruthValue,
    *,
    fact_present: bool | None = None,
    observed_duration_ms: int | None = None,
) -> str:
    if fact_present is False and operator is not ConditionOperator.EXISTS:
        return "fact_missing"
    if operator is ConditionOperator.EXISTS:
        return "fact_exists" if truth is TruthValue.TRUE else "fact_missing"
    if operator in {ConditionOperator.ALL, ConditionOperator.ANY}:
        return f"{operator.value}_{truth.value}"
    if operator is ConditionOperator.NOT:
        return f"negated_to_{truth.value}"
    if operator is ConditionOperator.STABLE_FOR:
        if truth is TruthValue.UNKNOWN:
            return "duration_unobserved"
        if truth is TruthValue.TRUE:
            return "duration_satisfied"
        return "argument_not_true" if observed_duration_ms is None else "duration_pending"
    if truth is TruthValue.UNKNOWN:
        return "invalid_observed_value"
    return f"{operator.value}_{truth.value}"


def _explain_expression(
    expression: Mapping[str, object],
    facts: Mapping[str, object],
    durations: Mapping[str, int],
    path: str,
) -> ConditionExplanation:
    operator = ConditionOperator(expression["op"])
    children: tuple[ConditionExplanation, ...] = ()
    fact = expression.get("fact")
    fact_present = fact in facts if isinstance(fact, str) else None
    actual = facts.get(fact) if fact_present else None
    expected = expression.get("value")
    expected_values = tuple(expression.get("values", ()))
    duration_ms = expression.get("durationMs")
    observed_duration_ms = None

    if operator in {ConditionOperator.ALL, ConditionOperator.ANY}:
        children = tuple(
            _explain_expression(argument, facts, durations, f"{path}.args[{index}]")
            for index, argument in enumerate(expression["args"])
        )
    elif operator in {ConditionOperator.NOT, ConditionOperator.STABLE_FOR}:
        argument = expression["arg"]
        children = (_explain_expression(argument, facts, durations, f"{path}.arg"),)
        if operator is ConditionOperator.STABLE_FOR:
            observed_duration_ms = durations.get(condition_expression_key(argument))

    truth = evaluate_condition_expression(
        expression,
        facts,
        stable_durations_ms=durations,
    )
    return ConditionExplanation(
        path=path,
        operator=operator,
        truth=truth,
        reason=_explanation_reason(
            operator,
            truth,
            fact_present=fact_present,
            observed_duration_ms=observed_duration_ms,
        ),
        fact=fact if isinstance(fact, str) else None,
        fact_present=fact_present,
        actual=actual,
        expected=expected,
        expected_values=expected_values,
        duration_ms=duration_ms if isinstance(duration_ms, int) else None,
        observed_duration_ms=observed_duration_ms,
        children=children,
    )


def explain_condition_ast(
    document: Mapping[str, object],
    facts: Mapping[str, object],
    *,
    stable_durations_ms: Mapping[str, int] | None = None,
) -> ConditionExplanation:
    validation = validate_condition_ast(document)
    if not validation.valid:
        summary = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"invalid condition AST: {summary}")
    return _explain_expression(
        document["expression"],
        facts,
        stable_durations_ms or {},
        "$.expression",
    )
