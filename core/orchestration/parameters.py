from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from jsonschema import Draft202012Validator


class ParameterType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    OBJECT = "object"
    ARRAY = "array"


class ParameterValueSource(StrEnum):
    ACTIVATION = "activation"
    DEFAULT = "default"
    PARENT_PARAMETER = "parent_parameter"
    LITERAL_BINDING = "literal_binding"


_MISSING = object()


@dataclass(frozen=True, slots=True)
class ParameterIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ParameterProvenance:
    source: ParameterValueSource
    source_path: str
    parent_parameter: str | None = None

    def to_document(self) -> dict[str, str]:
        document = {
            "source": self.source.value,
            "sourcePath": self.source_path,
        }
        if self.parent_parameter is not None:
            document["parentParameter"] = self.parent_parameter
        return document


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    name: str
    parameter_type: ParameterType
    required: bool
    description: str = ""
    default: object = _MISSING
    enum: tuple[object, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    items: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("parameter name must be a non-empty string")
        object.__setattr__(self, "parameter_type", ParameterType(self.parameter_type))
        if not isinstance(self.required, bool):
            raise ValueError("parameter required must be a boolean")
        if not isinstance(self.description, str):
            raise ValueError("parameter description must be a string")
        enum = tuple(self.enum)
        if self.parameter_type == ParameterType.ENUM:
            if not enum or len(enum) != len({_value_key(value) for value in enum}):
                raise ValueError("enum parameters require unique choices")
        elif enum:
            raise ValueError("enum choices are only valid for enum parameters")
        object.__setattr__(self, "enum", enum)
        numeric = self.parameter_type in {ParameterType.INTEGER, ParameterType.NUMBER}
        if (self.minimum is not None or self.maximum is not None) and not numeric:
            raise ValueError("minimum and maximum require a numeric parameter")
        for name, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"parameter {name} must be a finite number")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("parameter minimum cannot exceed maximum")
        length_compatible = self.parameter_type in {
            ParameterType.STRING,
            ParameterType.ARRAY,
        }
        if (self.min_length is not None or self.max_length is not None) and not length_compatible:
            raise ValueError("length constraints require a string or array parameter")
        for name, value in (("minLength", self.min_length), ("maxLength", self.max_length)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"parameter {name} must be a non-negative integer")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("parameter minLength cannot exceed maxLength")
        if self.items is not None:
            if self.parameter_type != ParameterType.ARRAY or not isinstance(self.items, Mapping):
                raise ValueError("items requires an array parameter and a JSON schema")
            Draft202012Validator.check_schema(dict(self.items))
        if self.default is not _MISSING:
            issues = self.validate_value(self.default, path="$.default")
            if issues:
                raise ValueError(f"invalid parameter default: {issues[0].message}")

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> "ParameterDefinition":
        if not isinstance(document, Mapping):
            raise ValueError("parameter definition must be an object")
        return cls(
            name=document.get("name"),
            parameter_type=document.get("type"),
            required=document.get("required"),
            description=document.get("description", ""),
            default=document.get("default", _MISSING),
            enum=tuple(document.get("enum", ())),
            minimum=document.get("minimum"),
            maximum=document.get("maximum"),
            min_length=document.get("minLength"),
            max_length=document.get("maxLength"),
            items=document.get("items"),
        )

    def validate_value(self, value: object, *, path: str) -> tuple[ParameterIssue, ...]:
        issues: list[ParameterIssue] = []
        type_matches = {
            ParameterType.STRING: lambda item: isinstance(item, str),
            ParameterType.INTEGER: lambda item: isinstance(item, int)
            and not isinstance(item, bool),
            ParameterType.NUMBER: lambda item: isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item),
            ParameterType.BOOLEAN: lambda item: isinstance(item, bool),
            ParameterType.ENUM: lambda item: any(item == choice for choice in self.enum),
            ParameterType.OBJECT: lambda item: isinstance(item, dict),
            ParameterType.ARRAY: lambda item: isinstance(item, list),
        }[self.parameter_type]
        if not type_matches(value):
            return (
                ParameterIssue(
                    path,
                    "type_mismatch",
                    f"Expected parameter type {self.parameter_type.value}.",
                ),
            )
        if self.minimum is not None and value < self.minimum:
            issues.append(
                ParameterIssue(path, "minimum", f"Value must be at least {self.minimum}.")
            )
        if self.maximum is not None and value > self.maximum:
            issues.append(ParameterIssue(path, "maximum", f"Value must be at most {self.maximum}."))
        if self.min_length is not None and len(value) < self.min_length:
            issues.append(
                ParameterIssue(
                    path,
                    "min_length",
                    f"Value length must be at least {self.min_length}.",
                )
            )
        if self.max_length is not None and len(value) > self.max_length:
            issues.append(
                ParameterIssue(
                    path,
                    "max_length",
                    f"Value length must be at most {self.max_length}.",
                )
            )
        if self.items is not None and isinstance(value, list):
            validator = Draft202012Validator({"type": "array", "items": dict(self.items)})
            for error in validator.iter_errors(value):
                item_path = path + "".join(f"[{part!r}]" for part in error.absolute_path)
                issues.append(ParameterIssue(item_path, f"items_{error.validator}", error.message))
        return tuple(issues)


