from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

FACT_CATALOGUE_VERSION = 1
MAX_FACT_PATH_LENGTH = 512
_BINDING_VALUE = r"[A-Za-z0-9][A-Za-z0-9:_./-]{0,254}"
_PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")


class FactNamespace(StrEnum):
    ENDPOINT = "endpoint"
    SIGNAL = "signal"
    PROCESSOR = "processor"
    PARAMETER = "parameter"
    MODE = "mode"
    RESOURCE = "resource"
    OVERRIDE = "override"


class FactValueType(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    ENUM = "enum"
    OBJECT = "object"
    ARRAY = "array"
    JSON = "json"


_JSON_SCHEMA_TYPES = {
    FactValueType.BOOLEAN: "boolean",
    FactValueType.INTEGER: "integer",
    FactValueType.NUMBER: "number",
    FactValueType.STRING: "string",
    FactValueType.OBJECT: "object",
    FactValueType.ARRAY: "array",
}


@dataclass(frozen=True, slots=True)
class FactDefinition:
    path_pattern: str
    namespace: FactNamespace
    value_type: FactValueType
    description: str
    nullable: bool = False
    enum_values: tuple[object, ...] = ()
    supports_stable_duration: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", FactNamespace(self.namespace))
        object.__setattr__(self, "value_type", FactValueType(self.value_type))
        if not self.path_pattern.startswith(f"{self.namespace.value}."):
            raise ValueError("fact pattern must begin with its namespace")
        if len(self.path_pattern) > MAX_FACT_PATH_LENGTH:
            raise ValueError("fact pattern is too long")
        if not self.description:
            raise ValueError("fact description must not be empty")
        placeholders = _PLACEHOLDER.findall(self.path_pattern)
        if len(placeholders) != len(set(placeholders)):
            raise ValueError("fact pattern placeholders must be unique")
        remainder = _PLACEHOLDER.sub("binding", self.path_pattern)
        if "{" in remainder or "}" in remainder:
            raise ValueError("fact pattern contains an invalid placeholder")
        if self.value_type is FactValueType.ENUM and not self.enum_values:
            raise ValueError("enum facts must declare enum_values")
        if self.value_type is not FactValueType.ENUM and self.enum_values:
            raise ValueError("only enum facts may declare enum_values")

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(_PLACEHOLDER.findall(self.path_pattern))

    @property
    def specificity(self) -> int:
        return len(_PLACEHOLDER.sub("", self.path_pattern))

    def _regex(self) -> re.Pattern[str]:
        fragments: list[str] = []
        position = 0
        for match in _PLACEHOLDER.finditer(self.path_pattern):
            fragments.append(re.escape(self.path_pattern[position : match.start()]))
            fragments.append(f"(?P<{match.group(1)}>{_BINDING_VALUE})")
            position = match.end()
        fragments.append(re.escape(self.path_pattern[position:]))
        return re.compile("^" + "".join(fragments) + "$")

    def match(self, path: str) -> Mapping[str, str] | None:
        if not isinstance(path, str) or not path or len(path) > MAX_FACT_PATH_LENGTH:
            return None
        matched = self._regex().fullmatch(path)
        return None if matched is None else matched.groupdict()

    def value_schema(self) -> dict[str, object]:
        if self.value_type is FactValueType.JSON:
            schema: dict[str, object] = {}
        elif self.value_type is FactValueType.ENUM:
            schema = {"enum": list(self.enum_values)}
            if all(isinstance(value, str) for value in self.enum_values):
                schema["type"] = "string"
        else:
            schema = {"type": _JSON_SCHEMA_TYPES[self.value_type]}
        if self.nullable:
            return {"anyOf": [schema, {"type": "null"}]}
        return schema

    def to_document(self) -> dict[str, object]:
        return {
            "pathPattern": self.path_pattern,
            "namespace": self.namespace.value,
            "valueType": self.value_type.value,
            "nullable": self.nullable,
            "schema": self.value_schema(),
            "supportsStableDuration": self.supports_stable_duration,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class ResolvedFactDefinition:
    path: str
    definition: FactDefinition
    bindings: Mapping[str, str]


class FactCatalogue:
    def __init__(self, definitions: Iterable[FactDefinition] = ()) -> None:
        self._definitions: dict[str, FactDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: FactDefinition) -> None:
        if not isinstance(definition, FactDefinition):
            raise TypeError("definition must be a FactDefinition")
        if definition.path_pattern in self._definitions:
            raise ValueError(f"fact pattern already registered: {definition.path_pattern}")
        self._definitions[definition.path_pattern] = definition

    def definitions(self) -> tuple[FactDefinition, ...]:
        return tuple(
            sorted(
                self._definitions.values(),
                key=lambda item: (item.namespace.value, item.path_pattern),
            )
        )

    def resolve(self, path: str) -> ResolvedFactDefinition | None:
        matches = []
        for definition in self._definitions.values():
            bindings = definition.match(path)
            if bindings is not None:
                matches.append((definition.specificity, definition, bindings))
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[0], item[1].path_pattern))
        _, definition, bindings = matches[0]
        return ResolvedFactDefinition(path, definition, bindings)

    def with_graph_parameters(
        self,
        parameters: Iterable[Mapping[str, object]],
    ) -> FactCatalogue:
        result = FactCatalogue(self.definitions())
        for parameter in parameters:
            name = parameter.get("name")
            value_type = parameter.get("type")
            if not isinstance(name, str) or not name:
                raise ValueError("graph parameter needs a non-empty name")
            try:
                fact_type = {
                    "boolean": FactValueType.BOOLEAN,
                    "integer": FactValueType.INTEGER,
                    "number": FactValueType.NUMBER,
                    "string": FactValueType.STRING,
                    "enum": FactValueType.ENUM,
                    "object": FactValueType.OBJECT,
                    "array": FactValueType.ARRAY,
                }[value_type]
            except (KeyError, TypeError) as error:
                raise ValueError(f"unsupported graph parameter type: {value_type!r}") from error
            enum_values = tuple(parameter.get("enum", ()))
            result.register(
                FactDefinition(
                    path_pattern=f"parameter.{name}",
                    namespace=FactNamespace.PARAMETER,
                    value_type=fact_type,
                    enum_values=enum_values,
                    nullable=not bool(parameter.get("required", False)),
                    description=str(parameter.get("description") or f"Graph parameter {name}."),
                )
            )
        return result

    def to_document(self) -> dict[str, object]:
        return {
            "version": FACT_CATALOGUE_VERSION,
            "facts": [definition.to_document() for definition in self.definitions()],
        }


