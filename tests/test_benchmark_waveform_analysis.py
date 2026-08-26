from __future__ import annotations

import array
import json
import math
import wave
from pathlib import Path

import pytest

from deployment.benchmarks.analyzers.waveform import (
    AnalysisError,
    analyze_capture_health,
    analyze_channel_mapping,
    analyze_latency,
    propagate_uncertainty_ms,
    read_pcm16_wav,
    retain_analysis_artifacts,
)

ROOT = Path(__file__).parents[1]
GENERATED = ROOT / "deployment/benchmarks/media/generated"


def write_samples(
    path: Path,
    *,
    channels: int,
    sample_rate_hz: int,
    samples: array.array,
) -> None:
    assert len(samples) % channels == 0
    payload = array.array("h", samples)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(payload.tobytes())


def delayed_capture(reference_path: Path, output_path: Path, *, delay_frames: int) -> None:
    reference = read_pcm16_wav(reference_path)
    samples = array.array("h", [0] * delay_frames * reference.channels)
    samples.extend(reference.samples)
    write_samples(
        output_path,
        channels=reference.channels,
        sample_rate_hz=reference.sample_rate_hz,
        samples=samples,
    )


def test_cross_correlation_recovers_sample_exact_latency_and_uncertainty(tmp_path: Path) -> None:
    reference = read_pcm16_wav(GENERATED / "pcm-stereo-channel-id.wav")
    capture_path = tmp_path / "capture.wav"
    delayed_capture(reference.path, capture_path, delay_frames=384)
    capture = read_pcm16_wav(capture_path)

    result = analyze_latency(
        reference,
        capture,
        maximum_lag_ms=20,
        baseline_latency_ms=2.0,
        generator_uncertainty_ms=0.10,
        capture_uncertainty_ms=0.20,
        baseline_uncertainty_ms=0.05,
        clock_drift_ppm=25,
    )

    assert result["observedLagFrames"] == 384
    assert result["observedLatencyMs"] == 8.0
    assert result["correctedLatencyMs"] == 6.0
    assert result["normalizedCorrelation"] == pytest.approx(1.0)
    expected_uncertainty = math.sqrt(
        (500 / 48_000) ** 2 + 0.10**2 + 0.20**2 + 0.05**2 + (8 * 25 / 1_000_000) ** 2
    )
    assert result["uncertainty"]["totalMs"] == pytest.approx(expected_uncertainty)


def test_disconnect_and_reconnect_gaps_are_measured_objectively(tmp_path: Path) -> None:
    reference = read_pcm16_wav(GENERATED / "adaptive-switch-continuous-stereo.wav")
    delay = 240
    capture_samples = array.array("h", [0] * delay * reference.channels)
    capture_samples.extend(reference.samples)
    gap_ranges = ((48_000, 52_800), (144_000, 151_200))
    for start, end in gap_ranges:
        for frame in range(start + delay, end + delay):
            for channel in range(reference.channels):
                capture_samples[frame * reference.channels + channel] = 0
    capture_path = tmp_path / "switch-capture.wav"
    write_samples(
        capture_path,
        channels=reference.channels,
        sample_rate_hz=reference.sample_rate_hz,
        samples=capture_samples,
    )

    result = analyze_capture_health(
        reference,
        read_pcm16_wav(capture_path),
        latency_frames=delay,
        minimum_gap_ms=20,
    )

    assert len(result["unexpectedSilence"]) == 2
    assert result["unexpectedSilence"][0]["durationMs"] == pytest.approx(100.0)
    assert result["unexpectedSilence"][1]["durationMs"] == pytest.approx(150.0)
    assert result["audioLossFrame"] == 48_000
    assert result["restorationFrame"] == 52_800
    assert result["audibleGapDurationMs"] == pytest.approx(100.0)


def test_clipping_and_discontinuity_are_reported_separately(tmp_path: Path) -> None:
    reference = read_pcm16_wav(GENERATED / "adaptive-switch-continuous-stereo.wav")
    capture_samples = array.array("h", reference.samples)
    frame = 80_000
    capture_samples[frame * reference.channels] = 32_767
    capture_path = tmp_path / "clipped.wav"
    write_samples(
        capture_path,
        channels=reference.channels,
        sample_rate_hz=reference.sample_rate_hz,
        samples=capture_samples,
    )

    result = analyze_capture_health(
        reference,
        read_pcm16_wav(capture_path),
        latency_frames=0,
    )

    assert result["clipping"]["sampleCount"] == 1
    assert result["clipping"]["firstFrame"] == frame
    assert result["discontinuities"]["count"] >= 1


