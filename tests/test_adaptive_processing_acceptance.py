import copy
import json
from pathlib import Path

from core.orchestration.adaptive_decoder import (
    AdaptiveDecoderPolicy,
    resolve_adaptive_decoder_choice,
)
from core.orchestration.camilladsp_config import (
    CamillaDSPEndpoint,
    generate_camilladsp_config,
    validate_camilladsp_config_structure,
)
from core.orchestration.camilladsp_profiles import normalize_camilladsp_profile
from core.orchestration.signal_contracts import ChannelLayout
from core.orchestration.signal_descriptors import AudioFormatDescriptor, SignalDescriptor

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "orchestration" / "adaptive_signal_traces.json"


def _profile(channels: int) -> dict[str, object]:
    positions = {
        2: ["FL", "FR"],
        6: ["FL", "FR", "FC", "LFE", "SL", "SR"],
        8: ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"],
    }[channels]
    contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "rates": [48000],
        "layouts": [{"channels": channels, "positions": positions}],
    }
    return {
        "schemaVersion": 1,
        "title": "Headphones" if channels == 2 else "Living room",
        "parameters": [],
        "signalContracts": {"input": copy.deepcopy(contract), "output": contract},
        "processing": {"chunksize": 1024, "pipeline": []},
    }


def _endpoints() -> tuple[CamillaDSPEndpoint, CamillaDSPEndpoint]:
    group = "opencinema.camilladsp.acceptance.group"
    return (
        CamillaDSPEndpoint(
            "processor-input",
            "opencinema.camilladsp.acceptance.capture",
            "Open Cinema CamillaDSP Acceptance Capture",
            group,
        ),
        CamillaDSPEndpoint(
            "processor-output",
            "opencinema.camilladsp.acceptance.playback",
            "Open Cinema CamillaDSP Acceptance Playback",
            group,
        ),
    )


def test_pcm_ac3_eac3_and_dts_drive_output_compatible_camilladsp_profiles() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    policy = AdaptiveDecoderPolicy.from_document(fixture["policy"])
    cases = {case["id"]: case for case in fixture["cases"]}
    expected = {
        "plain-pcm": ("pcm-bypass", None, 2),
        "ac3": ("decode", "ac3", 6),
        "eac3": ("decode", "eac3", 6),
        "dts": ("decode", "dts", 6),
    }
    capture, playback = _endpoints()
    working_layout = ChannelLayout(8, ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"))
    working_descriptor = AudioFormatDescriptor("FLOAT32LE", 48000, working_layout)

    for case_id, (choice, codec, content_channels) in expected.items():
        observation = cases[case_id]["observations"][-1]
        descriptor = SignalDescriptor.from_document(observation["descriptor"])
        decision = resolve_adaptive_decoder_choice(
            descriptor,
            policy,
            decoder_available=observation["decoderAvailable"],
        )

        assert decision.choice.value == choice
        assert decision.codec == codec
        assert decision.output_contract is not None
        assert decision.output_contract.layouts[0].channels == content_channels

        generated = generate_camilladsp_config(
            normalize_camilladsp_profile(_profile(8)),
            capture_endpoint=capture,
            playback_endpoint=playback,
            signal=descriptor,
            input_descriptor=working_descriptor,
            output_descriptor=working_descriptor,
        )

        assert generated.configuration["devices"]["capture"]["channels"] == 8
        assert generated.configuration["devices"]["playback"]["channels"] == 8
        assert generated.configuration["devices"]["capture"]["autoconnect_to"] is None
        assert validate_camilladsp_config_structure(generated.configuration).valid
