from __future__ import annotations

import copy

import pytest

from core.orchestration.camilladsp_config import (
    CamillaDSPConfigError,
    CamillaDSPEndpoint,
    ChannelAdaptation,
    generate_camilladsp_config,
    validate_camilladsp_config_structure,
)
from core.orchestration.camilladsp_profiles import normalize_camilladsp_profile
from core.orchestration.signal_contracts import ChannelLayout
from core.orchestration.signal_descriptors import (
    SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalContentKind,
    SignalDescriptor,
    SignalObservationSource,
    SignalObservationSourceKind,
    SignalTransportDescriptor,
    SignalTransportKind,
)


def profile_document(*, channels: int = 2) -> dict[str, object]:
    positions = ["FL", "FR"] if channels == 2 else ["FL", "FR", "FC", "LFE", "SL", "SR"]
    contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "rates": [48000],
        "layouts": [{"channels": channels, "positions": positions}],
    }
    return {
        "schemaVersion": 1,
        "title": "Living room",
        "parameters": [{"name": "gainDb", "type": "number", "default": -3.0}],
        "signalContracts": {"input": copy.deepcopy(contract), "output": contract},
        "processing": {
            "chunksize": 1024,
            "filters": {
                "room_gain": {
                    "type": "Gain",
                    "parameters": {"gain": {"parameter": "gainDb"}},
                }
            },
            "pipeline": [
                {"type": "Filter", "channels": list(range(channels)), "names": ["room_gain"]}
            ],
        },
    }


def signal(layout: ChannelLayout) -> SignalDescriptor:
    audio_format = AudioFormatDescriptor("FLOAT32LE", 48000, layout)
    return SignalDescriptor(
        SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
        SignalTransportDescriptor(SignalTransportKind.PCM, audio_format),
        SignalContentDescriptor(SignalContentKind.PCM),
        None,
        1.0,
        SignalObservationSource(SignalObservationSourceKind.WIREPLUMBER, "tv"),
        "2026-08-22T12:00:00Z",
    )


def endpoints(index: int = 0):
    prefix = f"opencinema.camilladsp.{index}"
    group = f"{prefix}.group"
    return (
        CamillaDSPEndpoint(
            "processor-input",
            f"{prefix}.capture",
            f"Open Cinema CamillaDSP {index} Capture",
            group,
        ),
        CamillaDSPEndpoint(
            "processor-output",
            f"{prefix}.playback",
            f"Open Cinema CamillaDSP {index} Playback",
            group,
        ),
    )


def test_stereo_configuration_uses_native_pipewire_nodes_without_autoconnect() -> None:
    layout = ChannelLayout(2, ("FL", "FR"))
    capture, playback = endpoints()
    generated = generate_camilladsp_config(
        normalize_camilladsp_profile(profile_document()),
        capture_endpoint=capture,
        playback_endpoint=playback,
        signal=signal(layout),
        output_descriptor=AudioFormatDescriptor("FLOAT32LE", 48000, layout),
        parameter_bindings={"gainDb": -9},
    )

    devices = generated.configuration["devices"]
    assert devices["capture"] == {
        "type": "PipeWire",
        "channels": 2,
        "node_name": "opencinema.camilladsp.0.capture",
        "node_description": "Open Cinema CamillaDSP 0 Capture",
        "node_group_name": "opencinema.camilladsp.0.group",
        "autoconnect_to": None,
    }
    assert devices["playback"]["node_name"] == "opencinema.camilladsp.0.playback"
    assert devices["playback"]["node_group_name"] == devices["capture"]["node_group_name"]
    assert devices["playback"]["autoconnect_to"] is None
    assert "device" not in devices["playback"]
    assert "format" not in devices["playback"]
    assert generated.configuration["filters"]["room_gain"]["parameters"]["gain"] == -9
    assert validate_camilladsp_config_structure(generated.configuration).valid


