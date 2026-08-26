from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import yaml

from .camilladsp_profiles import (
    CamillaDSPProfileDocument,
    CamillaDSPProfileError,
    resolve_camilladsp_parameters,
)
from .graph_documents import graph_content_digest
from .signal_contracts import AudioContent, ChannelLayout
from .signal_descriptors import AudioFormatDescriptor, SignalContentKind, SignalDescriptor


class CamillaDSPConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CamillaDSPEndpoint:
    logical_id: str
    node_name: str
    node_description: str
    node_group_name: str
    autoconnect_to: str | None = None
    backend: str = "PipeWire"

    def __post_init__(self) -> None:
        for name in (
            "logical_id",
            "node_name",
            "node_description",
            "node_group_name",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")
        if self.backend != "PipeWire":
            raise ValueError("Open Cinema requires CamillaDSP 4 native PipeWire endpoints")
        if self.autoconnect_to is not None and not self.autoconnect_to:
            raise ValueError("autoconnect_to must be non-empty or null")

    def to_document(self) -> dict[str, object]:
        return {
            "logicalId": self.logical_id,
            "backend": self.backend,
            "nodeName": self.node_name,
            "nodeDescription": self.node_description,
            "nodeGroupName": self.node_group_name,
            "autoconnectTo": self.autoconnect_to,
        }


@dataclass(frozen=True, slots=True)
class ChannelAdaptation:
    name: str
    input_layout: ChannelLayout
    output_layout: ChannelLayout
    mapping: tuple[Mapping[str, object], ...] = ()
    existing_mixer: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("channel adaptation name must be non-empty")
        if not isinstance(self.input_layout, ChannelLayout) or not isinstance(
            self.output_layout, ChannelLayout
        ):
            raise TypeError("channel adaptation requires typed layouts")
        mapping = tuple(copy.deepcopy(dict(item)) for item in self.mapping)
        if not isinstance(self.existing_mixer, bool):
            raise TypeError("existing_mixer must be a boolean")
        if mapping and self.existing_mixer:
            raise ValueError("channel adaptation cannot both inject and reuse a mixer")
        if (
            self.input_layout.channels != self.output_layout.channels
            and not mapping
            and not self.existing_mixer
        ):
            raise ValueError("channel count changes require an explicit mixer mapping")
        object.__setattr__(self, "mapping", mapping)

    @classmethod
    def passthrough(cls, layout: ChannelLayout) -> "ChannelAdaptation":
        return cls("passthrough", layout, layout)


@dataclass(frozen=True, slots=True)
class GeneratedCamillaDSPConfig:
    configuration: dict[str, object]
    digest: str
    profile_digest: str
    input_descriptor: AudioFormatDescriptor
    output_descriptor: AudioFormatDescriptor
    capture_endpoint: CamillaDSPEndpoint
    playback_endpoint: CamillaDSPEndpoint

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.configuration, sort_keys=False)

    def to_driver_configuration(self) -> dict[str, object]:
        return {
            "generatedConfiguration": copy.deepcopy(self.configuration),
            "configurationDigest": self.digest,
            "profileDigest": self.profile_digest,
            "inputDescriptor": self.input_descriptor.to_document(),
            "outputDescriptor": self.output_descriptor.to_document(),
            "captureEndpoint": self.capture_endpoint.to_document(),
            "playbackEndpoint": self.playback_endpoint.to_document(),
        }


@dataclass(frozen=True, slots=True)
class CamillaDSPValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    normalized_configuration: Mapping[str, object] | None = None


def _replace_parameters(value: object, resolved: Mapping[str, object]) -> object:
    if isinstance(value, list):
        return [_replace_parameters(item, resolved) for item in value]
    if not isinstance(value, Mapping):
        return copy.deepcopy(value)
    if set(value) == {"parameter"}:
        name = value["parameter"]
        if name not in resolved:
            raise CamillaDSPConfigError(f"profile parameter {name!r} requires a binding")
        return copy.deepcopy(resolved[name])
    return {str(name): _replace_parameters(item, resolved) for name, item in value.items()}


def _effective_input(signal: SignalDescriptor) -> AudioFormatDescriptor:
    if signal.decoded_output is not None:
        return signal.decoded_output
    if signal.content.kind is SignalContentKind.PCM:
        return signal.transport.format
    raise CamillaDSPConfigError(
        "CamillaDSP requires PCM input; encoded content has no decoded descriptor"
    )


