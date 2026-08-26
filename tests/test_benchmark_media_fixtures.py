from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import yaml

from core.orchestration.camilladsp_config import validate_camilladsp_config_structure
from deployment.benchmarks.media.generate_fixtures import (
    SAMPLE_RATE,
    verify,
    write_channel_identification_wav,
)

ROOT = Path(__file__).parents[1]
MEDIA = ROOT / "deployment/benchmarks/media"
GENERATED = MEDIA / "generated"


def load_manifest() -> dict:
    return json.loads((MEDIA / "manifest.json").read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_registered_synthetic_media_is_complete_and_content_addressed() -> None:
    manifest = verify(output_dir=GENERATED, manifest_path=MEDIA / "manifest.json")

    assert manifest["assetRoot"] == "generated"
    assert manifest["license"].startswith("CC0-1.0 synthetic waveforms")
    fixtures = {item["id"]: item for item in manifest["fixtures"]}
    assert set(fixtures) == {
        "pcm-channel-id-2ch",
        "pcm-channel-id-6ch",
        "pcm-channel-id-8ch",
        "pcm-stereo-raw-carrier",
        "controlled-silence",
        "no-carrier",
        "ac3-5.1",
        "eac3-5.1",
        "dts-5.1",
        "unsupported-aac-5.1",
        "adaptive-switch-continuous-stereo",
    }
    expected_formats = {
        "ac3-5.1": ("ac3", 6, "5.1(side)"),
        "eac3-5.1": ("eac3", 6, "5.1(side)"),
        "dts-5.1": ("dts", 6, "5.1(side)"),
        "unsupported-aac-5.1": ("aac", 6, "5.1"),
    }
    for fixture_id, (codec, channels, layout) in expected_formats.items():
        stream = fixtures[fixture_id]["ffprobe"]["streams"][0]
        assert stream["codec_name"] == codec
        assert stream["channels"] == channels
        assert stream["channel_layout"] == layout
        assert stream["sample_rate"] == "48000"
        assert fixtures[fixture_id]["generation"]["sourceDateEpoch"] == 0
    assert fixtures["no-carrier"]["sha256"] == hashlib.sha256(b"").hexdigest()
    assert fixtures["no-carrier"]["ffprobe"]["status"] == "not-applicable"
    assert fixtures["controlled-silence"]["generation"]["method"] == "zero-filled-pcm"
    assert fixtures["unsupported-aac-5.1"]["transport"] == "iec61937-unsupported-data-type"
    assert fixtures["unsupported-aac-5.1"]["generation"]["expectedDecoderOutcome"] == (
        "unsupported-by-design-safe-silence"
    )
    assert fixtures["unsupported-aac-5.1"]["generation"]["iec61937DataType"] == "0x07"
    unsupported_payload = (GENERATED / fixtures["unsupported-aac-5.1"]["path"]).read_bytes()
    assert unsupported_payload[:4] == bytes.fromhex("72f81f4e")
    assert int.from_bytes(unsupported_payload[4:6], "little") & 0x1F == 0x07


def test_pcm_channel_identification_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first_frames = write_channel_identification_wav(first, channels=8)
    second_frames = write_channel_identification_wav(second, channels=8)

    assert first_frames == second_frames
    assert first.read_bytes() == second.read_bytes()
    with wave.open(str(first), "rb") as stream:
        assert stream.getframerate() == SAMPLE_RATE
        assert stream.getnchannels() == 8
        assert stream.getsampwidth() == 2
        assert stream.getnframes() == first_frames


def test_transition_registry_covers_menu_cross_format_and_adaptive_switches() -> None:
    manifest = load_manifest()
    sequences = {item["id"]: item for item in manifest["transitionSequences"]}

    assert set(sequences) == {
        "pcm-2.0-to-menu",
        "ac3-5.1-to-menu",
        "pcm-7.1-to-menu-stable-output-reference",
        "ac3-eac3-dts-pcm-cross-format",
    }
    for sequence in sequences.values():
        assert sequence["markerBearing"] is True
        assert digest(GENERATED / sequence["path"]) == sequence["sha256"]
        assert len(sequence["segments"]) >= 2
    cross_format = sequences["ac3-eac3-dts-pcm-cross-format"]
    assert [segment["fixtureId"] for segment in cross_format["segments"]] == [
        "ac3-5.1",
        "eac3-5.1",
        "dts-5.1",
        "pcm-stereo-raw-carrier",
    ]
    seven_one = sequences["pcm-7.1-to-menu-stable-output-reference"]
    assert seven_one["channels"] == 8
    assert [segment["expectedDecodedLayout"] for segment in seven_one["segments"]] == [
        "7.1",
        "stereo-menu-in-eight-channel-contract",
    ]
    adaptive = manifest["adaptiveRoutingSequence"]
    assert [item["event"] for item in adaptive["eventSchedule"]] == [
        "headset-disconnect",
        "headset-reconnect",
    ]


def test_camilladsp_profiles_are_valid_128_frame_native_pipewire_workloads() -> None:
    root = MEDIA / "camilladsp"
    registry = json.loads((root / "profiles.json").read_text())
    profiles = {item["id"]: item for item in registry["profiles"]}

    assert set(profiles) == {
        "camilladsp-passthrough-128",
        "camilladsp-stereo-128",
        "camilladsp-multichannel-128",
        "camilladsp-channel-adaptation-128",
        "camilladsp-production-fir-iir-128",
    }
    for profile in profiles.values():
        path = root / profile["path"]
        document = yaml.safe_load(path.read_text())
        result = validate_camilladsp_config_structure(document)
        assert result.valid, result.errors
        assert document["devices"]["samplerate"] == 48_000
        assert document["devices"]["chunksize"] == 128
        assert document["devices"]["capture"]["type"] == "PipeWire"
        assert document["devices"]["playback"]["type"] == "PipeWire"
        assert digest(path) == profile["sha256"]
    production = profiles["camilladsp-production-fir-iir-128"]
    assert production["workload"] == {
        "mixers": 0,
        "iirBiquadsPerChannel": 2,
        "firTapsPerChannel": 1024,
    }
    fir = registry["assets"][0]
    assert fir["taps"] == 1024
    assert fir["sizeBytes"] == 4_096
    assert digest(root / fir["path"]) == fir["sha256"]


def test_physical_path_does_not_invent_an_uncalibrated_latency() -> None:
    path = yaml.safe_load((MEDIA / "physical-path.yml").read_text())

    assert path["state"] == "awaiting-physical-loopback-calibration"
    assert path["acceptance_metrics_available"] is False
    assert path["calibration"]["physical_result"] == "not-measured"
    assert path["calibration"]["loopback_baseline"]["median_ms"] is None
    assert path["clock_relationship"]["kind"] == "independent-generator-and-capture-clocks"
    assert "Never subtract" in path["clock_relationship"]["subtraction_policy"]
    assert path["subjective_observation_policy"]["quantitative_substitution"] == "forbidden"
