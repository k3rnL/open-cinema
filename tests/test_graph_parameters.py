import pytest

from core.orchestration.parameters import (
    ParameterDefinition,
    ParameterType,
    ParameterValueSource,
    resolve_graph_parameters,
    resolve_subgraph_parameters,
)


def _graph_parameters():
    return {
        "parameters": [
            {
                "name": "gain",
                "type": "number",
                "required": False,
                "default": 0.75,
                "minimum": 0.0,
                "maximum": 1.0,
            },
            {
                "name": "profile",
                "type": "enum",
                "required": True,
                "enum": ["music", "cinema"],
            },
            {
                "name": "labels",
                "type": "array",
                "required": False,
                "default": ["room"],
                "minLength": 1,
                "items": {"type": "string", "minLength": 1},
            },
        ]
    }


def test_graph_defaults_overrides_constraints_and_provenance() -> None:
    result = resolve_graph_parameters(
        _graph_parameters(),
        {"profile": "cinema", "gain": 0.5},
    )

    assert result.valid is True
    assert dict(result.values) == {
        "gain": 0.5,
        "profile": "cinema",
        "labels": ["room"],
    }
    assert result.provenance["gain"].source == ParameterValueSource.ACTIVATION
    assert result.provenance["labels"].source == ParameterValueSource.DEFAULT


def test_missing_unknown_and_invalid_graph_bindings_are_explained() -> None:
    result = resolve_graph_parameters(
        _graph_parameters(),
        {"gain": 2.0, "unknown": True},
    )

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {
        "maximum",
        "required_parameter",
        "unknown_parameter",
    }
    assert "gain" not in result.values


def test_subgraph_bindings_keep_parent_literal_and_default_provenance() -> None:
    parent = resolve_graph_parameters(
        _graph_parameters(),
        {"profile": "music", "gain": 0.4},
    )
    subgraph = {
        "parameters": [
            {"name": "volume", "type": "number", "required": True},
            {"name": "mode", "type": "enum", "required": True, "enum": ["a", "b"]},
            {"name": "enabled", "type": "boolean", "required": False, "default": True},
        ]
    }
    instance = {
        "parameterBindings": {
            "volume": {"parameter": "gain"},
            "mode": {"value": "b"},
        }
    }

    result = resolve_subgraph_parameters(subgraph, instance, parent=parent)

    assert result.valid is True
    assert dict(result.values) == {"volume": 0.4, "mode": "b", "enabled": True}
    assert result.provenance["volume"].source == ParameterValueSource.PARENT_PARAMETER
    assert result.provenance["volume"].parent_parameter == "gain"
    assert result.provenance["mode"].source == ParameterValueSource.LITERAL_BINDING
    assert result.provenance["enabled"].source == ParameterValueSource.DEFAULT


def test_subgraph_rejects_missing_parent_and_malformed_binding() -> None:
    parent = resolve_graph_parameters(_graph_parameters(), {"profile": "cinema"})
    subgraph = {
        "parameters": [
            {"name": "volume", "type": "number", "required": True},
            {"name": "mode", "type": "string", "required": True},
        ]
    }

    result = resolve_subgraph_parameters(
        subgraph,
        {
            "parameterBindings": {
                "volume": {"parameter": "missing"},
                "mode": {"value": "cinema", "parameter": "profile"},
            }
        },
        parent=parent,
    )

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {
        "unknown_parent_parameter",
        "invalid_binding",
    }


@pytest.mark.parametrize(
    "definition",
    (
        {"name": "bad", "type": "string", "required": False, "minimum": 0},
        {"name": "bad", "type": "enum", "required": False, "enum": []},
        {
            "name": "bad",
            "type": "integer",
            "required": False,
            "default": True,
        },
        {
            "name": "bad",
            "type": "array",
            "required": False,
            "minLength": 4,
            "maxLength": 2,
        },
    ),
)
def test_invalid_parameter_definitions_are_rejected(definition) -> None:
    with pytest.raises(ValueError):
        ParameterDefinition.from_document(definition)


def test_parameter_resolution_mappings_are_read_only() -> None:
    result = resolve_graph_parameters(_graph_parameters(), {"profile": "music"})

    with pytest.raises(TypeError):
        result.values["gain"] = 1
