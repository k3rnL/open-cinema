#!/usr/bin/env python3
"""Produce a stable content digest for one locally synchronized source tree."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
from pathlib import Path


IGNORED_DIRECTORY_PATTERNS = (
    ".git",
    ".ansible",
    ".hypothesis",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".venv*",
    ".vscode",
    "__pycache__",
    "*.egg-info",
    "build",
    "deployment",
    "docs",
    "media",
    "node_modules",
    "openspec",
    "target",
    "tests",
    "venv",
)
IGNORED_FILE_PATTERNS = (
    ".env",
    "README.md",
    "*.pyc",
    "*.so",
    "*.so.*",
    "*.sqlite3",
    "*.sqlite3-shm",
    "*.sqlite3-wal",
)


def ignored(path: Path, *, directory: bool) -> bool:
    patterns = IGNORED_DIRECTORY_PATTERNS if directory else IGNORED_FILE_PATTERNS
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def digest_tree(root: Path, includes: tuple[Path, ...]) -> str:
    if not root.is_dir():
        raise SystemExit(f"source tree does not exist: {root}")
    digest = hashlib.sha256()
    candidates: set[Path] = set()
    for include in includes or (Path("."),):
        target = root / include
        if target.is_file():
            candidates.add(target)
        elif target.is_dir():
            candidates.update(target.rglob("*"))
        else:
            raise SystemExit(f"included source path does not exist: {target}")
    for candidate in sorted(candidates):
        relative = candidate.relative_to(root)
        if any(ignored(part, directory=True) for part in relative.parents):
            continue
        if candidate.is_dir():
            continue
        if ignored(candidate, directory=False):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        if candidate.is_symlink():
            digest.update(b"link\0")
            digest.update(candidate.readlink().as_posix().encode())
        elif candidate.is_file():
            digest.update(b"file\0")
            with candidate.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--include", action="append", default=[], type=Path)
    arguments = parser.parse_args()
    print(digest_tree(arguments.root.resolve(), tuple(arguments.include)))


if __name__ == "__main__":
    main()