def _value_key(value: object) -> str:
    return f"{type(value).__name__}:{value!r}"


@dataclass(frozen=True, slots=True)
class ParameterResolution:
    valid: bool
    values: Mapping[str, object]
    provenance: Mapping[str, ParameterProvenance]
    issues: tuple[ParameterIssue, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "values": deepcopy(dict(self.values)),
            "provenance": {
                name: provenance.to_document() for name, provenance in self.provenance.items()
            },
            "issues": [
                {"path": issue.path, "code": issue.code, "message": issue.message}
                for issue in self.issues
            ],
        }


def parse_parameter_definitions(
    document: Mapping[str, object],
) -> tuple[dict[str, ParameterDefinition], list[ParameterIssue]]:
    definitions: dict[str, ParameterDefinition] = {}
    issues: list[ParameterIssue] = []
    raw_definitions = document.get("parameters", [])
    if not isinstance(raw_definitions, list):
        return {}, [ParameterIssue("$.parameters", "invalid_definitions", "Expected an array.")]
    for index, raw in enumerate(raw_definitions):
        try:
            definition = ParameterDefinition.from_document(raw)
        except (TypeError, ValueError) as error:
            issues.append(
                ParameterIssue(
                    f"$.parameters[{index}]",
                    "invalid_definition",
                    str(error),
                )
            )
            continue
        if definition.name in definitions:
            issues.append(
                ParameterIssue(
                    f"$.parameters[{index}].name",
                    "duplicate_parameter",
                    f"Parameter {definition.name!r} is declared more than once.",
                )
            )
            continue
        definitions[definition.name] = definition
    return definitions, issues


