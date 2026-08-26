from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

from django.conf import settings

from .condition_ast import CONDITION_AST_VERSION, ConditionOperator
from .fact_catalogue import (
    FactCatalogue,
    FactDefinition,
    FactValueType,
    core_fact_catalogue,
)

MAX_CONDITION_DEPTH = 16
MAX_CONDITION_NODES = 128
MAX_CONDITION_GROUP_ARGUMENTS = 32
MAX_CONDITION_MEMBERSHIP_VALUES = 64
MAX_CONDITION_DOCUMENT_BYTES = 32_768


@dataclass(frozen=True, slots=True)
class ConditionValidationLimits:
    max_depth: int
    max_nodes: int
    max_group_arguments: int
    max_membership_values: int
    max_document_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "max_depth",
            "max_nodes",
            "max_group_arguments",
            "max_membership_values",
            "max_document_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_settings(cls) -> "ConditionValidationLimits":
        values = settings.AUDIO_CONDITION_VALIDATION_LIMITS
        expected = {
            "max_depth",
            "max_nodes",
            "max_group_arguments",
            "max_membership_values",
            "max_document_bytes",
        }
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError(
                "AUDIO_CONDITION_VALIDATION_LIMITS must define exactly "
                f"{', '.join(sorted(expected))}"
            )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ConditionValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ConditionValidationResult:
    valid: bool
    issues: tuple[ConditionValidationIssue, ...]
    node_count: int
    maximum_depth: int
    document_bytes: int


@dataclass(slots=True)
class _ValidationState:
    catalogue: FactCatalogue
    limits: ConditionValidationLimits
    issues: list[ConditionValidationIssue]
    node_count: int = 0
    maximum_depth: int = 0
    node_limit_reported: bool = False

    def issue(self, path: str, code: str, message: str) -> None:
        self.issues.append(ConditionValidationIssue(path, code, message))


_OPERATORS = {operator.value: operator for operator in ConditionOperator}
_GROUP_OPERATORS = {ConditionOperator.ALL, ConditionOperator.ANY}
_COMPARISON_OPERATORS = {
    ConditionOperator.EQUAL,
    ConditionOperator.NOT_EQUAL,
    ConditionOperator.LESS_THAN,
    ConditionOperator.LESS_THAN_OR_EQUAL,
    ConditionOperator.GREATER_THAN,
    ConditionOperator.GREATER_THAN_OR_EQUAL,
}
_NUMERIC_OPERATORS = {
    ConditionOperator.LESS_THAN,
    ConditionOperator.LESS_THAN_OR_EQUAL,
    ConditionOperator.GREATER_THAN,
    ConditionOperator.GREATER_THAN_OR_EQUAL,
}
_MEMBERSHIP_OPERATORS = {ConditionOperator.IN, ConditionOperator.NOT_IN}


def _number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _value_matches(definition: FactDefinition, value: object) -> bool:
    if value is None:
        return definition.nullable
    value_type = definition.value_type
    if value_type is FactValueType.JSON:
        return True
    if value_type is FactValueType.BOOLEAN:
        return isinstance(value, bool)
    if value_type is FactValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type is FactValueType.NUMBER:
        return _number(value)
    if value_type is FactValueType.STRING:
        return isinstance(value, str)
    if value_type is FactValueType.ENUM:
        return any(
            type(value) is type(option) and value == option for option in definition.enum_values
        )
    if value_type is FactValueType.OBJECT:
        return isinstance(value, Mapping)
    if value_type is FactValueType.ARRAY:
        return isinstance(value, list)
    raise AssertionError(f"unhandled fact value type: {value_type}")


