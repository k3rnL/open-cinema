#!/usr/bin/env python3
"""Analyze marker-bearing PCM captures without optional numeric dependencies."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import shutil
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_MARKER_START_FRAME = 4_800
DEFAULT_MARKER_FRAMES = 13 * 96
CHANNEL_SLOT_START_FRAME = 9_600
CHANNEL_SLOT_STRIDE_FRAMES = 4_800
CHANNEL_SLOT_ACTIVE_FRAMES = 3_600


class AnalysisError(ValueError):
    """Waveform evidence is absent, corrupt, or incompatible."""


@dataclass(frozen=True, slots=True)
class Waveform:
    path: Path
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    samples: array.array
    sha256: str

    def channel(self, index: int) -> array.array:
        if index < 0 or index >= self.channels:
            raise AnalysisError(f"channel {index} is outside the {self.channels}-channel waveform")
        return array.array("h", self.samples[index :: self.channels])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pcm16_wav(path: Path | str) -> Waveform:
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getcomptype() != "NONE":
                raise AnalysisError(f"{path} is compressed, not linear PCM")
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            sample_rate = stream.getframerate()
            frame_count = stream.getnframes()
            if channels < 1 or sample_rate < 1:
                raise AnalysisError(f"{path} has invalid channel or rate metadata")
            if sample_width != 2:
                raise AnalysisError(f"{path} must contain signed 16-bit PCM")
            payload = stream.readframes(frame_count)
    except (EOFError, OSError, wave.Error) as error:
        raise AnalysisError(f"cannot read PCM WAV {path}: {error}") from error

    expected_bytes = frame_count * channels * sample_width
    if len(payload) != expected_bytes:
        raise AnalysisError(
            f"truncated PCM WAV {path}: expected {expected_bytes} bytes, got {len(payload)}"
        )
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    return Waveform(
        path=path.resolve(),
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frame_count=frame_count,
        samples=samples,
        sha256=_sha256(path),
    )


def _assert_compatible(reference: Waveform, capture: Waveform) -> None:
    if reference.sample_rate_hz != capture.sample_rate_hz:
        raise AnalysisError(
            "reference and capture sample rates differ; resampling would invalidate timing"
        )


def _normalized_score(
    template: Sequence[int],
    candidate: Sequence[int],
    indices: Sequence[int],
) -> float:
    template_mean = sum(template[index] for index in indices) / len(indices)
    candidate_mean = sum(candidate[index] for index in indices) / len(indices)
    numerator = 0.0
    template_energy = 0.0
    candidate_energy = 0.0
    for index in indices:
        left = template[index] - template_mean
        right = candidate[index] - candidate_mean
        numerator += left * right
        template_energy += left * left
        candidate_energy += right * right
    denominator = math.sqrt(template_energy * candidate_energy)
    return numerator / denominator if denominator else -1.0


def _sparse_indices(template: Sequence[int], *, maximum: int = 192) -> tuple[int, ...]:
    peak = max((abs(value) for value in template), default=0)
    if peak < 1_000:
        raise AnalysisError("reference marker is missing or below the minimum level")
    useful = [index for index, value in enumerate(template) if abs(value) >= peak * 0.28]
    if len(useful) < 16:
        raise AnalysisError("reference marker has insufficient correlation energy")
    if len(useful) <= maximum:
        return tuple(useful)
    return tuple(
        useful[round(index * (len(useful) - 1) / (maximum - 1))] for index in range(maximum)
    )


def locate_marker_lag(
    reference_samples: Sequence[int],
    capture_samples: Sequence[int],
    *,
    marker_start_frame: int = DEFAULT_MARKER_START_FRAME,
    marker_frames: int = DEFAULT_MARKER_FRAMES,
    minimum_lag_frames: int = 0,
    maximum_lag_frames: int,
    minimum_correlation: float = 0.72,
) -> tuple[int, float]:
    if marker_start_frame < 0 or marker_frames < 32:
        raise AnalysisError("marker boundaries are invalid")
    marker_end = marker_start_frame + marker_frames
    if marker_end > len(reference_samples):
        raise AnalysisError("reference marker lies outside the reference waveform")
    template = reference_samples[marker_start_frame:marker_end]
    indices = _sparse_indices(template)
    last_lag = min(maximum_lag_frames, len(capture_samples) - marker_end)
    if last_lag < minimum_lag_frames:
        raise AnalysisError("capture is too short for the requested marker search")

    coarse_step = max(1, len(template) // 312)
    best_lag = minimum_lag_frames
    best_score = -1.0
    for lag in range(minimum_lag_frames, last_lag + 1, coarse_step):
        candidate = capture_samples[
            marker_start_frame + lag : marker_start_frame + lag + marker_frames
        ]
        score = _normalized_score(template, candidate, indices)
        if score > best_score:
            best_lag, best_score = lag, score

    refine_start = max(minimum_lag_frames, best_lag - coarse_step)
    refine_end = min(last_lag, best_lag + coarse_step)
    for lag in range(refine_start, refine_end + 1):
        candidate = capture_samples[
            marker_start_frame + lag : marker_start_frame + lag + marker_frames
        ]
        score = _normalized_score(template, candidate, indices)
        if score > best_score:
            best_lag, best_score = lag, score
    if best_score < minimum_correlation:
        raise AnalysisError(
            f"capture marker not found: best normalized correlation {best_score:.6f}"
        )
    return best_lag, best_score


def propagate_uncertainty_ms(
    *,
    sample_rate_hz: int,
    generator_ms: float = 0.0,
    capture_ms: float = 0.0,
    baseline_ms: float = 0.0,
    clock_drift_ppm: float = 0.0,
    elapsed_ms: float = 0.0,
) -> dict[str, Any]:
    if sample_rate_hz < 1:
        raise AnalysisError("sample rate must be positive")
    values = (generator_ms, capture_ms, baseline_ms, clock_drift_ppm, elapsed_ms)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise AnalysisError("uncertainty inputs must be finite non-negative values")
    sample_quantization_ms = 500.0 / sample_rate_hz
    drift_ms = elapsed_ms * clock_drift_ppm / 1_000_000.0
    total = math.sqrt(
        sample_quantization_ms**2 + generator_ms**2 + capture_ms**2 + baseline_ms**2 + drift_ms**2
    )
    return {
        "method": "root-sum-square-independent-components",
        "totalMs": total,
        "componentsMs": {
            "sampleQuantization": sample_quantization_ms,
            "generator": generator_ms,
            "capture": capture_ms,
            "baseline": baseline_ms,
            "clockDrift": drift_ms,
        },
    }


def analyze_latency(
    reference: Waveform,
    capture: Waveform,
    *,
    reference_channel: int = 0,
    capture_channel: int = 0,
    marker_start_frame: int = DEFAULT_MARKER_START_FRAME,
    marker_frames: int = DEFAULT_MARKER_FRAMES,
    maximum_lag_ms: float = 2_500.0,
    baseline_latency_ms: float = 0.0,
    generator_uncertainty_ms: float = 0.0,
    capture_uncertainty_ms: float = 0.0,
    baseline_uncertainty_ms: float = 0.0,
    clock_drift_ppm: float = 0.0,
) -> dict[str, Any]:
    _assert_compatible(reference, capture)
    maximum_lag_frames = round(maximum_lag_ms * reference.sample_rate_hz / 1_000.0)
    lag_frames, correlation = locate_marker_lag(
        reference.channel(reference_channel),
        capture.channel(capture_channel),
        marker_start_frame=marker_start_frame,
        marker_frames=marker_frames,
        maximum_lag_frames=maximum_lag_frames,
    )
    observed_ms = lag_frames * 1_000.0 / reference.sample_rate_hz
    corrected_ms = observed_ms - baseline_latency_ms
    if corrected_ms < 0:
        raise AnalysisError(
            "calibration baseline exceeds observed latency; capture clocks or path are inconsistent"
        )
    uncertainty = propagate_uncertainty_ms(
        sample_rate_hz=reference.sample_rate_hz,
        generator_ms=generator_uncertainty_ms,
        capture_ms=capture_uncertainty_ms,
        baseline_ms=baseline_uncertainty_ms,
        clock_drift_ppm=clock_drift_ppm,
        elapsed_ms=observed_ms,
    )
    return {
        "method": "normalized-sparse-cross-correlation",
        "referenceChannel": reference_channel,
        "captureChannel": capture_channel,
        "observedLagFrames": lag_frames,
        "observedLatencyMs": observed_ms,
        "baselineLatencyMs": baseline_latency_ms,
        "correctedLatencyMs": corrected_ms,
        "normalizedCorrelation": correlation,
        "uncertainty": uncertainty,
    }


def _rms(samples: Sequence[int], start: int, end: int) -> float:
    if end <= start:
        return 0.0
    return math.sqrt(sum(samples[index] ** 2 for index in range(start, end)) / (end - start))


def analyze_capture_health(
    reference: Waveform,
    capture: Waveform,
    *,
    latency_frames: int,
    reference_channel: int = 0,
    capture_channel: int = 0,
    block_frames: int | None = None,
    minimum_gap_ms: float = 10.0,
    silence_ratio: float = 0.08,
    discontinuity_delta: int = 24_000,
    clipping_level: int = 32_760,
) -> dict[str, Any]:
    _assert_compatible(reference, capture)
    if latency_frames < 0:
        raise AnalysisError("negative capture latency is not supported")
    ref = reference.channel(reference_channel)
    cap = capture.channel(capture_channel)
    aligned_frames = min(len(ref), len(cap) - latency_frames)
    if aligned_frames <= 0:
        raise AnalysisError("capture does not overlap the reference after alignment")
    block = block_frames or max(1, reference.sample_rate_hz // 200)
    reference_rms = [
        _rms(ref, start, min(aligned_frames, start + block))
        for start in range(0, aligned_frames, block)
    ]
    active_peak = max(reference_rms, default=0.0)
    if active_peak < 500:
        raise AnalysisError("reference contains no measurable programme audio")
    active_threshold = active_peak * 0.05
    missing_blocks: list[tuple[int, int]] = []
    for block_index, start in enumerate(range(0, aligned_frames, block)):
        end = min(aligned_frames, start + block)
        expected = reference_rms[block_index]
        observed = _rms(cap, start + latency_frames, end + latency_frames)
        if expected >= active_threshold and observed < max(64.0, expected * silence_ratio):
            missing_blocks.append((start, end))

    gaps = []
    minimum_gap_frames = math.ceil(minimum_gap_ms * reference.sample_rate_hz / 1_000.0)
    if missing_blocks:
        gap_start, gap_end = missing_blocks[0]
        for start, end in missing_blocks[1:]:
            if start <= gap_end + block:
                gap_end = end
                continue
            if gap_end - gap_start >= minimum_gap_frames:
                gaps.append((gap_start, gap_end))
            gap_start, gap_end = start, end
        if gap_end - gap_start >= minimum_gap_frames:
            gaps.append((gap_start, gap_end))

    clipping = [
        index
        for index, value in enumerate(cap[latency_frames : latency_frames + aligned_frames])
        if abs(value) >= clipping_level
    ]
    discontinuities = []
    aligned_capture = cap[latency_frames : latency_frames + aligned_frames]
    for index in range(1, len(aligned_capture)):
        delta = abs(aligned_capture[index] - aligned_capture[index - 1])
        if delta >= discontinuity_delta:
            discontinuities.append(
                {
                    "frame": index,
                    "timeMs": index * 1_000.0 / reference.sample_rate_hz,
                    "delta": delta,
                }
            )

    gap_documents = [
        {
            "startFrame": start,
            "endFrame": end,
            "startMs": start * 1_000.0 / reference.sample_rate_hz,
            "endMs": end * 1_000.0 / reference.sample_rate_hz,
            "durationMs": (end - start) * 1_000.0 / reference.sample_rate_hz,
        }
        for start, end in gaps
    ]
    return {
        "method": "aligned-block-rms-and-sample-edge-analysis",
        "blockFrames": block,
        "alignedFrames": aligned_frames,
        "unexpectedSilence": gap_documents,
        "audioLossFrame": gap_documents[0]["startFrame"] if gap_documents else None,
        "restorationFrame": gap_documents[0]["endFrame"] if gap_documents else None,
        "audibleGapDurationMs": gap_documents[0]["durationMs"] if gap_documents else 0.0,
        "clipping": {
            "sampleCount": len(clipping),
            "firstFrame": clipping[0] if clipping else None,
        },
        "discontinuities": {
            "count": len(discontinuities),
            "events": discontinuities[:100],
            "truncated": len(discontinuities) > 100,
        },
    }


def _window_score(
    reference: Sequence[int],
    capture: Sequence[int],
    *,
    reference_start: int,
    capture_start: int,
    frames: int,
) -> float:
    if reference_start + frames > len(reference) or capture_start + frames > len(capture):
        return -1.0
    template = reference[reference_start : reference_start + frames]
    candidate = capture[capture_start : capture_start + frames]
    indices = tuple(range(0, frames, max(1, frames // 256)))
    return _normalized_score(template, candidate, indices)


def analyze_channel_mapping(
    reference: Waveform,
    capture: Waveform,
    *,
    latency_frames: int,
    source_positions: Sequence[str] | None = None,
    capture_positions: Sequence[str] | None = None,
    minimum_correlation: float = 0.70,
) -> dict[str, Any]:
    _assert_compatible(reference, capture)
    if capture.channels < reference.channels:
        raise AnalysisError("capture has fewer channels than the channel-identification source")
    source_positions = tuple(
        source_positions or (f"CH{index}" for index in range(reference.channels))
    )
    capture_positions = tuple(
        capture_positions or (f"CH{index}" for index in range(capture.channels))
    )
    if len(source_positions) != reference.channels or len(capture_positions) != capture.channels:
        raise AnalysisError("channel position names do not match waveform channel counts")

    scores = []
    for source_channel in range(reference.channels):
        reference_start = CHANNEL_SLOT_START_FRAME + source_channel * CHANNEL_SLOT_STRIDE_FRAMES
        source = reference.channel(source_channel)
        for capture_channel in range(capture.channels):
            destination = capture.channel(capture_channel)
            score = _window_score(
                source,
                destination,
                reference_start=reference_start,
                capture_start=reference_start + latency_frames,
                frames=CHANNEL_SLOT_ACTIVE_FRAMES,
            )
            scores.append((score, source_channel, capture_channel))

    assigned_sources: set[int] = set()
    assigned_captures: set[int] = set()
    assignments = []
    for score, source_channel, capture_channel in sorted(scores, reverse=True):
        if source_channel in assigned_sources or capture_channel in assigned_captures:
            continue
        assigned_sources.add(source_channel)
        assigned_captures.add(capture_channel)
        assignments.append(
            {
                "sourceChannel": source_channel,
                "sourcePosition": source_positions[source_channel],
                "captureChannel": capture_channel,
                "capturePosition": capture_positions[capture_channel],
                "normalizedCorrelation": score,
                "matched": score >= minimum_correlation,
            }
        )
    assignments.sort(key=lambda item: item["sourceChannel"])
    valid = len(assignments) == reference.channels and all(item["matched"] for item in assignments)
    return {
        "method": "channel-specific-tone-normalized-correlation",
        "valid": valid,
        "assignments": assignments,
        "unmatchedSourceChannels": sorted(set(range(reference.channels)) - assigned_sources),
        "unusedCaptureChannels": sorted(set(range(capture.channels)) - assigned_captures),
    }


def _artifact_document(path: Path, *, retained_path: Path) -> dict[str, Any]:
    return {
        "sourcePath": str(path.resolve()),
        "retainedPath": str(retained_path.resolve()),
        "sizeBytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def retain_analysis_artifacts(
    *,
    reference_path: Path,
    capture_path: Path,
    analysis: dict[str, Any],
    evidence_dir: Path,
    subjective_notes: Sequence[dict[str, Any] | str] = (),
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    retained = []
    for role, source in (("reference", reference_path), ("capture", capture_path)):
        digest = _sha256(source)
        destination = evidence_dir / f"{role}-{digest[:16]}{source.suffix.lower()}"
        if destination.exists() and _sha256(destination) != digest:
            raise AnalysisError(f"retained artifact collision at {destination}")
        if not destination.exists():
            shutil.copyfile(source, destination)
        retained.append({"role": role, **_artifact_document(source, retained_path=destination)})
    document = {
        "schemaVersion": 1,
        "objective": analysis,
        "subjectiveNotes": list(subjective_notes),
        "artifacts": retained,
    }
    output = evidence_dir / "waveform-analysis.json"
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def _load_subjective_notes(path: Path | None) -> list[dict[str, Any] | str]:
    if path is None:
        return []
    document = json.loads(path.read_text())
    notes = document.get("observations") if isinstance(document, dict) else document
    if not isinstance(notes, list) or not all(isinstance(item, (str, dict)) for item in notes):
        raise AnalysisError("subjective notes must be a JSON array or observations array")
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--reference-channel", type=int, default=0)
    parser.add_argument("--capture-channel", type=int, default=0)
    parser.add_argument("--maximum-lag-ms", type=float, default=2_500.0)
    parser.add_argument("--baseline-latency-ms", type=float, default=0.0)
    parser.add_argument("--generator-uncertainty-ms", type=float, default=0.0)
    parser.add_argument("--capture-uncertainty-ms", type=float, default=0.0)
    parser.add_argument("--baseline-uncertainty-ms", type=float, default=0.0)
    parser.add_argument("--clock-drift-ppm", type=float, default=0.0)
    parser.add_argument("--subjective-notes", type=Path)
    parser.add_argument("--analyze-channel-mapping", action="store_true")
    args = parser.parse_args()
    try:
        reference = read_pcm16_wav(args.reference)
        capture = read_pcm16_wav(args.capture)
        latency = analyze_latency(
            reference,
            capture,
            reference_channel=args.reference_channel,
            capture_channel=args.capture_channel,
            maximum_lag_ms=args.maximum_lag_ms,
            baseline_latency_ms=args.baseline_latency_ms,
            generator_uncertainty_ms=args.generator_uncertainty_ms,
            capture_uncertainty_ms=args.capture_uncertainty_ms,
            baseline_uncertainty_ms=args.baseline_uncertainty_ms,
            clock_drift_ppm=args.clock_drift_ppm,
        )
        analysis = {
            "latency": latency,
            "captureHealth": analyze_capture_health(
                reference,
                capture,
                latency_frames=latency["observedLagFrames"],
                reference_channel=args.reference_channel,
                capture_channel=args.capture_channel,
            ),
        }
        if args.analyze_channel_mapping:
            analysis["channelMapping"] = analyze_channel_mapping(
                reference,
                capture,
                latency_frames=latency["observedLagFrames"],
            )
        retained = retain_analysis_artifacts(
            reference_path=args.reference,
            capture_path=args.capture,
            analysis=analysis,
            evidence_dir=args.evidence_dir,
            subjective_notes=_load_subjective_notes(args.subjective_notes),
        )
    except (AnalysisError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(retained, sort_keys=True))


if __name__ == "__main__":
    main()
