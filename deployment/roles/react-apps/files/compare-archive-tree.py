#!/usr/bin/env python3
"""Compare one release archive with an installed regular-file tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath

TREE_MISMATCH_EXIT = 10


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archive_files(path: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            parts = tuple(part for part in relative.parts if part != ".")
            if relative.is_absolute() or ".." in parts or not parts:
                if member.isdir() and not parts:
                    continue
                raise ValueError("archive contains an unsafe member path")
            normalized = PurePosixPath(*parts).as_posix()
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("archive contains a non-regular member")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archive regular file cannot be read")
            if normalized in files:
                raise ValueError("archive contains duplicate normalized paths")
            files[normalized] = digest_bytes(source.read())
    if not files:
        raise ValueError("archive contains no regular files")
    return files


def installed_files(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        return {}
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("installed tree contains a symbolic link")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = digest_bytes(path.read_bytes())
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()

    expected = archive_files(args.archive)
    actual = installed_files(args.root)
    if expected != actual:
        result = {
            "extra": sorted(actual.keys() - expected.keys()),
            "missing": sorted(expected.keys() - actual.keys()),
            "modified": sorted(
                name for name in actual.keys() & expected.keys() if actual[name] != expected[name]
            ),
        }
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        raise SystemExit(TREE_MISMATCH_EXIT)
    print(json.dumps({"fileCount": len(expected), "result": "identical"}, sort_keys=True))


if __name__ == "__main__":
    main()