def _fact_definition(
    state: _ValidationState,
    value: object,
    path: str,
) -> FactDefinition | None:
    if not isinstance(value, str) or not value:
        state.issue(path, "invalid_fact_path", "Fact path must be a non-empty string.")
        return None
    if any(token in value for token in ("*", "?", "[", "]", "\\")):
        state.issue(
            path,
            "unsafe_fact_pattern",
            "Fact paths cannot contain glob or regular-expression syntax.",
        )
        return None
    if any(ord(character) < 32 or character.isspace() for character in value):
        state.issue(path, "unsafe_fact_path", "Fact path contains whitespace or control data.")
        return None
    if any(part == ".." for part in value.split("/")):
        state.issue(path, "unsafe_fact_path", "Fact path cannot contain parent traversal.")
        return None
    resolved = state.catalogue.resolve(value)
    if resolved is None:
        state.issue(path, "unknown_fact", f"Fact {value!r} is not in the catalogue.")
        return None
    return resolved.definition


def _unknown_fields(
    state: _ValidationState,
    expression: Mapping[str, object],
    path: str,
    allowed: set[str],
) -> None:
    for field in sorted(set(expression) - allowed):
        state.issue(
            f"{path}.{field}",
            "unknown_field",
            f"Field {field!r} is not valid for this operator.",
        )


def _walk_expression(
    state: _ValidationState,
    expression: object,
    path: str,
    depth: int,
) -> None:
    if state.node_limit_reported:
        return
    state.node_count += 1
    state.maximum_depth = max(state.maximum_depth, depth)
    if state.node_count > state.limits.max_nodes:
        if not state.node_limit_reported:
            state.issue(
                path,
                "node_limit_exceeded",
                f"Condition contains more than {state.limits.max_nodes} expressions.",
            )
            state.node_limit_reported = True
        return
    if depth > state.limits.max_depth:
        state.issue(
            path,
            "depth_limit_exceeded",
            f"Condition nesting exceeds {state.limits.max_depth} levels.",
        )
        return
    if not isinstance(expression, Mapping):
        state.issue(path, "invalid_expression", "Expression must be an object.")
        return

    raw_operator = expression.get("op")
    if not isinstance(raw_operator, str):
        state.issue(f"{path}.op", "missing_operator", "Expression needs an operator.")
        return
    operator = _OPERATORS.get(raw_operator)
    if operator is None:
        state.issue(
            f"{path}.op",
            "unknown_operator",
            f"Unknown condition operator {raw_operator!r}.",
        )
        return

    if operator in _GROUP_OPERATORS:
        _unknown_fields(state, expression, path, {"op", "args"})
        arguments = expression.get("args")
        if not isinstance(arguments, list) or not arguments:
            state.issue(
                f"{path}.args",
                "invalid_arguments",
                "Boolean groups require a non-empty argument array.",
            )
            return
        if len(arguments) > state.limits.max_group_arguments:
            state.issue(
                f"{path}.args",
                "group_width_exceeded",
                "Boolean groups allow at most "
                f"{state.limits.max_group_arguments} arguments.",
            )
        for index, argument in enumerate(arguments[: state.limits.max_group_arguments]):
            _walk_expression(state, argument, f"{path}.args[{index}]", depth + 1)
        return

    if operator is ConditionOperator.NOT:
        _unknown_fields(state, expression, path, {"op", "arg"})
        if "arg" not in expression:
            state.issue(f"{path}.arg", "missing_argument", "Not requires one argument.")
            return
        _walk_expression(state, expression["arg"], f"{path}.arg", depth + 1)
        return

    if operator is ConditionOperator.STABLE_FOR:
        _unknown_fields(state, expression, path, {"op", "arg", "durationMs"})
        duration = expression.get("durationMs")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            state.issue(
                f"{path}.durationMs",
                "invalid_duration",
                "durationMs must be a non-negative integer.",
            )
        if "arg" not in expression:
            state.issue(f"{path}.arg", "missing_argument", "stable_for requires an argument.")
            return
        _walk_expression(state, expression["arg"], f"{path}.arg", depth + 1)
        return

    if operator is ConditionOperator.EXISTS:
        _unknown_fields(state, expression, path, {"op", "fact"})
        _fact_definition(state, expression.get("fact"), f"{path}.fact")
        return

    if operator in _COMPARISON_OPERATORS:
        _unknown_fields(state, expression, path, {"op", "fact", "value"})
        definition = _fact_definition(state, expression.get("fact"), f"{path}.fact")
        if "value" not in expression:
            state.issue(f"{path}.value", "missing_value", "Comparison requires a value.")
            return
        value = expression["value"]
        if operator in _NUMERIC_OPERATORS:
            if definition is not None and definition.value_type not in {
                FactValueType.INTEGER,
                FactValueType.NUMBER,
            }:
                state.issue(
                    f"{path}.fact",
                    "numeric_fact_required",
                    "Numeric comparison requires an integer or number fact.",
                )
            if not _number(value):
                state.issue(
                    f"{path}.value",
                    "numeric_value_required",
                    "Numeric comparison requires a finite numeric value.",
                )
        elif definition is not None and not _value_matches(definition, value):
            state.issue(
                f"{path}.value",
                "fact_value_type_mismatch",
                f"Value does not match {definition.path_pattern} "
                f"({definition.value_type.value}).",
            )
        return

    if operator in _MEMBERSHIP_OPERATORS:
        _unknown_fields(state, expression, path, {"op", "fact", "values"})
        definition = _fact_definition(state, expression.get("fact"), f"{path}.fact")
        values = expression.get("values")
        if not isinstance(values, list) or not values:
            state.issue(
                f"{path}.values",
                "invalid_membership_values",
                "Membership requires a non-empty values array.",
            )
            return
        if len(values) > state.limits.max_membership_values:
            state.issue(
                f"{path}.values",
                "membership_limit_exceeded",
                "Membership allows at most "
                f"{state.limits.max_membership_values} values.",
            )
        seen: set[str] = set()
        for index, value in enumerate(values[: state.limits.max_membership_values]):
            try:
                identity = json.dumps(value, allow_nan=False, sort_keys=True)
            except (TypeError, ValueError):
                identity = f"invalid:{index}"
            if identity in seen:
                state.issue(
                    f"{path}.values[{index}]",
                    "duplicate_membership_value",
                    "Membership values must be unique.",
                )
            seen.add(identity)
            if definition is not None and not _value_matches(definition, value):
                state.issue(
                    f"{path}.values[{index}]",
                    "fact_value_type_mismatch",
                    f"Value does not match {definition.path_pattern} "
                    f"({definition.value_type.value}).",
                )
        return

    raise AssertionError(f"unhandled condition operator: {operator}")


