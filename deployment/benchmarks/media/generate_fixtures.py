#!/usr/bin/env python3
"""Generate deterministic, non-copyrighted benchmark audio fixtures.

PCM waveforms are synthesized with the Python standard library.  FFmpeg is
used only to encode the pinned PCM sources into the decoder formats exercised
by the appliance.  Generated files are addressed by SHA-256 in ``manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SAMPLE_RATE = 48_000
SAMPLE_WIDTH_BYTES = 2
SOURCE_DATE_EPOCH = 0
MARKER_START_FRAME = 4_800
MARKER_CHIP_FRAMES = 96
MARKER_CODE = (1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1)
CHANNEL_FREQUENCIES_HZ = (521, 617, 733, 829, 941, 1_057, 1_171, 1_289)
LAYOUTS = {
    2: ("FL", "FR"),
    6: ("FL", "FR", "FC", "LFE", "SL", "SR"),
    8: ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
}


class FixtureError(RuntimeError):
    """Fixture generation or verification failed."""


@dataclass(frozen=True, slots=True)
class GeneratedAsset:
    fixture_id: str
    path: Path
    media_role: str
    codec: str
    transport: str
    channels: int | None
    channel_layout: str | None
    duration_frames: int | None
    generation: dict[str, Any]
    probe: dict[str, Any]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pcm16(value: float) -> int:
    return max(-32_768, min(32_767, round(value * 32_767)))


def marker_value(frame: int, *, start_frame: int = MARKER_START_FRAME) -> float:
    """Return a phase-coded marker with a sharp, correlation-friendly envelope."""

    relative = frame - start_frame
    marker_frames = len(MARKER_CODE) * MARKER_CHIP_FRAMES
    if relative < 0 or relative >= marker_frames:
        return 0.0
    chip = MARKER_CODE[relative // MARKER_CHIP_FRAMES]
    phase = 2.0 * math.pi * 3_000.0 * (relative / SAMPLE_RATE)
    return chip * math.sin(phase) * 0.78


def _channel_identification_value(frame: int, channel: int) -> float:
    marker = marker_value(frame)
    slot_start = 9_600 + channel * 4_800
    slot_relative = frame - slot_start
    tone = 0.0
    if 0 <= slot_relative < 3_600:
        ramp = min(1.0, slot_relative / 120.0, (3_600 - slot_relative) / 120.0)
        tone = (
            math.sin(
                2.0 * math.pi * CHANNEL_FREQUENCIES_HZ[channel] * (slot_relative / SAMPLE_RATE)
            )
            * 0.42
            * ramp
        )
    return max(-0.95, min(0.95, marker + tone))


def write_channel_identification_wav(path: Path, *, channels: int) -> int:
    if channels not in LAYOUTS:
        raise FixtureError(f"unsupported deterministic channel count: {channels}")
    frame_count = 9_600 + channels * 4_800 + 2_400
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE)
        buffer = bytearray()
        for frame in range(frame_count):
            for channel in range(channels):
                buffer.extend(
                    struct.pack("<h", _pcm16(_channel_identification_value(frame, channel)))
                )
            if len(buffer) >= 256 * 1024:
                output.writeframesraw(buffer)
                buffer.clear()
        output.writeframes(buffer)
    return frame_count


def write_silence_wav(path: Path, *, duration_frames: int = SAMPLE_RATE) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(b"\0" * duration_frames * 2 * SAMPLE_WIDTH_BYTES)
    return duration_frames


def write_adaptive_switch_reference(path: Path, *, duration_frames: int = SAMPLE_RATE * 6) -> int:
    """Write continuous stereo programme audio with markers every 500 ms."""

    path.parent.mkdir(parents=True, exist_ok=True)
    marker_interval = SAMPLE_RATE // 2
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE)
        buffer = bytearray()
        for frame in range(duration_frames):
            marker_start = (frame // marker_interval) * marker_interval + 2_400
            marker = marker_value(frame, start_frame=marker_start) * 0.65
            left = 0.15 * math.sin(2.0 * math.pi * 347.0 * frame / SAMPLE_RATE)
            right = 0.15 * math.sin(2.0 * math.pi * 431.0 * frame / SAMPLE_RATE)
            buffer.extend(struct.pack("<hh", _pcm16(left + marker), _pcm16(right + marker)))
            if len(buffer) >= 256 * 1024:
                output.writeframesraw(buffer)
                buffer.clear()
        output.writeframes(buffer)
    return duration_frames


def write_stable_output_transition_reference(
    path: Path,
    *,
    first_channels: int,
) -> tuple[int, int]:
    """Write an eight-channel expected-output transition ending in stereo menu audio."""

    if first_channels not in {2, 6, 8}:
        raise FixtureError("transition reference requires 2, 6, or 8 source channels")
    first_frames = 9_600 + first_channels * 4_800 + 2_400
    menu_frames = 9_600 + 2 * 4_800 + 2_400
    total_frames = first_frames + menu_frames
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(8)
        output.setsampwidth(SAMPLE_WIDTH_BYTES)
        output.setframerate(SAMPLE_RATE)
        buffer = bytearray()
        for frame in range(total_frames):
            if frame < first_frames:
                local_frame = frame
                active_channels = first_channels
            else:
                local_frame = frame - first_frames
                active_channels = 2
            for channel in range(8):
                value = (
                    _channel_identification_value(local_frame, channel)
                    if channel < active_channels
                    else 0.0
                )
                buffer.extend(struct.pack("<h", _pcm16(value)))
            if len(buffer) >= 256 * 1024:
                output.writeframesraw(buffer)
                buffer.clear()
        output.writeframes(buffer)
    return total_frames, first_frames


def wav_to_raw_s16le(source: Path, destination: Path) -> int:
    with wave.open(str(source), "rb") as stream:
        if stream.getsampwidth() != 2 or stream.getframerate() != SAMPLE_RATE:
            raise FixtureError(f"{source} is not deterministic 48 kHz PCM16")
        frames = stream.getnframes()
        destination.write_bytes(stream.readframes(frames))
        return frames


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise FixtureError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr}"
        )
    return result


def _tool_version(tool: str) -> str:
    result = _run([tool, "-version"])
    return result.stdout.splitlines()[0].strip()


def _encode(
    *,
    ffmpeg: str,
    source: Path,
    destination: Path,
    codec: str,
    bitrate: str,
    muxer: str,
    strict_experimental: bool = False,
) -> list[str]:
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+bitexact",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-flags:a",
        "+bitexact",
        "-c:a",
        codec,
    ]
    if strict_experimental:
        command.extend(["-strict", "experimental"])
    command.extend(["-b:a", bitrate, "-f", muxer, str(destination)])
    _run(command)
    return [
        (
            source.name
            if item == str(source)
            else destination.name if item == str(destination) else item
        )
        for item in command[1:]
    ]


def _encode_unsupported_aac_spdif(
    *, ffmpeg: str, source: Path, destination: Path
) -> list[list[str]]:
    """Wrap synthetic AAC in an IEC-61937 type the decoder does not support."""

    elementary = destination.with_suffix(".temporary.aac")
    encode_command = _encode(
        ffmpeg=ffmpeg,
        source=source,
        destination=elementary,
        codec="aac",
        bitrate="384k",
        muxer="adts",
    )
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+bitexact",
        "-i",
        str(elementary),
        "-map_metadata",
        "-1",
        "-c:a",
        "copy",
        "-f",
        "spdif",
        str(destination),
    ]
    _run(command)
    remux_command = [
        (
            elementary.name
            if item == str(elementary)
            else destination.name if item == str(destination) else item
        )
        for item in command[1:]
    ]
    elementary.unlink()
    return [encode_command, remux_command]


def _probe(ffprobe: str, path: Path) -> dict[str, Any]:
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size,bit_rate:stream=index,codec_name,codec_type,sample_rate,channels,channel_layout",
            "-of",
            "json",
            str(path),
        ]
    )
    document = json.loads(result.stdout)
    streams = []
    for stream in document.get("streams", []):
        streams.append(
            {
                key: stream[key]
                for key in (
                    "index",
                    "codec_name",
                    "codec_type",
                    "sample_rate",
                    "channels",
                    "channel_layout",
                )
                if key in stream
            }
        )
    format_document = document.get("format", {})
    return {
        "tool": _tool_version(ffprobe),
        "streams": streams,
        "format": {
            key: format_document[key]
            for key in ("format_name", "duration", "size", "bit_rate")
            if key in format_document
        },
    }


def _asset_document(asset: GeneratedAsset, *, root: Path) -> dict[str, Any]:
    return {
        "id": asset.fixture_id,
        "path": asset.path.relative_to(root).as_posix(),
        "mediaRole": asset.media_role,
        "codec": asset.codec,
        "transport": asset.transport,
        "sampleRateHz": SAMPLE_RATE if asset.duration_frames is not None else None,
        "channels": asset.channels,
        "channelLayout": asset.channel_layout,
        "durationFrames": asset.duration_frames,
        "durationSeconds": (
            round(asset.duration_frames / SAMPLE_RATE, 9)
            if asset.duration_frames is not None
            else None
        ),
        "sizeBytes": asset.path.stat().st_size,
        "sha256": sha256(asset.path),
        "generation": asset.generation,
        "ffprobe": asset.probe,
    }


def _sequence(
    *,
    sequence_id: str,
    destination: Path,
    fixture_paths: Sequence[tuple[str, Path, str]],
    root: Path,
) -> dict[str, Any]:
    data = bytearray()
    segments = []
    for fixture_id, path, expected_layout in fixture_paths:
        payload = path.read_bytes()
        byte_offset = len(data)
        data.extend(payload)
        segments.append(
            {
                "fixtureId": fixture_id,
                "byteOffset": byte_offset,
                "byteLength": len(payload),
                "transportFrameOffset": byte_offset // 4,
                "expectedDecodedLayout": expected_layout,
                "marker": {
                    "kind": "phase-coded-3000hz-barker13",
                    "sourceFrameOffset": MARKER_START_FRAME,
                },
            }
        )
    destination.write_bytes(data)
    return {
        "id": sequence_id,
        "path": destination.relative_to(root).as_posix(),
        "transport": "stereo-s16le-pcm-or-iec61937",
        "sampleRateHz": SAMPLE_RATE,
        "markerBearing": True,
        "sizeBytes": destination.stat().st_size,
        "sha256": sha256(destination),
        "segments": segments,
    }


def generate(*, output_dir: Path, manifest_path: Path, ffmpeg: str, ffprobe: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in output_dir.iterdir():
        if child.is_file():
            child.unlink()

    assets: list[GeneratedAsset] = []
    pcm_sources: dict[int, Path] = {}
    pcm_frames: dict[int, int] = {}
    layout_names = {2: "stereo", 6: "5.1(side)", 8: "7.1"}
    for channels in (2, 6, 8):
        path = (
            output_dir
            / f"pcm-{layout_names[channels].replace('(side)', '').replace('.', '_')}-channel-id.wav"
        )
        frame_count = write_channel_identification_wav(path, channels=channels)
        pcm_sources[channels] = path
        pcm_frames[channels] = frame_count
        assets.append(
            GeneratedAsset(
                f"pcm-channel-id-{channels}ch",
                path,
                "programme-and-channel-identification",
                "pcm_s16le",
                "wav",
                channels,
                layout_names[channels],
                frame_count,
                {
                    "method": "python-standard-library-synthesis",
                    "marker": "phase-coded-3000hz-barker13",
                    "channelFrequenciesHz": list(CHANNEL_FREQUENCIES_HZ[:channels]),
                },
                _probe(ffprobe, path),
            )
        )

    stereo_raw = output_dir / "pcm-stereo-channel-id.s16le"
    stereo_raw_frames = wav_to_raw_s16le(pcm_sources[2], stereo_raw)
    assets.append(
        GeneratedAsset(
            "pcm-stereo-raw-carrier",
            stereo_raw,
            "decoder-pcm-input",
            "pcm_s16le",
            "raw-stereo-s16le",
            2,
            "stereo",
            stereo_raw_frames,
            {"method": "wav-payload-extraction", "source": pcm_sources[2].name},
            {"status": "not-self-describing", "declaredFormat": "s16le/48000/2"},
        )
    )

    silence = output_dir / "silence-stereo.wav"
    silence_frames = write_silence_wav(silence)
    assets.append(
        GeneratedAsset(
            "controlled-silence",
            silence,
            "safe-output-reference",
            "pcm_s16le",
            "wav",
            2,
            "stereo",
            silence_frames,
            {"method": "zero-filled-pcm"},
            _probe(ffprobe, silence),
        )
    )

    no_carrier = output_dir / "no-carrier.s16le"
    no_carrier.write_bytes(b"")
    assets.append(
        GeneratedAsset(
            "no-carrier",
            no_carrier,
            "absent-input-state",
            "none",
            "no-bytes",
            None,
            None,
            None,
            {"method": "empty-stream-sentinel", "carrierState": "absent"},
            {"status": "not-applicable", "reason": "fixture represents absent carrier"},
        )
    )

    encoded_specs = (
        ("ac3-5.1", pcm_sources[6], "ac3", "448k", "spdif", "5.1(side)", False),
        ("eac3-5.1", pcm_sources[6], "eac3", "768k", "spdif", "5.1(side)", False),
        ("dts-5.1", pcm_sources[6], "dca", "1411200", "spdif", "5.1(side)", True),
    )
    encoded_paths: dict[str, Path] = {}
    for fixture_id, source, codec, bitrate, muxer, layout, experimental in encoded_specs:
        suffix = "spdif" if muxer == "spdif" else "aac"
        destination = output_dir / f"{fixture_id}.{suffix}"
        command = _encode(
            ffmpeg=ffmpeg,
            source=source,
            destination=destination,
            codec=codec,
            bitrate=bitrate,
            muxer=muxer,
            strict_experimental=experimental,
        )
        encoded_paths[fixture_id] = destination
        assets.append(
            GeneratedAsset(
                fixture_id,
                destination,
                (
                    "unsupported-decoder-input"
                    if fixture_id.startswith("unsupported")
                    else "encoded-decoder-input"
                ),
                "dts" if codec == "dca" else codec,
                "iec61937" if muxer == "spdif" else "elementary-adts",
                8 if layout == "7.1" else 6,
                layout,
                pcm_frames[8 if layout == "7.1" else 6],
                {
                    "method": "ffmpeg-encoding-of-deterministic-pcm",
                    "source": source.name,
                    "command": command,
                    "bitrate": bitrate,
                    "sourceDateEpoch": SOURCE_DATE_EPOCH,
                },
                _probe(ffprobe, destination),
            )
        )

    unsupported_destination = output_dir / "unsupported-aac-5.1.spdif"
    unsupported_commands = _encode_unsupported_aac_spdif(
        ffmpeg=ffmpeg,
        source=pcm_sources[6],
        destination=unsupported_destination,
    )
    assets.append(
        GeneratedAsset(
            "unsupported-aac-5.1",
            unsupported_destination,
            "unsupported-decoder-input",
            "aac",
            "iec61937-unsupported-data-type",
            6,
            "5.1",
            pcm_frames[6],
            {
                "method": "ffmpeg-aac-encoding-and-iec61937-remux",
                "source": pcm_sources[6].name,
                "commands": unsupported_commands,
                "bitrate": "384k",
                "sourceDateEpoch": SOURCE_DATE_EPOCH,
                "iec61937DataType": "0x07",
                "expectedDecoderOutcome": "unsupported-by-design-safe-silence",
            },
            _probe(ffprobe, unsupported_destination),
        )
    )

    adaptive = output_dir / "adaptive-switch-continuous-stereo.wav"
    adaptive_frames = write_adaptive_switch_reference(adaptive)
    assets.append(
        GeneratedAsset(
            "adaptive-switch-continuous-stereo",
            adaptive,
            "headset-takeover-fallback-reference",
            "pcm_s16le",
            "wav",
            2,
            "stereo",
            adaptive_frames,
            {
                "method": "python-standard-library-synthesis",
                "markerIntervalFrames": SAMPLE_RATE // 2,
                "scenarioEvents": ["disconnect", "reconnect"],
            },
            _probe(ffprobe, adaptive),
        )
    )

    stable_references = []
    for channels in (2, 6, 8):
        path = output_dir / f"stable-output-{channels}ch-to-menu-reference.wav"
        frames, boundary = write_stable_output_transition_reference(path, first_channels=channels)
        stable_references.append(
            {
                "id": f"stable-output-{channels}ch-to-menu",
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": sha256(path),
                "sizeBytes": path.stat().st_size,
                "sampleRateHz": SAMPLE_RATE,
                "channels": 8,
                "durationFrames": frames,
                "transitionFrame": boundary,
                "markerBearing": True,
                "firstLayoutChannels": channels,
                "menuLayoutChannels": 2,
                "ffprobe": _probe(ffprobe, path),
            }
        )

    sequences = [
        _sequence(
            sequence_id="pcm-2.0-to-menu",
            destination=output_dir / "pcm-2.0-to-menu.s16le",
            fixture_paths=(
                ("pcm-stereo-raw-carrier", stereo_raw, "stereo"),
                ("pcm-stereo-raw-carrier", stereo_raw, "stereo-menu"),
            ),
            root=output_dir,
        ),
        _sequence(
            sequence_id="ac3-5.1-to-menu",
            destination=output_dir / "ac3-5.1-to-menu.s16le",
            fixture_paths=(
                ("ac3-5.1", encoded_paths["ac3-5.1"], "5.1(side)"),
                ("pcm-stereo-raw-carrier", stereo_raw, "stereo-menu"),
            ),
            root=output_dir,
        ),
        {
            **next(item for item in stable_references if item["id"] == "stable-output-8ch-to-menu"),
            "id": "pcm-7.1-to-menu-stable-output-reference",
            "transport": "wav-stable-eight-channel-output-reference",
            "segments": [
                {
                    "fixtureId": "pcm-channel-id-8ch",
                    "frameOffset": 0,
                    "frameLength": pcm_frames[8],
                    "expectedDecodedLayout": "7.1",
                    "marker": {
                        "kind": "phase-coded-3000hz-barker13",
                        "sourceFrameOffset": MARKER_START_FRAME,
                    },
                },
                {
                    "fixtureId": "pcm-stereo-menu-stable-output",
                    "frameOffset": pcm_frames[8],
                    "frameLength": pcm_frames[2],
                    "expectedDecodedLayout": "stereo-menu-in-eight-channel-contract",
                    "marker": {
                        "kind": "phase-coded-3000hz-barker13",
                        "sourceFrameOffset": MARKER_START_FRAME,
                    },
                },
            ],
        },
        _sequence(
            sequence_id="ac3-eac3-dts-pcm-cross-format",
            destination=output_dir / "ac3-eac3-dts-pcm-cross-format.s16le",
            fixture_paths=(
                ("ac3-5.1", encoded_paths["ac3-5.1"], "5.1(side)"),
                ("eac3-5.1", encoded_paths["eac3-5.1"], "5.1(side)"),
                ("dts-5.1", encoded_paths["dts-5.1"], "5.1(side)"),
                ("pcm-stereo-raw-carrier", stereo_raw, "stereo-menu"),
            ),
            root=output_dir,
        ),
    ]

    script_path = Path(__file__).resolve()
    document = {
        "schemaVersion": 1,
        "suiteId": "open-cinema-raspberry-audio-v2",
        "fixtureContractId": "pi5-8gb-gab8-native-v1",
        "assetRoot": "generated",
        "license": "CC0-1.0 synthetic waveforms; no third-party programme material",
        "generationProvenance": {
            "script": script_path.name,
            "scriptSha256": sha256(script_path),
            "python": sys.version.split()[0],
            "ffmpeg": _tool_version(ffmpeg),
            "ffprobe": _tool_version(ffprobe),
            "sourceDateEpoch": SOURCE_DATE_EPOCH,
            "sampleRateHz": SAMPLE_RATE,
            "sampleFormat": "signed-16-bit-little-endian",
            "marker": {
                "kind": "phase-coded-3000hz-barker13",
                "startFrame": MARKER_START_FRAME,
                "chipFrames": MARKER_CHIP_FRAMES,
                "code": list(MARKER_CODE),
            },
        },
        "fixtures": [_asset_document(asset, root=output_dir) for asset in assets],
        "transitionSequences": sequences,
        "stableOutputReferences": stable_references,
        "adaptiveRoutingSequence": {
            "fixtureId": "adaptive-switch-continuous-stereo",
            "eventSchedule": [
                {"event": "headset-disconnect", "atFrame": SAMPLE_RATE * 2},
                {"event": "headset-reconnect", "atFrame": SAMPLE_RATE * 4},
            ],
            "expectedAnalysis": ["audio-loss", "restoration", "audible-gap"],
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def verify(*, output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    document = json.loads(manifest_path.read_text())
    failures = []
    if document.get("schemaVersion") != 1:
        failures.append("manifest schemaVersion must be 1")
    if document.get("fixtureContractId") != "pi5-8gb-gab8-native-v1":
        failures.append("manifest fixtureContractId is incompatible")
    recorded_script_digest = document.get("generationProvenance", {}).get("scriptSha256")
    if recorded_script_digest != sha256(Path(__file__).resolve()):
        failures.append("generator script digest differs from generation provenance")
    entries: Iterable[dict[str, Any]] = (
        list(document.get("fixtures", []))
        + list(document.get("transitionSequences", []))
        + list(document.get("stableOutputReferences", []))
    )
    output_root = output_dir.resolve()
    for entry in entries:
        relative_path = Path(entry["path"])
        path = (output_dir / relative_path).resolve()
        if relative_path.is_absolute() or not path.is_relative_to(output_root):
            failures.append(f"unsafe fixture path {entry['path']}")
            continue
        if not path.is_file():
            failures.append(f"missing {entry['path']}")
            continue
        actual = sha256(path)
        if actual != entry.get("sha256"):
            failures.append(f"digest mismatch for {entry['path']}: {actual}")
        if path.stat().st_size != entry.get("sizeBytes"):
            failures.append(f"size mismatch for {entry['path']}")
    if failures:
        raise FixtureError("; ".join(failures))
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "generated")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).parent / "manifest.json")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        document = verify(output_dir=args.output, manifest_path=args.manifest)
        print(f"verified {len(document['fixtures'])} fixtures")
        return
    document = generate(
        output_dir=args.output,
        manifest_path=args.manifest,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print(
        f"generated {len(document['fixtures'])} fixtures and "
        f"{len(document['transitionSequences'])} transition sequences"
    )


if __name__ == "__main__":
    main()
