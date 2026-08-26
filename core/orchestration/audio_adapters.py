from __future__ import annotations

import copy
import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath

from django.conf import settings
from jsonschema import Draft202012Validator

ADAPTER_SCHEMA_VERSION = 1
ROC_RECEIVER = "roc-receiver"
ROC_SENDER = "roc-sender"
DEBUG_FILE_SOURCE = "debug-file-source"
DEBUG_FILE_RECORDER = "debug-file-recorder"


class AudioAdapterConfigurationError(ValueError):
    def __init__(self, detail: str, *, field: str = "configuration") -> None:
        self.field = field
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class AudioAdapterTypeDefinition:
    kind: str
    title: str
    description: str
    direction: str
    configuration_schema: dict[str, object]

    def to_document(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "direction": self.direction,
            "schemaVersion": ADAPTER_SCHEMA_VERSION,
            "configurationSchema": copy.deepcopy(self.configuration_schema),
        }


def _object_schema(properties, required):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


_PORT = {"type": "integer", "minimum": 1, "maximum": 65535}
_FEC = {
    "type": "string",
    "enum": ["disable", "rs8m", "ldpc"],
    "default": "disable",
    "description": "Enable only when the installed ROC build includes the selected FEC codec.",
}
_ROC_PORTS = {
    "sourcePort": {**_PORT, "title": "Source port", "default": 10001},
    "repairPort": {
        **_PORT,
        "title": "Repair port",
        "description": "Used only when forward error correction is enabled.",
        "default": 10002,
    },
    "controlPort": {**_PORT, "title": "Control port", "default": 10003},
    "fecCode": {**_FEC, "title": "Forward error correction"},
}

ADAPTER_TYPES = {
    ROC_RECEIVER: AudioAdapterTypeDefinition(
        kind=ROC_RECEIVER,
        title="ROC receiver",
        description="Receive network audio and expose it as an Open Cinema input.",
        direction="input",
        configuration_schema=_object_schema(
            {
                "localAddress": {"type": "string", "title": "Listen address", "default": "0.0.0.0"},
                **_ROC_PORTS,
                "latencyMs": {
                    "type": "integer",
                    "title": "Latency (ms)",
                    "minimum": 1,
                    "maximum": 60000,
                    "default": 200,
                },
                "resamplerProfile": {
                    "type": "string",
                    "title": "Resampler profile",
                    "enum": ["disable", "high", "medium", "low"],
                    "default": "medium",
                },
            },
            [
                "localAddress",
                "sourcePort",
                "repairPort",
                "controlPort",
                "fecCode",
                "latencyMs",
                "resamplerProfile",
            ],
        ),
    ),
    ROC_SENDER: AudioAdapterTypeDefinition(
        kind=ROC_SENDER,
        title="ROC sender",
        description="Expose an Open Cinema output and send its audio to a ROC receiver.",
        direction="output",
        configuration_schema=_object_schema(
            {
                "remoteAddress": {"type": "string", "title": "Receiver address"},
                **_ROC_PORTS,
            },
            ["remoteAddress", "sourcePort", "repairPort", "controlPort", "fecCode"],
        ),
    ),
    DEBUG_FILE_SOURCE: AudioAdapterTypeDefinition(
        kind=DEBUG_FILE_SOURCE,
        title="Looping WAV source",
        description="Continuously loop a PCM WAV file as an Open Cinema input.",
        direction="input",
        configuration_schema=_object_schema(
            {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "title": "WAV path",
                    "description": "Relative to the adapter media directory.",
                }
            },
            ["path"],
        ),
    ),
    DEBUG_FILE_RECORDER: AudioAdapterTypeDefinition(
        kind=DEBUG_FILE_RECORDER,
        title="WAV recorder",
        description="Expose an Open Cinema output and record routed PCM audio.",
        direction="output",
        configuration_schema=_object_schema(
            {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Output WAV path",
                    "description": "Relative to the adapter media directory.",
                },
                "rate": {
                    "type": "integer",
                    "title": "Sample rate",
                    "minimum": 8000,
                    "maximum": 384000,
                    "default": 48000,
                },
                "channels": {
                    "type": "integer",
                    "title": "Channels",
                    "minimum": 1,
                    "maximum": 64,
                    "default": 2,
                },
                "channelMap": {
                    "type": "string",
                    "title": "Channel map",
                    "minLength": 1,
                    "default": "stereo",
                },
                "sampleFormat": {
                    "type": "string",
                    "title": "Sample format",
                    "enum": ["s16", "s32", "f32"],
                    "default": "s16",
                },
                "replaceExisting": {
                    "type": "boolean",
                    "title": "Replace existing file",
                    "default": False,
                },
            },
            ["path", "rate", "channels", "channelMap", "sampleFormat", "replaceExisting"],
        ),
    ),
}