def validate_condition_document(
    document: Mapping[str, object],
    *,
    catalogue: FactCatalogue | None = None,
    limits: ConditionValidationLimits | None = None,
) -> ConditionValidationResult:
    limits = limits or ConditionValidationLimits.from_settings()
    issues: list[ConditionValidationIssue] = []
    if not isinstance(document, Mapping):
        return ConditionValidationResult(
            False,
            (ConditionValidationIssue("$", "invalid_document", "Condition must be an object."),),
            0,
            0,
            0,
        )
    try:
        document_bytes = len(
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as error:
        issues.append(ConditionValidationIssue("$", "invalid_json", str(error)))
        document_bytes = 0
    if document_bytes > limits.max_document_bytes:
        issues.append(
            ConditionValidationIssue(
                "$",
                "document_size_exceeded",
                f"Condition uses {document_bytes} bytes; limit is "
                f"{limits.max_document_bytes}.",
            )
        )
    for field in sorted(set(document) - {"version", "expression"}):
        issues.append(
            ConditionValidationIssue(
                f"$.{field}", "unknown_field", f"Unknown condition field {field!r}."
            )
        )
    if document.get("version") != CONDITION_AST_VERSION:
        issues.append(
            ConditionValidationIssue(
                "$.version",
                "unsupported_version",
                f"Condition version must be {CONDITION_AST_VERSION}.",
            )
        )
    state = _ValidationState(catalogue or core_fact_catalogue(), limits, issues)
    if "expression" not in document:
        issues.append(
            ConditionValidationIssue(
                "$.expression", "missing_expression", "Condition needs an expression."
            )
        )
    else:
        _walk_expression(state, document["expression"], "$.expression", 1)
    ordered = tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))
    return ConditionValidationResult(
        valid=not ordered,
        issues=ordered,
        node_count=state.node_count,
        maximum_depth=state.maximum_depth,
        document_bytes=document_bytes,
    )