def _fact(
    path_pattern: str,
    namespace: FactNamespace,
    value_type: FactValueType,
    description: str,
    *,
    nullable: bool = False,
    enum_values: tuple[object, ...] = (),
) -> FactDefinition:
    return FactDefinition(
        path_pattern=path_pattern,
        namespace=namespace,
        value_type=value_type,
        description=description,
        nullable=nullable,
        enum_values=enum_values,
    )


@lru_cache(maxsize=1)
def core_fact_catalogue() -> FactCatalogue:
    endpoint_states = (
        "discovered",
        "route-available",
        "selected",
        "linked",
        "active-signal",
        "suspended",
        "unavailable",
        "ambiguous",
        "error",
    )
    definitions = (
        _fact(
            "endpoint.{endpoint}.availability",
            FactNamespace.ENDPOINT,
            FactValueType.ENUM,
            "Current logical endpoint availability state.",
            enum_values=endpoint_states,
        ),
        _fact(
            "endpoint.{endpoint}.activeSignal",
            FactNamespace.ENDPOINT,
            FactValueType.BOOLEAN,
            "Whether the endpoint currently carries an active signal.",
        ),
        _fact(
            "endpoint.{endpoint}.volume",
            FactNamespace.ENDPOINT,
            FactValueType.NUMBER,
            "Observed endpoint volume where available.",
            nullable=True,
        ),
        _fact(
            "endpoint.{endpoint}.mute",
            FactNamespace.ENDPOINT,
            FactValueType.BOOLEAN,
            "Observed endpoint mute state where available.",
            nullable=True,
        ),
        _fact(
            "endpoint.{endpoint}.direction",
            FactNamespace.ENDPOINT,
            FactValueType.ENUM,
            "Logical endpoint direction.",
            enum_values=("input", "output"),
        ),
        _fact(
            "endpoint.{endpoint}.capabilities",
            FactNamespace.ENDPOINT,
            FactValueType.OBJECT,
            "Observed endpoint capability projection.",
        ),
        _fact(
            "signal.{node}.transport",
            FactNamespace.SIGNAL,
            FactValueType.OBJECT,
            "Observed signal transport descriptor.",
            nullable=True,
        ),
        _fact(
            "signal.{node}.content.codec",
            FactNamespace.SIGNAL,
            FactValueType.STRING,
            "Detected content codec.",
            nullable=True,
        ),
        _fact(
            "signal.{node}.decoded",
            FactNamespace.SIGNAL,
            FactValueType.OBJECT,
            "Actual decoded output descriptor.",
            nullable=True,
        ),
        _fact(
            "signal.{node}.confidence",
            FactNamespace.SIGNAL,
            FactValueType.NUMBER,
            "Confidence of the current signal observation.",
            nullable=True,
        ),
        _fact(
            "processor.{processor}.health",
            FactNamespace.PROCESSOR,
            FactValueType.ENUM,
            "Current processor health classification.",
            enum_values=("unknown", "ready", "degraded", "failed", "unavailable"),
        ),
        _fact(
            "processor.{processor}.ready",
            FactNamespace.PROCESSOR,
            FactValueType.BOOLEAN,
            "Whether the processor is ready for route activation.",
        ),
        _fact(
            "processor.{processor}.input",
            FactNamespace.PROCESSOR,
            FactValueType.OBJECT,
            "Observed processor input descriptor.",
            nullable=True,
        ),
        _fact(
            "processor.{processor}.output",
            FactNamespace.PROCESSOR,
            FactValueType.OBJECT,
            "Observed processor output descriptor.",
            nullable=True,
        ),
        _fact(
            "parameter.{parameter}",
            FactNamespace.PARAMETER,
            FactValueType.JSON,
            "Graph parameter value; concrete graphs refine this schema.",
            nullable=True,
        ),
        _fact(
            "mode.{mode}",
            FactNamespace.MODE,
            FactValueType.JSON,
            "Named user or deployment mode value.",
            nullable=True,
        ),
        _fact(
            "resource.{resource}.availability",
            FactNamespace.RESOURCE,
            FactValueType.ENUM,
            "Managed processing resource availability.",
            enum_values=("available", "degraded", "unavailable"),
        ),
        _fact(
            "resource.{resource}.capacity",
            FactNamespace.RESOURCE,
            FactValueType.INTEGER,
            "Declared resource capacity.",
        ),
        _fact(
            "resource.{resource}.allocated",
            FactNamespace.RESOURCE,
            FactValueType.INTEGER,
            "Currently allocated resource units.",
        ),
        _fact(
            "override.{scope}.active",
            FactNamespace.OVERRIDE,
            FactValueType.BOOLEAN,
            "Whether a scoped manual override is active.",
        ),
        _fact(
            "override.{scope}.value",
            FactNamespace.OVERRIDE,
            FactValueType.JSON,
            "Value supplied by the active manual override.",
            nullable=True,
        ),
        _fact(
            "override.{scope}.expiresAt",
            FactNamespace.OVERRIDE,
            FactValueType.STRING,
            "Wall-clock expiry of the active override.",
            nullable=True,
        ),
    )
    return FactCatalogue(definitions)
