from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from .graph_documents import graph_content_digest
from .signal_contracts import SignalContract

CAMILLADSP_PROFILE_SCHEMA_VERSION = 1

_PARAMETER_TYPES = {
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "string": str,
}

CAMILLADSP_PROFILE_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "parameters",
        "signalContracts",
        "processing",
    ],
    "properties": {
        "schemaVersion": {"const": CAMILLADSP_PROFILE_SCHEMA_VERSION},
        "title": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "maxLength": 4096},
        "parameters": {
            "type": "array",
            "maxItems": 128,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type"],
                "properties": {
                    "name": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,127}$",
                    },
                    "type": {"enum": sorted(_PARAMETER_TYPES)},
                    "description": {"type": "string", "maxLength": 2048},
                    "required": {"type": "boolean"},
                    "default": {},
                    "minimum": {"type": "number"},
                    "maximum": {"type": "number"},
                    "enum": {"type": "array", "maxItems": 256},
                },
            },
        },
        "signalContracts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["input", "output"],
            "properties": {
                "input": {"type": "object"},
                "output": {"type": "object"},
            },
        },
        "processing": {
            "type": "object",
            "additionalProperties": False,
            "required": ["chunksize"],
            "properties": {
                "chunksize": {},
                "samplerate": {},
                "captureSamplerate": {},
                "resampler": {"type": ["object", "null"]},
                "deviceOptions": {"type": "object"},
                "filters": {"type": "object", "maxProperties": 512},
                "mixers": {"type": "object", "maxProperties": 128},
                "pipeline": {"type": "array", "maxItems": 1024},
            },
        },
    },
}


class CamillaDSPProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CamillaDSPProfileDocument:
    content: dict[str, object]
    digest: str
    input_contract: SignalContract
    output_contract: SignalContract


def _path(error) -> str:
    return ".".join(str(component) for component in error.absolute_path) or "$"


def _validate_parameter_value(definition: Mapping[str, object], value: object) -> None:
    name = definition["name"]
    parameter_type = definition["type"]
    expected = _PARAMETER_TYPES[parameter_type]
    if isinstance(value, bool) and parameter_type in {"integer", "number"}:
        raise CamillaDSPProfileError(f"parameter {name!r} has an invalid boolean value")
    if not isinstance(value, expected):
        raise CamillaDSPProfileError(f"parameter {name!r} value must be of type {parameter_type}")
    if "minimum" in definition and value < definition["minimum"]:
        raise CamillaDSPProfileError(f"parameter {name!r} value is below minimum")
    if "maximum" in definition and value > definition["maximum"]:
        raise CamillaDSPProfileError(f"parameter {name!r} value is above maximum")
    if "enum" in definition and value not in definition["enum"]:
        raise CamillaDSPProfileError(f"parameter {name!r} value is not in enum")


def _validate_references(
    value: object, parameter_names: set[str], path: str = "processing"
) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_references(item, parameter_names, f"{path}.{index}")
        return
    if not isinstance(value, Mapping):
        return
    if set(value) == {"parameter"}:
        name = value["parameter"]
        if not isinstance(name, str) or name not in parameter_names:
            raise CamillaDSPProfileError(f"{path} references undeclared parameter {name!r}")
        return
    for name, item in value.items():
        _validate_references(item, parameter_names, f"{path}.{name}")


def normalize_camilladsp_profile(
    document: Mapping[str, object],
) -> CamillaDSPProfileDocument:
    if not isinstance(document, Mapping):
        raise CamillaDSPProfileError("CamillaDSP profile must be an object")
    candidate = copy.deepcopy(dict(document))
    errors = sorted(
        Draft202012Validator(CAMILLADSP_PROFILE_JSON_SCHEMA).iter_errors(candidate),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        raise CamillaDSPProfileError(f"{_path(first)}: {first.message}")

    parameters = candidate["parameters"]
    names = [item["name"] for item in parameters]
    if len(names) != len(set(names)):
        raise CamillaDSPProfileError("profile parameter names must be unique")
    for definition in parameters:
        if definition.get("required", False) and "default" in definition:
            raise CamillaDSPProfileError(
                f"required parameter {definition['name']!r} cannot declare a default"
            )
        if (
            "minimum" in definition
            and "maximum" in definition
            and definition["minimum"] > definition["maximum"]
        ):
            raise CamillaDSPProfileError(
                f"parameter {definition['name']!r} minimum exceeds maximum"
            )
        if "default" in definition:
            _validate_parameter_value(definition, definition["default"])

    try:
        contracts = candidate["signalContracts"]
        input_contract = SignalContract.from_document(contracts["input"])
        output_contract = SignalContract.from_document(contracts["output"])
    except (TypeError, ValueError) as error:
        raise CamillaDSPProfileError(f"invalid signal contract: {error}") from error

    processing = candidate["processing"]
    forbidden = {"devices", "capture", "playback"}.intersection(processing)
    if forbidden:
        raise CamillaDSPProfileError(
            "profiles are device-independent; concrete device fields are forbidden"
        )
    _validate_references(processing, set(names))
    candidate["parameters"] = sorted(parameters, key=lambda item: item["name"])
    return CamillaDSPProfileDocument(
        content=candidate,
        digest=graph_content_digest(candidate),
        input_contract=input_contract,
        output_contract=output_contract,
    )


def resolve_camilladsp_parameters(
    profile: CamillaDSPProfileDocument,
    bindings: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(bindings, Mapping):
        raise CamillaDSPProfileError("profile parameter bindings must be an object")
    definitions = {item["name"]: item for item in profile.content["parameters"]}
    unknown = set(bindings) - set(definitions)
    if unknown:
        raise CamillaDSPProfileError(f"unknown profile parameters: {', '.join(sorted(unknown))}")
    resolved = {}
    for name, definition in definitions.items():
        if name in bindings:
            value = bindings[name]
        elif "default" in definition:
            value = definition["default"]
        elif definition.get("required", False):
            raise CamillaDSPProfileError(f"required parameter {name!r} is missing")
        else:
            continue
        _validate_parameter_value(definition, value)
        resolved[name] = copy.deepcopy(value)
    return resolved