def resolve_graph_parameters(
    graph_document: Mapping[str, object],
    activation_bindings: Mapping[str, object] | None = None,
) -> ParameterResolution:
    definitions, issues = parse_parameter_definitions(graph_document)
    bindings = {} if activation_bindings is None else activation_bindings
    if not isinstance(bindings, Mapping):
        issues.append(
            ParameterIssue("$.bindings", "invalid_bindings", "Bindings must be an object.")
        )
        bindings = {}
    unknown = sorted(set(bindings) - set(definitions))
    for name in unknown:
        issues.append(
            ParameterIssue(
                f"$.bindings[{name!r}]",
                "unknown_parameter",
                f"Parameter {name!r} is not declared.",
            )
        )
    values: dict[str, object] = {}
    provenance: dict[str, ParameterProvenance] = {}
    for name, definition in definitions.items():
        if name in bindings:
            value = bindings[name]
            source = ParameterValueSource.ACTIVATION
            source_path = f"$.bindings[{name!r}]"
        elif definition.has_default:
            value = deepcopy(definition.default)
            source = ParameterValueSource.DEFAULT
            source_path = f"$.parameters[{name!r}].default"
        elif definition.required:
            issues.append(
                ParameterIssue(
                    f"$.bindings[{name!r}]",
                    "required_parameter",
                    f"Required parameter {name!r} has no binding.",
                )
            )
            continue
        else:
            continue
        value_issues = definition.validate_value(value, path=source_path)
        issues.extend(value_issues)
        if not value_issues:
            values[name] = deepcopy(value)
            provenance[name] = ParameterProvenance(source, source_path)
    return ParameterResolution(
        valid=not issues,
        values=MappingProxyType(values),
        provenance=MappingProxyType(provenance),
        issues=tuple(issues),
    )


def resolve_subgraph_parameters(
    subgraph_document: Mapping[str, object],
    instance: Mapping[str, object],
    *,
    parent: ParameterResolution,
) -> ParameterResolution:
    definitions, issues = parse_parameter_definitions(subgraph_document)
    raw_bindings = instance.get("parameterBindings", {})
    if not isinstance(raw_bindings, Mapping):
        issues.append(
            ParameterIssue(
                "$.subgraph.parameterBindings",
                "invalid_bindings",
                "Subgraph bindings must be an object.",
            )
        )
        raw_bindings = {}
    for name in sorted(set(raw_bindings) - set(definitions)):
        issues.append(
            ParameterIssue(
                f"$.subgraph.parameterBindings[{name!r}]",
                "unknown_parameter",
                f"Subgraph parameter {name!r} is not declared.",
            )
        )
    values: dict[str, object] = {}
    provenance: dict[str, ParameterProvenance] = {}
    for name, definition in definitions.items():
        binding = raw_bindings.get(name, _MISSING)
        parent_name = None
        if isinstance(binding, Mapping) and set(binding) == {"parameter"}:
            parent_name = binding["parameter"]
            source_path = f"$.subgraph.parameterBindings[{name!r}].parameter"
            if not isinstance(parent_name, str) or parent_name not in parent.values:
                issues.append(
                    ParameterIssue(
                        source_path,
                        "unknown_parent_parameter",
                        f"Parent parameter {parent_name!r} has no resolved value.",
                    )
                )
                continue
            value = parent.values[parent_name]
            source = ParameterValueSource.PARENT_PARAMETER
        elif isinstance(binding, Mapping) and set(binding) == {"value"}:
            value = binding["value"]
            source = ParameterValueSource.LITERAL_BINDING
            source_path = f"$.subgraph.parameterBindings[{name!r}].value"
        elif binding is not _MISSING:
            issues.append(
                ParameterIssue(
                    f"$.subgraph.parameterBindings[{name!r}]",
                    "invalid_binding",
                    "Binding must contain exactly 'parameter' or 'value'.",
                )
            )
            continue
        elif definition.has_default:
            value = deepcopy(definition.default)
            source = ParameterValueSource.DEFAULT
            source_path = f"$.parameters[{name!r}].default"
        elif definition.required:
            issues.append(
                ParameterIssue(
                    f"$.subgraph.parameterBindings[{name!r}]",
                    "required_parameter",
                    f"Required subgraph parameter {name!r} has no binding.",
                )
            )
            continue
        else:
            continue
        value_issues = definition.validate_value(value, path=source_path)
        issues.extend(value_issues)
        if not value_issues:
            values[name] = deepcopy(value)
            provenance[name] = ParameterProvenance(
                source=source,
                source_path=source_path,
                parent_parameter=parent_name,
            )
    return ParameterResolution(
        valid=parent.valid and not issues,
        values=MappingProxyType(values),
        provenance=MappingProxyType(provenance),
        issues=tuple(issues),
    )