def test_multichannel_identification_recovers_a_permuted_mapping(tmp_path: Path) -> None:
    reference = read_pcm16_wav(GENERATED / "pcm-5_1-channel-id.wav")
    destination_to_source = (2, 0, 1, 5, 3, 4)
    expected_source_to_destination = {
        source: destination for destination, source in enumerate(destination_to_source)
    }
    delay = 96
    samples = array.array("h", [0] * delay * reference.channels)
    for frame in range(reference.frame_count):
        for source_channel in destination_to_source:
            samples.append(reference.samples[frame * reference.channels + source_channel])
    capture_path = tmp_path / "permuted.wav"
    write_samples(
        capture_path,
        channels=reference.channels,
        sample_rate_hz=reference.sample_rate_hz,
        samples=samples,
    )

    result = analyze_channel_mapping(
        reference,
        read_pcm16_wav(capture_path),
        latency_frames=delay,
        source_positions=("FL", "FR", "FC", "LFE", "SL", "SR"),
        capture_positions=("OUT1", "OUT2", "OUT3", "OUT4", "OUT5", "OUT6"),
    )

    assert result["valid"] is True
    assert {
        item["sourceChannel"]: item["captureChannel"] for item in result["assignments"]
    } == expected_source_to_destination
    assert all(item["normalizedCorrelation"] > 0.99 for item in result["assignments"])


def test_missing_marker_and_corrupted_capture_are_invalid(tmp_path: Path) -> None:
    silence = read_pcm16_wav(GENERATED / "silence-stereo.wav")
    with pytest.raises(AnalysisError, match="marker is missing"):
        analyze_latency(silence, silence, maximum_lag_ms=10)

    reference = read_pcm16_wav(GENERATED / "pcm-stereo-channel-id.wav")
    missing_capture_path = tmp_path / "missing-marker.wav"
    missing_samples = array.array("h", [0] * reference.frame_count * reference.channels)
    write_samples(
        missing_capture_path,
        channels=reference.channels,
        sample_rate_hz=reference.sample_rate_hz,
        samples=missing_samples,
    )
    with pytest.raises(AnalysisError, match="capture marker not found"):
        analyze_latency(
            reference,
            read_pcm16_wav(missing_capture_path),
            maximum_lag_ms=10,
        )

    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"RIFF\xff\xff\xff\xffWAVEfmt ")
    with pytest.raises(AnalysisError, match="cannot read PCM WAV"):
        read_pcm16_wav(corrupt)


def test_uncertainty_rejects_invalid_inputs() -> None:
    with pytest.raises(AnalysisError, match="non-negative"):
        propagate_uncertainty_ms(sample_rate_hz=48_000, capture_ms=-0.1)
    with pytest.raises(AnalysisError, match="sample rate"):
        propagate_uncertainty_ms(sample_rate_hz=0)


def test_subjective_notes_are_retained_without_becoming_measurements(tmp_path: Path) -> None:
    reference = GENERATED / "pcm-stereo-channel-id.wav"
    capture = tmp_path / "capture.wav"
    delayed_capture(reference, capture, delay_frames=24)
    objective = {"latency": {"correctedLatencyMs": 0.5}}
    note = {"kind": "perceived-sync", "text": "listener guessed about four seconds"}

    document = retain_analysis_artifacts(
        reference_path=reference,
        capture_path=capture,
        analysis=objective,
        evidence_dir=tmp_path / "evidence",
        subjective_notes=[note],
    )

    assert document["objective"] == objective
    assert document["subjectiveNotes"] == [note]
    assert "four seconds" not in json.dumps(document["objective"])
    assert all(Path(item["retainedPath"]).is_file() for item in document["artifacts"])
    persisted = json.loads((tmp_path / "evidence/waveform-analysis.json").read_text())
    assert persisted == document