def _contract_errors(
    descriptor: AudioFormatDescriptor,
    contract,
    *,
    role: str,
) -> list[str]:
    errors = []
    if contract.content not in {AudioContent.ANY, AudioContent.PCM}:
        errors.append(f"{role} contract does not accept PCM")
    if descriptor.sample_format and contract.sample_formats:
        if descriptor.sample_format not in contract.sample_formats:
            errors.append(f"{role} sample format is outside the profile contract")
    if descriptor.rate and contract.rates and descriptor.rate not in contract.rates:
        errors.append(f"{role} sample rate is outside the profile contract")
    if descriptor.layout and contract.layouts and descriptor.layout not in contract.layouts:
        errors.append(f"{role} channel layout is outside the profile contract")
    return errors


def generate_camilladsp_config(
    profile: CamillaDSPProfileDocument,
    *,
    capture_endpoint: CamillaDSPEndpoint,
    playback_endpoint: CamillaDSPEndpoint,
    signal: SignalDescriptor,
    input_descriptor: AudioFormatDescriptor | None = None,
    output_descriptor: AudioFormatDescriptor,
    parameter_bindings: Mapping[str, object] | None = None,
    channel_adaptation: ChannelAdaptation | None = None,
) -> GeneratedCamillaDSPConfig:
    if not isinstance(profile, CamillaDSPProfileDocument):
        raise TypeError("profile must be a normalized CamillaDSPProfileDocument")
    if not isinstance(signal, SignalDescriptor):
        raise TypeError("signal must be a SignalDescriptor")
    if not isinstance(output_descriptor, AudioFormatDescriptor):
        raise TypeError("output_descriptor must be an AudioFormatDescriptor")
    input_descriptor = input_descriptor or _effective_input(signal)
    if not isinstance(input_descriptor, AudioFormatDescriptor):
        raise TypeError("input_descriptor must be an AudioFormatDescriptor or null")
    if input_descriptor.rate is None or input_descriptor.layout is None:
        raise CamillaDSPConfigError("input rate and channel layout must be resolved")
    if output_descriptor.rate is None or output_descriptor.layout is None:
        raise CamillaDSPConfigError("output rate and channel layout must be resolved")

    contract_errors = [
        *_contract_errors(input_descriptor, profile.input_contract, role="input"),
        *_contract_errors(output_descriptor, profile.output_contract, role="output"),
    ]
    if contract_errors:
        raise CamillaDSPConfigError("; ".join(contract_errors))

    adaptation = channel_adaptation
    if adaptation is None:
        if input_descriptor.layout != output_descriptor.layout:
            raise CamillaDSPConfigError(
                "a channel adaptation decision is required when layouts differ"
            )
        adaptation = ChannelAdaptation.passthrough(input_descriptor.layout)
    if adaptation.input_layout != input_descriptor.layout:
        raise CamillaDSPConfigError("channel adaptation input does not match the signal")
    if adaptation.output_layout != output_descriptor.layout:
        raise CamillaDSPConfigError("channel adaptation output does not match the route")

    try:
        resolved_parameters = resolve_camilladsp_parameters(
            profile,
            parameter_bindings or {},
        )
    except CamillaDSPProfileError as error:
        raise CamillaDSPConfigError(str(error)) from error
    processing = _replace_parameters(profile.content["processing"], resolved_parameters)
    chunksize = processing.pop("chunksize")
    samplerate = processing.pop("samplerate", output_descriptor.rate)
    capture_samplerate = processing.pop("captureSamplerate", input_descriptor.rate)
    device_options = processing.pop("deviceOptions", {})
    filters = processing.pop("filters", {})
    mixers = processing.pop("mixers", {})
    pipeline = processing.pop("pipeline", [])
    resampler = processing.pop("resampler", None)
    if processing:
        raise CamillaDSPConfigError(
            f"unsupported processing fields: {', '.join(sorted(processing))}"
        )

    devices = {
        "samplerate": samplerate,
        "chunksize": chunksize,
        **device_options,
        "capture": {
            "type": capture_endpoint.backend,
            "channels": input_descriptor.layout.channels,
            "node_name": capture_endpoint.node_name,
            "node_description": capture_endpoint.node_description,
            "node_group_name": capture_endpoint.node_group_name,
            "autoconnect_to": capture_endpoint.autoconnect_to,
        },
        "playback": {
            "type": playback_endpoint.backend,
            "channels": output_descriptor.layout.channels,
            "node_name": playback_endpoint.node_name,
            "node_description": playback_endpoint.node_description,
            "node_group_name": playback_endpoint.node_group_name,
            "autoconnect_to": playback_endpoint.autoconnect_to,
        },
    }
    if capture_samplerate != samplerate:
        if resampler is None:
            raise CamillaDSPConfigError("rate conversion requires an explicit CamillaDSP resampler")
        devices["capture_samplerate"] = capture_samplerate
        devices["resampler"] = resampler
    elif resampler is not None:
        devices["resampler"] = resampler

    if adaptation.mapping:
        mixer_name = f"open_cinema_{adaptation.name}"
        if mixer_name in mixers:
            raise CamillaDSPConfigError(
                f"channel adaptation mixer {mixer_name!r} conflicts with the profile"
            )
        mixers[mixer_name] = {
            "channels": {
                "in": adaptation.input_layout.channels,
                "out": adaptation.output_layout.channels,
            },
            "mapping": [copy.deepcopy(dict(item)) for item in adaptation.mapping],
        }
        pipeline = [{"type": "Mixer", "name": mixer_name}, *pipeline]
    elif adaptation.existing_mixer:
        mixer_name = adaptation.name
        mixer = mixers.get(mixer_name)
        if not isinstance(mixer, Mapping):
            raise CamillaDSPConfigError(
                f"channel adaptation mixer {mixer_name!r} is absent from the profile"
            )
        channels = mixer.get("channels")
        expected_channels = {
            "in": adaptation.input_layout.channels,
            "out": adaptation.output_layout.channels,
        }
        if channels != expected_channels:
            raise CamillaDSPConfigError(
                f"channel adaptation mixer {mixer_name!r} has incompatible channels"
            )
        if not any(
            isinstance(item, Mapping)
            and item.get("type") == "Mixer"
            and item.get("name") == mixer_name
            for item in pipeline
        ):
            pipeline = [{"type": "Mixer", "name": mixer_name}, *pipeline]

    configuration: dict[str, object] = {
        "title": profile.content.get("title", "Open Cinema managed profile"),
        "description": profile.content.get(
            "description",
            f"Managed profile {profile.digest}",
        ),
        "devices": devices,
    }
    if filters:
        configuration["filters"] = filters
    if mixers:
        configuration["mixers"] = mixers
    if pipeline:
        configuration["pipeline"] = pipeline
    validate_camilladsp_config_structure(configuration, raise_on_error=True)
    return GeneratedCamillaDSPConfig(
        configuration=configuration,
        digest=graph_content_digest(configuration),
        profile_digest=profile.digest,
        input_descriptor=input_descriptor,
        output_descriptor=output_descriptor,
        capture_endpoint=capture_endpoint,
        playback_endpoint=playback_endpoint,
    )


