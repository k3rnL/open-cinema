from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

CONDITION_AST_VERSION = 1
CONDITION_AST_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "audio-condition-v1.schema.json"
)


class ConditionOperator(StrEnum):
    ALL = "all"
    ANY = "any"
    NOT = "not"
    EQUAL = "eq"
    NOT_EQUAL = "ne"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    STABLE_FOR = "stable_for"


@dataclass(frozen=True, slots=True)
class ConditionAstIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ConditionAstValidation:
    valid: bool
    issues: tuple[ConditionAstIssue, ...]


@lru_cache(maxsize=1)
def condition_ast_schema() -> dict[str, object]:
    schema = json.loads(CONDITION_AST_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def condition_ast_validator() -> Draft202012Validator:
    return Draft202012Validator(condition_ast_schema())


def _error_path(error) -> str:
    path = "$"
    for component in error.absolute_path:
        if isinstance(component, int):
            path += f"[{component}]"
        else:
            path += f".{component}"
    return path


def validate_condition_ast(
    document: Mapping[str, object],
) -> ConditionAstValidation:
    if not isinstance(document, Mapping):
        return ConditionAstValidation(
            False,
            (ConditionAstIssue("$", "schema_type", "Condition must be an object."),),
        )
    errors = sorted(
        condition_ast_validator().iter_errors(dict(document)),
        key=lambda error: (list(error.absolute_path), error.validator, error.message),
    )
    return ConditionAstValidation(
        not errors,
        tuple(
            ConditionAstIssue(
                path=_error_path(error),
                code=f"schema_{error.validator}",
                message=error.message,
            )
            for error in errors
        ),
    )
