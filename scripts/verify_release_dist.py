#!/usr/bin/env python3
"""Verify Open Cinema wheel/sdist identity and required runtime resources."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

CONTRACTS = (
    "audio-condition-v1.schema.json",
    "audio-orchestration-v1.yml",
    "audio-signal-descriptor-v1.schema.json",
    "desired-audio-graph-v1.schema.json",
)


def _single(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise AssertionError(f"expected exactly one {label}, found {len(paths)}")
    return paths[0]


def _metadata_version(metadata: str) -> str:
    parsed = Parser().parsestr(metadata)
    version = parsed.get("Version")
    if not version:
        raise AssertionError("distribution metadata has no Version field")
    return version


def verify_wheel(path: Path, expected_version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for contract in CONTRACTS:
            required = f"contracts/{contract}"
            if required not in names:
                raise AssertionError(f"wheel is missing {required}")
        if "opencinema/version.py" not in names:
            raise AssertionError("wheel is missing opencinema/version.py")

        metadata_name = _single(
            [Path(name) for name in names if name.endswith(".dist-info/METADATA")],
            "wheel METADATA file",
        )
        version = _metadata_version(archive.read(str(metadata_name)).decode())
        if version != expected_version:
            raise AssertionError(f"wheel metadata version {version!r} != {expected_version!r}")

        licenses = [
            name for name in names if ".dist-info/licenses/" in name and name.endswith("/LICENSE")
        ]
        if len(licenses) != 1:
            raise AssertionError("wheel must contain exactly one packaged LICENSE")

        for contract in CONTRACTS:
            if contract.endswith(".json"):
                json.loads(archive.read(f"contracts/{contract}"))


def verify_sdist(path: Path, expected_version: str) -> None:
    expected_root = f"open_cinema-{expected_version}"
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
        for relative in (
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "opencinema/version.py",
            *(f"contracts/{contract}" for contract in CONTRACTS),
        ):
            required = f"{expected_root}/{relative}"
            if required not in names:
                raise AssertionError(f"source archive is missing {required}")

        pkg_info = archive.extractfile(f"{expected_root}/PKG-INFO")
        if pkg_info is None:
            raise AssertionError("source archive is missing PKG-INFO")
        version = _metadata_version(pkg_info.read().decode())
        if version != expected_version:
            raise AssertionError(f"source metadata version {version!r} != {expected_version!r}")


def verify_tag(tag: str | None, expected_version: str) -> None:
    if not tag:
        return
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise AssertionError(f"release tag {tag!r} is not v<major>.<minor>.<patch>")
    if tag != f"v{expected_version}":
        raise AssertionError(f"release tag {tag!r} != v{expected_version}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--tag")
    args = parser.parse_args()

    wheel = _single(sorted(args.dist_dir.glob("open_cinema-*.whl")), "wheel")
    sdist = _single(sorted(args.dist_dir.glob("open_cinema-*.tar.gz")), "source archive")
    verify_tag(args.tag, args.expected_version)
    verify_wheel(wheel, args.expected_version)
    verify_sdist(sdist, args.expected_version)
    print(f"verified {wheel.name} and {sdist.name} as Open Cinema {args.expected_version}")


if __name__ == "__main__":
    main()