def adapter_type_catalogue() -> list[dict[str, object]]:
    return [ADAPTER_TYPES[kind].to_document() for kind in sorted(ADAPTER_TYPES)]


def adapter_type(kind: str) -> AudioAdapterTypeDefinition:
    try:
        return ADAPTER_TYPES[kind]
    except KeyError as error:
        raise AudioAdapterConfigurationError(
            f"Unsupported adapter type {kind!r}.", field="kind"
        ) from error


def adapter_media_root(root: Path | None = None) -> Path:
    return Path(root or settings.AUDIO_ADAPTER_MEDIA_ROOT).resolve()


def resolve_adapter_media_path(value: object, *, root: Path | None = None) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AudioAdapterConfigurationError(
            "Path must be a non-empty relative WAV path.", field="configuration.path"
        )
    relative = PurePath(value)
    if relative.is_absolute() or ".." in relative.parts or value != value.strip():
        raise AudioAdapterConfigurationError(
            "Path must remain beneath the adapter media directory.", field="configuration.path"
        )
    media_root = adapter_media_root(root)
    candidate = (media_root / relative).resolve()
    if not candidate.is_relative_to(media_root) or candidate.suffix.lower() != ".wav":
        raise AudioAdapterConfigurationError(
            "Only relative .wav paths beneath the adapter media directory are allowed.",
            field="configuration.path",
        )
    return candidate


def _defaults(schema: Mapping[str, object], value: Mapping[str, object]) -> dict[str, object]:
    result = copy.deepcopy(dict(value))
    for name, definition in schema["properties"].items():
        if name not in result and "default" in definition:
            result[name] = copy.deepcopy(definition["default"])
    return result


def normalize_adapter_configuration(
    kind: str,
    configuration: Mapping[str, object],
    *,
    media_root: Path | None = None,
) -> dict[str, object]:
    definition = adapter_type(kind)
    if not isinstance(configuration, Mapping):
        raise AudioAdapterConfigurationError("Configuration must be an object.")
    candidate = _defaults(definition.configuration_schema, configuration)
    errors = sorted(
        Draft202012Validator(definition.configuration_schema).iter_errors(candidate),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path)
        raise AudioAdapterConfigurationError(
            error.message, field=f"configuration{'.' + path if path else ''}"
        )
    if kind in {ROC_RECEIVER, ROC_SENDER}:
        address_field = "localAddress" if kind == ROC_RECEIVER else "remoteAddress"
        try:
            ipaddress.ip_address(candidate[address_field])
        except ValueError as error:
            raise AudioAdapterConfigurationError(
                "Address must be a valid IPv4 or IPv6 address.",
                field=f"configuration.{address_field}",
            ) from error
        ports = [candidate["sourcePort"], candidate["repairPort"], candidate["controlPort"]]
        if len(set(ports)) != len(ports):
            raise AudioAdapterConfigurationError(
                "ROC source, repair, and control ports must be distinct.", field="configuration"
            )
    if kind in {DEBUG_FILE_SOURCE, DEBUG_FILE_RECORDER}:
        path = resolve_adapter_media_path(candidate["path"], root=media_root)
        candidate["path"] = path.relative_to(adapter_media_root(media_root)).as_posix()
        if kind == DEBUG_FILE_SOURCE and (not path.is_file() or path.is_symlink()):
            raise AudioAdapterConfigurationError(
                "Source WAV file does not exist or is not a regular file.",
                field="configuration.path",
            )
    return candidate