def test_explicit_5_1_to_headset_adaptation_generates_mixer() -> None:
    source_layout = ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR"))
    headset_layout = ChannelLayout(2, ("FL", "FR"))
    mapping = (
        {
            "dest": 0,
            "sources": [
                {"channel": 0, "gain": 0.0},
                {"channel": 2, "gain": -3.0},
                {"channel": 4, "gain": -3.0},
            ],
        },
        {
            "dest": 1,
            "sources": [
                {"channel": 1, "gain": 0.0},
                {"channel": 2, "gain": -3.0},
                {"channel": 5, "gain": -3.0},
            ],
        },
    )
    profile = profile_document(channels=6)
    profile["signalContracts"]["output"]["layouts"] = [headset_layout.to_document()]
    capture, playback = endpoints()

    generated = generate_camilladsp_config(
        normalize_camilladsp_profile(profile),
        capture_endpoint=capture,
        playback_endpoint=playback,
        signal=signal(source_layout),
        output_descriptor=AudioFormatDescriptor("FLOAT32LE", 48000, headset_layout),
        channel_adaptation=ChannelAdaptation(
            "surround_to_headset",
            source_layout,
            headset_layout,
            mapping,
        ),
    )

    assert generated.configuration["devices"]["playback"]["channels"] == 2
    assert generated.configuration["pipeline"][0] == {
        "type": "Mixer",
        "name": "open_cinema_surround_to_headset",
    }


def test_explicit_profile_mixer_adaptation_reuses_named_mixer() -> None:
    source_layout = ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR"))
    headset_layout = ChannelLayout(2, ("FL", "FR"))
    profile = profile_document(channels=6)
    profile["signalContracts"]["output"]["layouts"] = [headset_layout.to_document()]
    profile["processing"]["mixers"] = {
        "headset_downmix": {
            "channels": {"in": 6, "out": 2},
            "mapping": [
                {"dest": 0, "sources": [{"channel": 0, "gain": 0.0}]},
                {"dest": 1, "sources": [{"channel": 1, "gain": 0.0}]},
            ],
        }
    }
    capture, playback = endpoints()

    generated = generate_camilladsp_config(
        normalize_camilladsp_profile(profile),
        capture_endpoint=capture,
        playback_endpoint=playback,
        signal=signal(source_layout),
        output_descriptor=AudioFormatDescriptor("FLOAT32LE", 48000, headset_layout),
        channel_adaptation=ChannelAdaptation(
            "headset_downmix",
            source_layout,
            headset_layout,
            existing_mixer=True,
        ),
    )

    assert generated.configuration["devices"]["playback"]["channels"] == 2
    assert generated.configuration["pipeline"][0] == {
        "type": "Mixer",
        "name": "headset_downmix",
    }
    assert "open_cinema_headset_downmix" not in generated.configuration["mixers"]


def test_six_channel_room_profile_preserves_resolved_layout() -> None:
    layout = ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR"))
    capture, playback = endpoints()

    generated = generate_camilladsp_config(
        normalize_camilladsp_profile(profile_document(channels=6)),
        capture_endpoint=capture,
        playback_endpoint=playback,
        signal=signal(layout),
        output_descriptor=AudioFormatDescriptor("FLOAT32LE", 48000, layout),
    )

    assert generated.configuration["devices"]["capture"]["channels"] == 6
    assert generated.configuration["devices"]["playback"]["channels"] == 6
    assert "mixers" not in generated.configuration


def test_channel_change_without_adaptation_is_rejected() -> None:
    source = ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR"))
    output = ChannelLayout(2, ("FL", "FR"))
    profile = profile_document(channels=6)
    profile["signalContracts"]["output"]["layouts"] = [output.to_document()]
    with pytest.raises(CamillaDSPConfigError, match="adaptation decision"):
        generate_camilladsp_config(
            normalize_camilladsp_profile(profile),
            capture_endpoint=endpoints()[0],
            playback_endpoint=endpoints()[1],
            signal=signal(source),
            output_descriptor=AudioFormatDescriptor("FLOAT32LE", 48000, output),
        )


def test_structural_validation_reports_invalid_references() -> None:
    invalid = {
        "devices": {
            "samplerate": 48000,
            "chunksize": 1024,
            "capture": {
                "type": "PipeWire",
                "channels": 2,
                "node_name": "input",
                "node_description": "Input",
                "node_group_name": "test",
                "autoconnect_to": None,
            },
            "playback": {
                "type": "PipeWire",
                "channels": 2,
                "node_name": "output",
                "node_description": "Output",
                "node_group_name": "test",
                "autoconnect_to": None,
            },
        },
        "pipeline": [{"type": "Filter", "channels": [0, 1], "names": ["missing"]}],
    }

    result = validate_camilladsp_config_structure(invalid)

    assert not result.valid
    assert "unknown filter" in result.errors[0]
