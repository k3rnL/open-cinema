#!/usr/bin/env python3
"""List complete, checksum-verified coordinated rollback bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

import yaml

BUNDLE_ID_RE = re.compile(r"^transition-[0-9T]+-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_ARTIFACTS = {
    "application.tar.gz",
    "db.sqlite3",
    "dynamic-state.json",
    "managed-static.tar.gz",
    "processor-binaries.tar.gz",
    "processor-runtime.tar.gz",
    "release-manifest.yml",
    "web.tar.gz",
}
WYREPLUMBER_ARTIFACT = "wyreplumber.tar.gz"
ALL_ARTIFACTS = REQUIRED_ARTIFACTS | {WYREPLUMBER_ARTIFACT}

RESTORE_DECLARATIONS = {
    "application_archive": "application.tar.gz",
    "web_archive": "web.tar.gz",
    "processor_binary_archive": "processor-binaries.tar.gz",
    "processor_runtime_archive": "processor-runtime.tar.gz",
    "managed_static_archive": "managed-static.tar.gz",
    "database": "db.sqlite3",
    "release_manifest": "release-manifest.yml",
}


class BundleError(ValueError):
    """A retained bundle does not form a safe recovery boundary."""


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleError(f"{label} must be a mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_restore(manifest: dict[str, Any], artifact_names: set[str], schema: int) -> None:
    restore = _mapping(manifest.get("restore"), "restore")
    if restore.get("strategy") != "coordinated-full-generation":
        raise BundleError("restore strategy is not coordinated-full-generation")

    # Schema 1 predates the explicit archive declarations.  Schema 2 commits
    # them, so its restore recipe must identify the files it actually retains.
    if schema == 1:
        return
    for key, artifact_name in RESTORE_DECLARATIONS.items():
        if restore.get(key) != artifact_name:
            raise BundleError(f"restore.{key} does not identify {artifact_name}")
    expected_wyreplumber = WYREPLUMBER_ARTIFACT if WYREPLUMBER_ARTIFACT in artifact_names else None
    if restore.get("wyreplumber_archive") != expected_wyreplumber:
        raise BundleError("restore.wyreplumber_archive disagrees with retained artifacts")


def _verify_bundle(bundle: Path) -> None:
    if not BUNDLE_ID_RE.fullmatch(bundle.name):
        raise BundleError("bundle ID has an invalid format")
    if not _directory(bundle):
        raise BundleError("bundle must be a regular non-symlink directory")

    manifest_path = bundle / "manifest.yml"
    ready_path = bundle / "READY"
    if not _regular_file(manifest_path):
        raise BundleError("manifest.yml must be a regular non-symlink file")
    if not _regular_file(ready_path):
        raise BundleError("READY must be a regular non-symlink file")

    try:
        manifest = _mapping(yaml.safe_load(manifest_path.read_bytes()), "manifest")
        ready = _mapping(json.loads(ready_path.read_bytes()), "READY")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise BundleError("manifest.yml or READY cannot be parsed") from error

    schema = manifest.get("schema_version")
    if schema not in (1, 2) or isinstance(schema, bool):
        raise BundleError("unsupported manifest schema")
    if manifest.get("kind") != "open-cinema-coordinated-transition-backup":
        raise BundleError("manifest kind is incorrect")
    if manifest.get("bundle_id") != bundle.name:
        raise BundleError("manifest bundle ID does not match directory")
    if not SHA256_RE.fullmatch(manifest.get("previous_candidate_digest", "")):
        raise BundleError("previous_candidate_digest must be a lowercase SHA-256")

    artifacts = _mapping(manifest.get("artifacts"), "manifest artifacts")
    artifact_names = set(artifacts)
    if schema == 1 and artifact_names != ALL_ARTIFACTS:
        raise BundleError("schema 1 artifacts are incomplete")
    if schema == 2 and not (REQUIRED_ARTIFACTS <= artifact_names <= ALL_ARTIFACTS):
        raise BundleError("schema 2 artifacts are incomplete")
    if any(
        not isinstance(name, str) or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
        for name, digest in artifacts.items()
    ):
        raise BundleError("artifact digests must be lowercase SHA-256 strings")

    _validate_restore(manifest, artifact_names, schema)
    if schema == 2:
        previous_input_mode = manifest.get("previous_input_mode")
        if previous_input_mode not in {"appliance", "development"}:
            raise BundleError("previous_input_mode is invalid")
        if previous_input_mode == "development" and WYREPLUMBER_ARTIFACT not in artifact_names:
            raise BundleError("development bundles require a WyrePlumber source archive")

    if ready != artifacts:
        raise BundleError("READY does not exactly match manifest artifacts")
    for artifact_name, expected_digest in artifacts.items():
        artifact_path = bundle / artifact_name
        if not _regular_file(artifact_path):
            raise BundleError(f"{artifact_name} must be a regular non-symlink file")
        if _sha256(artifact_path) != expected_digest:
            raise BundleError(f"{artifact_name} digest does not match")


def inspect_root(root: Path | str) -> dict[str, list[str]]:
    """Inspect immediate ``transition-*`` entries under *root*.

    A malformed entry is reported as rejected, rather than making an otherwise
    useful inventory fail.  The root itself is intentionally strict.
    """

    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"rollback root is not a directory: {root_path}")

    verified: list[str] = []
    rejected: list[str] = []
    try:
        entries = sorted(
            (entry for entry in root_path.iterdir() if entry.name.startswith("transition-")),
            key=lambda entry: entry.name,
        )
    except OSError as error:
        raise ValueError(f"cannot inspect rollback root: {root_path}") from error

    for entry in entries:
        try:
            _verify_bundle(entry)
        except (BundleError, OSError):
            rejected.append(entry.name)
        else:
            verified.append(entry.name)
    return {"verifiedBundleIds": verified, "rejectedBundleIds": rejected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="rollback root directory")
    arguments = parser.parse_args(argv)
    try:
        result = inspect_root(arguments.root)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
