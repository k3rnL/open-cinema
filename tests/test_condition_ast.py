import json

import pytest
from jsonschema import Draft202012Validator

from core.orchestration.condition_ast import (
    CONDITION_AST_VERSION,
    ConditionOperator,
    condition_ast_schema,
    validate_condition_ast,
)


def _document(expression):
    return {"version": CONDITION_AST_VERSION, "expression": expression}


@pytest.mark.parametrize(
    "expression",
    (
        {
            "op": "all",
            "args": [
                {"op": "exists", "fact": "endpoint.headset.availability"},
                {
                    "op": "not",
                    "arg": {
                        "op": "eq",
                        "fact": "processor.decoder.health",
                        "value": "failed",
                    },
                },
            ],
        },
        {
            "op": "any",
            "args": [
                {"op": "ne", "fact": "signal.input.codec", "value": "pcm"},
                {"op": "in", "fact": "mode.cinema", "values": [True, False]},
            ],
        },
        {"op": "lt", "fact": "parameter.volume", "value": 0.25},
        {"op": "lte", "fact": "parameter.volume", "value": 0.25},
        {"op": "gt", "fact": "parameter.volume", "value": 0.25},
        {"op": "gte", "fact": "parameter.volume", "value": 0.25},
        {
            "op": "not_in",
            "fact": "signal.input.codec",
            "values": ["ac3", "dts"],
        },
        {
            "op": "stable_for",
            "arg": {
                "op": "eq",
                "fact": "endpoint.headset.availability",
                "value": "route-available",
            },
            "durationMs": 750,
        },
    ),
)
def test_condition_v1_schema_accepts_every_expression_shape(expression) -> None:
    assert validate_condition_ast(_document(expression)).valid


def test_operator_vocabulary_is_complete_and_stable() -> None:
    assert {operator.value for operator in ConditionOperator} == {
        "all",
        "any",
        "not",
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "in",
        "not_in",
        "exists",
        "stable_for",
    }


def test_schema_is_valid_json_schema_and_round_trips() -> None:
    schema = condition_ast_schema()
    Draft202012Validator.check_schema(schema)

    encoded = json.dumps(schema, sort_keys=True)

    assert json.loads(encoded) == schema
    assert schema["properties"]["version"] == {"const": 1}


@pytest.mark.parametrize(
    ("document", "code"),
    (
        ({"version": 2, "expression": {"op": "exists", "fact": "mode.x"}}, "schema_const"),
        (_document({"op": "unknown", "fact": "mode.x"}), "schema_oneOf"),
        (_document({"op": "all", "args": []}), "schema_oneOf"),
        (_document({"op": "not"}), "schema_oneOf"),
        (_document({"op": "in", "fact": "mode.x", "values": []}), "schema_oneOf"),
        (
            _document(
                {
                    "op": "stable_for",
                    "arg": {"op": "exists", "fact": "mode.x"},
                    "durationMs": -1,
                }
            ),
            "schema_oneOf",
        ),
    ),
)
def test_condition_shape_rejections_have_stable_codes(document, code) -> None:
    result = validate_condition_ast(document)

    assert not result.valid
    assert any(issue.code == code for issue in result.issues)
