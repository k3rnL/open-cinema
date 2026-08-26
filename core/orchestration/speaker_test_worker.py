from __future__ import annotations

import argparse
import json
import math
import signal
import struct
import subprocess
from collections.abc import Iterable

AMPLITUDE = 0.08
CHUNK_FRAMES = 512


def _spa_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def speaker_test_stream_properties(token: str) -> str:
    properties = {
        "node.name": f"open-cinema-speaker-test-{token}",
        "node.description": "Open Cinema speaker test",
        "media.role": "Test",
        "open-cinema.diagnostic": "speaker-test",
        "open-cinema.owner": "open-cinema",
    }
    fields = " ".join(f"{key} = {_spa_value(value)}" for key, value in sorted(properties.items()))
    return f"{{ {fields} }}"


def tone_chunks(
    channels: tuple[str, ...],
    selected_channel: str,
    *,
    rate: int,
    duration_ms: int,
) -> Iterable[bytes]:
    selected = channels.index(selected_channel)
    frame_count = rate * duration_ms // 1000
    ramp_frames = min(rate // 50, max(frame_count // 4, 1))
    frequency = 80.0 if selected_channel == "LFE" else 440.0
    frame_format = "<" + "f" * len(channels)
    for start in range(0, frame_count, CHUNK_FRAMES):
        block = bytearray()
        for frame in range(start, min(start + CHUNK_FRAMES, frame_count)):
            envelope = min(1.0, frame / ramp_frames, (frame_count - 1 - frame) / ramp_frames)
            sample = (
                AMPLITUDE * max(envelope, 0.0) * math.sin(2.0 * math.pi * frequency * frame / rate)
            )
            values = [0.0] * len(channels)
            values[selected] = sample
            block.extend(struct.pack(frame_format, *values))
        yield bytes(block)


def build_pw_cat_command(
    target: str,
    channels: tuple[str, ...],
    rate: int,
    token: str,
) -> list[str]:
    return [
        "pw-cat",
        "--playback",
        "--raw",
        "--target",
        target,
        "--latency",
        "50ms",
        "--rate",
        str(rate),
        "--channels",
        str(len(channels)),
        "--channel-map",
        ",".join(channels),
        "--format",
        "f32",
        "--properties",
        speaker_test_stream_properties(token),
        "-",
    ]


def run(args: argparse.Namespace) -> int:
    channels = tuple(item.strip() for item in args.channel_map.split(",") if item.strip())
    if not channels or len(set(channels)) != len(channels):
        raise ValueError("channel map must contain unique channel positions")
    if args.channel not in channels:
        raise ValueError("selected channel is absent from channel map")
    process = subprocess.Popen(
        build_pw_cat_command(args.target, channels, args.rate, args.token),
        stdin=subprocess.PIPE,
    )

    def terminate(_signum, _frame) -> None:
        process.terminate()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    assert process.stdin is not None
    try:
        for chunk in tone_chunks(
            channels,
            args.channel,
            rate=args.rate,
            duration_ms=args.duration_ms,
        ):
            process.stdin.write(chunk)
        process.stdin.close()
    except BrokenPipeError:
        pass
    return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Play one bounded Open Cinema speaker test")
    parser.add_argument("--target", required=True)
    parser.add_argument("--channel-map", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--rate", required=True, type=int, choices=range(8000, 384001))
    parser.add_argument("--duration-ms", required=True, type=int, choices=range(250, 5001))
    parser.add_argument("--token", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