def _positive_integer(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        errors.append(f"{path} must be a positive integer")


def validate_camilladsp_config_structure(
    configuration: Mapping[str, object],
    *,
    raise_on_error: bool = False,
) -> CamillaDSPValidationResult:
    errors: list[str] = []
    if not isinstance(configuration, Mapping):
        errors.append("configuration must be an object")
        result = CamillaDSPValidationResult(False, tuple(errors))
        if raise_on_error:
            raise CamillaDSPConfigError(errors[0])
        return result
    allowed = {"title", "description", "devices", "filters", "mixers", "pipeline"}
    unknown = set(configuration) - allowed
    if unknown:
        errors.append(f"unknown top-level fields: {', '.join(sorted(unknown))}")
    devices = configuration.get("devices")
    if not isinstance(devices, Mapping):
        errors.append("devices must be an object")
        devices = {}
    _positive_integer(devices.get("samplerate"), "devices.samplerate", errors)
    _positive_integer(devices.get("chunksize"), "devices.chunksize", errors)
    for role in ("capture", "playback"):
        device = devices.get(role)
        if not isinstance(device, Mapping):
            errors.append(f"devices.{role} must be an object")
            continue
        backend = device.get("type")
        if backend != "PipeWire":
            errors.append(f"devices.{role}.type must be PipeWire")
        _positive_integer(device.get("channels"), f"devices.{role}.channels", errors)
        for field in ("node_name", "node_description", "node_group_name"):
            if not isinstance(device.get(field), str) or not device.get(field):
                errors.append(f"devices.{role}.{field} must be a non-empty string")
        if device.get("autoconnect_to") is not None:
            errors.append(
                f"devices.{role}.autoconnect_to must be null; WirePlumber owns routing"
            )
        if "device" in device or "format" in device:
            errors.append(
                f"devices.{role} contains a legacy device or sample-format field"
            )

    filters = configuration.get("filters", {})
    if not isinstance(filters, Mapping):
        errors.append("filters must be an object")
        filters = {}
    for name, filter_config in filters.items():
        if not isinstance(name, str) or not name or not isinstance(filter_config, Mapping):
            errors.append("each filter must have a non-empty name and object value")
        elif not isinstance(filter_config.get("type"), str):
            errors.append(f"filter {name!r} must declare a type")

    mixers = configuration.get("mixers", {})
    if not isinstance(mixers, Mapping):
        errors.append("mixers must be an object")
        mixers = {}
    for name, mixer in mixers.items():
        if not isinstance(name, str) or not name or not isinstance(mixer, Mapping):
            errors.append("each mixer must have a non-empty name and object value")
            continue
        channels = mixer.get("channels")
        if not isinstance(channels, Mapping):
            errors.append(f"mixer {name!r} channels must be an object")
            continue
        in_channels = channels.get("in")
        out_channels = channels.get("out")
        _positive_integer(in_channels, f"mixers.{name}.channels.in", errors)
        _positive_integer(out_channels, f"mixers.{name}.channels.out", errors)
        mapping = mixer.get("mapping")
        if not isinstance(mapping, Sequence) or isinstance(mapping, (str, bytes)):
            errors.append(f"mixer {name!r} mapping must be an array")
            continue
        destinations = set()
        for index, entry in enumerate(mapping):
            if not isinstance(entry, Mapping):
                errors.append(f"mixer {name!r} mapping {index} must be an object")
                continue
            destination = entry.get("dest")
            if not isinstance(destination, int) or isinstance(destination, bool):
                errors.append(f"mixer {name!r} mapping {index} has invalid dest")
            elif isinstance(out_channels, int) and not 0 <= destination < out_channels:
                errors.append(f"mixer {name!r} mapping {index} dest is out of range")
            elif destination in destinations:
                errors.append(f"mixer {name!r} maps destination {destination} twice")
            destinations.add(destination)
            sources = entry.get("sources")
            if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
                errors.append(f"mixer {name!r} mapping {index} sources must be an array")
                continue
            for source in sources:
                channel = source.get("channel") if isinstance(source, Mapping) else None
                if (
                    not isinstance(channel, int)
                    or isinstance(channel, bool)
                    or (isinstance(in_channels, int) and not 0 <= channel < in_channels)
                ):
                    errors.append(f"mixer {name!r} mapping {index} source is out of range")

    pipeline = configuration.get("pipeline", [])
    if not isinstance(pipeline, Sequence) or isinstance(pipeline, (str, bytes)):
        errors.append("pipeline must be an array")
        pipeline = []
    for index, step in enumerate(pipeline):
        if not isinstance(step, Mapping):
            errors.append(f"pipeline step {index} must be an object")
            continue
        step_type = step.get("type")
        if step_type == "Mixer" and step.get("name") not in mixers:
            errors.append(f"pipeline step {index} references an unknown mixer")
        elif step_type == "Filter":
            names = step.get("names")
            if not isinstance(names, Sequence) or isinstance(names, (str, bytes)):
                errors.append(f"pipeline step {index} filter names must be an array")
            elif any(name not in filters for name in names):
                errors.append(f"pipeline step {index} references an unknown filter")
        elif step_type not in {"Mixer", "Filter", "Processor"}:
            errors.append(f"pipeline step {index} has unsupported type {step_type!r}")

    try:
        normalized = copy.deepcopy(dict(configuration))
        graph_content_digest(normalized)
    except (TypeError, ValueError) as error:
        errors.append(f"configuration is not canonical JSON: {error}")
        normalized = None
    result = CamillaDSPValidationResult(
        valid=not errors,
        errors=tuple(errors),
        normalized_configuration=normalized if not errors else None,
    )
    if errors and raise_on_error:
        raise CamillaDSPConfigError("; ".join(errors))
    return result
