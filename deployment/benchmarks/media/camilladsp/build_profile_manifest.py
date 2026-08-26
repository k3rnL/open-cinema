#!/usr/bin/env python3
"""Generate the deterministic FIR and checksummed CamillaDSP workload registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

import yaml

PROFILE_METADATA = {
    "passthrough-128.yml": {
        "id": "camilladsp-passthrough-128",
        "inputChannels": 8,
        "outputChannels": 8,
        "workload": {"mixers": 0, "iirBiquadsPerChannel": 0, "firTapsPerChannel": 0},
    },
    "stereo-128.yml": {
        "id": "camilladsp-stereo-128",
        "inputChannels": 2,
        "outputChannels": 2,
        "workload": {"mixers": 0, "gainFiltersPerChannel": 1, "firTapsPerChannel": 0},
    },
    "multichannel-128.yml": {
        "id": "camilladsp-multichannel-128",
        "inputChannels": 8,
        "outputChannels": 8,
        "workload": {"mixers": 0, "gainFiltersPerChannel": 1, "firTapsPerChannel": 0},
    },
    "channel-adaptation-128.yml": {
        "id": "camilladsp-channel-adaptation-128",
        "inputChannels": 8,
        "outputChannels": 2,
        "workload": {"mixers": 1, "mixerSourceTerms": 10, "firTapsPerChannel": 0},
    },
    "production-fir-iir-128.yml": {
        "id": "camilladsp-production-fir-iir-128",
        "inputChannels": 8,
        "outputChannels": 8,
        "workload": {"mixers": 0, "iirBiquadsPerChannel": 2, "firTapsPerChannel": 1024},
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_fir(path: Path, *, taps: int = 1024, cutoff_hz: float = 18_000.0) -> None:
    center = (taps - 1) / 2.0
    coefficients = []
    for index in range(taps):
        offset = index - center
        normalized_cutoff = cutoff_hz / 48_000.0
        sinc = (
            2.0 * normalized_cutoff
            if offset == 0
            else math.sin(2.0 * math.pi * normalized_cutoff * offset) / (math.pi * offset)
        )
        window = (
            0.42
            - 0.5 * math.cos(2.0 * math.pi * index / (taps - 1))
            + 0.08 * math.cos(4.0 * math.pi * index / (taps - 1))
        )
        coefficients.append(sinc * window)
    total = sum(coefficients)
    path.write_bytes(b"".join(struct.pack("<f", value / total) for value in coefficients))


def build(root: Path) -> dict:
    fir = root / "production-fir-1024.f32le"
    write_fir(fir)
    profiles = []
    for name, metadata in PROFILE_METADATA.items():
        path = root / name
        document = yaml.safe_load(path.read_text())
        devices = document["devices"]
        if devices["samplerate"] != 48_000 or devices["chunksize"] != 128:
            raise ValueError(f"{name} does not use the benchmark rate and period")
        profiles.append(
            {
                **metadata,
                "path": name,
                "sha256": sha256(path),
                "sizeBytes": path.stat().st_size,
                "sampleRateHz": 48_000,
                "periodFrames": 128,
                "transport": "native-pipewire",
            }
        )
    result = {
        "schemaVersion": 1,
        "fixtureContractId": "pi5-8gb-gab8-native-v1",
        "purpose": "synthetic-performance-workloads-not-room-correction",
        "profiles": profiles,
        "assets": [
            {
                "id": "production-fir-1024",
                "path": fir.name,
                "format": "FLOAT32LE",
                "sampleRateHz": 48_000,
                "taps": 1024,
                "generation": "normalized-18khz-blackman-windowed-sinc",
                "sha256": sha256(fir),
                "sizeBytes": fir.stat().st_size,
            }
        ],
    }
    (root / "profiles.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    result = build(args.root)
    print(f"registered {len(result['profiles'])} CamillaDSP workloads")


if __name__ == "__main__":
    main()
