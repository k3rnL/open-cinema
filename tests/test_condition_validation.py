import pytest

from core.orchestration.condition_validation import (
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_DOCUMENT_BYTES,
    MAX_CONDITION_NODES,
    validate_condition_document,
)
from core.orchestration.fact_catalogue import core_fact_catalogue


def _document(expression):
    return {"version": 1, "expression": expression}


def _codes(result):
    return {(issue.path, issue.code) for issue in result.issues}


def test_valid_condition_uses_graph_refined_fact_types() -> None:
    catalogue = core_fact_catalogue().with_graph_parameters(
        (
            {"name": "volume", "type": "number", "required": True},
            {
                "name": "profile",
                "type": "enum",
                "required": True,
                "enum": ["cinema", "music"],
            },
        )
    )
    result = validate_condition_document(
        _document(
            {
                "op": "all",
                "args": [
                    {"op": "gte", "fact": "parameter.volume", "value": 0.5},
                    {
                        "op": "in",
                        "fact": "parameter.profile",
                        "values": ["cinema", "music"],
                    },
                    {"op": "exists", "fact": "endpoint.headset.availability"},
                ],
            }
        ),
        catalogue=catalogue,
    )

    assert result.valid
    assert result.node_count == 4
    assert result.maximum_depth == 2


@pytest.mark.parametrize(
    ("expression", "path", "code"),
    (
        ({"op": "shell", "fact": "mode.cinema"}, "$.expression.op", "unknown_operator"),
        (
            {"op": "exists", "fact": "endpoint.*.availability"},
            "$.expression.fact",
            "unsafe_fact_pattern",
        ),
        (
            {"op": "exists", "fact": "endpoint.a/../secret.availability"},
            "$.expression.fact",
            "unsafe_fact_path",
        ),
        (
            {"op": "exists", "fact": "runtime.node.42"},
            "$.expression.fact",
            "unknown_fact",
        ),
        (
            {"op": "gt", "fact": "processor.decoder.health", "value": 1},
            "$.expression.fact",
            "numeric_fact_required",
        ),
        (
            {"op": "gt", "fact": "endpoint.headset.volume", "value": "loud"},
            "$.expression.value",
            "numeric_value_required",
        ),
        (
            {"op": "eq", "fact": "endpoint.headset.mute", "value": "false"},
            "$.expression.value",
            "fact_value_type_mismatch",
        ),
        (
            {
                "op": "in",
                "fact": "endpoint.headset.direction",
                "values": ["output", "sideways"],
            },
            "$.expression.values[1]",
            "fact_value_type_mismatch",
        ),
    ),
)
def test_semantic_rejections_have_field_level_paths(expression, path, code) -> None:
    result = validate_condition_document(_document(expression))

    assert not result.valid
    assert (path, code) in _codes(result)


def test_malformed_fields_are_reported_at_their_locations() -> None:
    result = validate_condition_document(
        {
            "version": 1,
            "expression": {"op": "all", "args": "not-an-array", "value": True},
            "script": "return true",
        }
    )

    assert ("$.expression.args", "invalid_arguments") in _codes(result)
    assert ("$.expression.value", "unknown_field") in _codes(result)
    assert ("$.script", "unknown_field") in _codes(result)


def test_excessive_nesting_is_bounded() -> None:
    expression = {"op": "exists", "fact": "mode.cinema"}
    for _ in range(MAX_CONDITION_DEPTH):
        expression = {"op": "not", "arg": expression}

    result = validate_condition_document(_document(expression))

    assert not result.valid
    assert any(issue.code == "depth_limit_exceeded" for issue in result.issues)
    assert result.maximum_depth == MAX_CONDITION_DEPTH + 1


def test_expression_node_count_is_bounded() -> None:
    leaf = {"op": "exists", "fact": "mode.cinema"}
    expression = {
        "op": "all",
        "args": [
            {"op": "any", "args": [leaf for _ in range(32)]}
            for _ in range(5)
        ],
    }

    result = validate_condition_document(_document(expression))

    assert not result.valid
    assert result.node_count == MAX_CONDITION_NODES + 1
    assert any(issue.code == "node_limit_exceeded" for issue in result.issues)


def test_oversized_document_is_rejected_without_unbounded_diagnostics() -> None:
    result = validate_condition_document(
        _document(
            {
                "op": "eq",
                "fact": "mode.cinema",
                "value": "x" * MAX_CONDITION_DOCUMENT_BYTES,
            }
        )
    )

    assert not result.valid
    assert result.document_bytes > MAX_CONDITION_DOCUMENT_BYTES
    assert any(issue.code == "document_size_exceeded" for issue in result.issues)
    assert len(result.issues) <= 2


def test_duplicate_membership_values_and_non_json_numbers_are_rejected() -> None:
    duplicate = validate_condition_document(
        _document(
            {
                "op": "in",
                "fact": "endpoint.headset.direction",
                "values": ["output", "output"],
            }
        )
    )
    non_json = validate_condition_document(
        _document({"op": "eq", "fact": "endpoint.headset.volume", "value": float("nan")})
    )

    assert any(issue.code == "duplicate_membership_value" for issue in duplicate.issues)
    assert any(issue.code == "invalid_json" for issue in non_json.issues)
