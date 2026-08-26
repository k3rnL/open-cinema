#!/usr/bin/env python3
"""Verify a private full-generation rollback capsule without exposing its state."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shutil
import sqlite3
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import yaml

RESTORE_ARTIFACTS = {
    "application.tar.gz",
    "db.sqlite3",
    "dynamic-state.json",
    "managed-static.tar.gz",
    "processor-binaries.tar.gz",
    "processor-runtime.tar.gz",
    "release-manifest.yml",
    "web.tar.gz",
    "wyreplumber.tar.gz",
}
ARCHIVE_ARTIFACTS = {name for name in RESTORE_ARTIFACTS if name.endswith(".tar.gz")}
ALLOWED_ABSOLUTE_SYMLINK_TARGETS = {
    "/etc/nginx/sites-available/open-cinema",
    "/usr/bin/python3",
    "/usr/bin/python3.13",
}


class CapsuleError(ValueError):
    """The capsule cannot prove the declared replacement baseline."""


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapsuleError(f"{path} must be a mapping")
    return value


def _text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CapsuleError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _integer(mapping: dict[str, Any], key: str, path: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CapsuleError(f"{path}.{key} must be a non-negative integer")
    return value


def _mode(value: str, path: str) -> int:
    if len(value) != 4 or any(character not in "01234567" for character in value):
        raise CapsuleError(f"{path} must be a four-digit octal mode")
    return int(value, 8)


def _safe_member(member: tarfile.TarInfo, *, root: str | None = None) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise CapsuleError("archive contains an unsafe member path")
    if root is not None and path.parts[0] != root:
        raise CapsuleError("capsule member is outside the declared baseline directory")
    if member.isdev() or member.isfifo():
        raise CapsuleError("archive contains a device or FIFO member")
    if member.issym() or member.islnk():
        target = PurePosixPath(member.linkname)
        if member.issym() and target.is_absolute():
            if target.as_posix() not in ALLOWED_ABSOLUTE_SYMLINK_TARGETS:
                raise CapsuleError("archive contains an unexpected absolute link target")
            return
        candidate = target if member.islnk() else path.parent / target
        resolved = PurePosixPath(posixpath.normpath(candidate.as_posix()))
        if target.is_absolute() or resolved == PurePosixPath("..") or resolved.parts[:1] == ("..",):
            raise CapsuleError("archive contains an unsafe link target")


def _member_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    member = archive.getmember(name)
    if not member.isfile():
        raise CapsuleError(f"{PurePosixPath(name).name} is not a regular file")
    stream = archive.extractfile(member)
    if stream is None:
        raise CapsuleError(f"cannot read {PurePosixPath(name).name}")
    return stream.read()


def _verify_inner_archive(stream: BinaryIO) -> int:
    count = 0
    with tarfile.open(fileobj=stream, mode="r|gz") as nested:
        for member in nested:
            _safe_member(member)
            count += 1
    if count == 0:
        raise CapsuleError("restore archive is empty")
    return count


def verify_capsule(
    capsule: Path,
    *,
    baseline_id: str,
    expected_sha256: str | None = None,
    expected_manifest_sha256: str | None = None,
    expected_ready_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    expected_regular_file_count: int | None = None,
    expected_mode: int | None = None,
    expected_parent_mode: int | None = None,
) -> dict[str, object]:
    if capsule.is_symlink() or not capsule.is_file():
        raise CapsuleError("private capsule must be a regular non-symlink file")
    mode = stat.S_IMODE(capsule.stat().st_mode)
    if mode & 0o077:
        raise CapsuleError("private capsule grants group or other permissions")
    if expected_mode is not None and mode != expected_mode:
        raise CapsuleError("private capsule mode does not match the retained receipt")
    parent_mode = stat.S_IMODE(capsule.parent.stat().st_mode)
    if expected_parent_mode is not None and parent_mode != expected_parent_mode:
        raise CapsuleError("private capsule parent mode does not match the retained receipt")
    capsule_sha256 = _sha256_path(capsule)
    if expected_sha256 is not None and capsule_sha256 != expected_sha256:
        raise CapsuleError("capsule SHA-256 does not match the retained receipt")
    if expected_size_bytes is not None and capsule.stat().st_size != expected_size_bytes:
        raise CapsuleError("capsule size does not match the retained receipt")

    with tarfile.open(capsule, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _safe_member(member, root=baseline_id)
        regular = [member for member in members if member.isfile()]
        if expected_regular_file_count is not None and len(regular) != expected_regular_file_count:
            raise CapsuleError("capsule file count does not match the retained receipt")
        names = {
            PurePosixPath(member.name).relative_to(baseline_id).as_posix() for member in regular
        }
        manifest_name = f"{baseline_id}/manifest.yml"
        ready_name = f"{baseline_id}/READY"
        if "manifest.yml" not in names or "READY" not in names:
            raise CapsuleError("capsule is missing its manifest or READY record")

        manifest_bytes = _member_bytes(archive, manifest_name)
        ready_bytes = _member_bytes(archive, ready_name)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        ready_sha256 = hashlib.sha256(ready_bytes).hexdigest()
        if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
            raise CapsuleError("inner manifest SHA-256 does not match the retained receipt")
        if expected_ready_sha256 is not None and ready_sha256 != expected_ready_sha256:
            raise CapsuleError("READY SHA-256 does not match the retained receipt")

        manifest = yaml.safe_load(manifest_bytes)
        ready = json.loads(ready_bytes)
        if not isinstance(manifest, dict) or not isinstance(ready, dict):
            raise CapsuleError("manifest and READY records must be mappings")
        if manifest.get("schema_version") != 1:
            raise CapsuleError("unsupported transition manifest schema")
        if manifest.get("kind") != "open-cinema-coordinated-transition-backup":
            raise CapsuleError("transition manifest kind is incorrect")
        if manifest.get("bundle_id") != baseline_id:
            raise CapsuleError("transition manifest baseline identity does not match")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != RESTORE_ARTIFACTS:
            raise CapsuleError("transition manifest does not cover the full restore boundary")
        if ready != artifacts:
            raise CapsuleError("READY and manifest artifact records disagree")
        if set(RESTORE_ARTIFACTS).difference(names):
            raise CapsuleError("capsule is missing one or more restore artifacts")

        nested_member_counts: dict[str, int] = {}
        with tempfile.TemporaryDirectory(prefix="open-cinema-rollback-verify-") as scratch:
            scratch_path = Path(scratch)
            for artifact_name, expected_digest in sorted(artifacts.items()):
                member = archive.getmember(f"{baseline_id}/{artifact_name}")
                source = archive.extractfile(member)
                if source is None:
                    raise CapsuleError(f"cannot read {artifact_name}")
                artifact_path = scratch_path / artifact_name
                with artifact_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                if _sha256_path(artifact_path) != expected_digest:
                    raise CapsuleError(f"restore artifact digest mismatch: {artifact_name}")
                if artifact_name in ARCHIVE_ARTIFACTS:
                    with artifact_path.open("rb") as nested_stream:
                        nested_member_counts[artifact_name] = _verify_inner_archive(nested_stream)

            database_path = scratch_path / "db.sqlite3"
            connection = sqlite3.connect(
                f"file:{database_path.as_posix()}?mode=ro&immutable=1",
                uri=True,
            )
            try:
                connection.execute("PRAGMA query_only=ON")
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
            finally:
                connection.close()
            if integrity != ("ok",):
                raise CapsuleError("retained SQLite database failed integrity_check")

        if manifest.get("release_manifest_sha256") != artifacts["release-manifest.yml"]:
            raise CapsuleError("installed release-manifest identity is not correlated")

    return {
        "schemaVersion": 1,
        "baselineId": baseline_id,
        "capsuleSha256": capsule_sha256,
        "capsuleSizeBytes": capsule.stat().st_size,
        "manifestSha256": manifest_sha256,
        "readySha256": ready_sha256,
        "regularFileCount": len(regular),
        "restoreArtifactCount": len(RESTORE_ARTIFACTS),
        "nestedArchiveCount": len(nested_member_counts),
        "sqliteIntegrity": "ok",
        "result": "verified",
    }


def verify_capsule_against_receipt(
    capsule: Path,
    receipt_path: Path,
    *,
    expected_receipt_sha256: str,
    expected_receipt_id: str,
) -> dict[str, object]:
    """Verify a capsule and every integrity assertion in its public receipt."""

    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise CapsuleError("rollback receipt must be a regular non-symlink file")
    if _sha256_path(receipt_path) != expected_receipt_sha256:
        raise CapsuleError("rollback receipt SHA-256 does not match the release manifest")
    receipt = _mapping(yaml.safe_load(receipt_path.read_text(encoding="utf-8")), "receipt")
    if receipt.get("schema_version") != 1:
        raise CapsuleError("unsupported rollback receipt schema")
    if receipt.get("receipt_id") != expected_receipt_id:
        raise CapsuleError("rollback receipt identity does not match the release manifest")
    if receipt.get("kind") != "private-full-generation-replacement":
        raise CapsuleError("rollback receipt kind is incorrect")
    if receipt.get("public") is not False:
        raise CapsuleError("rollback receipt must describe a private baseline")

    retention = _mapping(receipt.get("retention"), "receipt.retention")
    appliance_copy = _mapping(retention.get("appliance_copy"), "receipt.retention.appliance_copy")
    controller_copy = _mapping(
        retention.get("controller_copy"), "receipt.retention.controller_copy"
    )
    minimum_copies = retention.get("minimum_copies")
    if (
        not isinstance(minimum_copies, int)
        or isinstance(minimum_copies, bool)
        or minimum_copies < 2
    ):
        raise CapsuleError("rollback receipt must retain at least two copies")
    if (
        appliance_copy.get("present") is not True
        or appliance_copy.get("immutable_flag") is not True
    ):
        raise CapsuleError("rollback receipt does not attest an immutable appliance copy")
    if controller_copy.get("present") is not True:
        raise CapsuleError("rollback receipt does not attest a controller copy")

    integrity = _mapping(receipt.get("integrity"), "receipt.integrity")
    verification = _mapping(receipt.get("verification"), "receipt.verification")
    if verification.get("result") != "verified":
        raise CapsuleError("rollback receipt is not marked verified")

    result = verify_capsule(
        capsule,
        baseline_id=_text(receipt, "baseline_id", "receipt"),
        expected_sha256=_text(integrity, "capsule_sha256", "receipt.integrity"),
        expected_manifest_sha256=_text(integrity, "manifest_sha256", "receipt.integrity"),
        expected_ready_sha256=_text(integrity, "ready_sha256", "receipt.integrity"),
        expected_size_bytes=_integer(integrity, "capsule_size_bytes", "receipt.integrity"),
        expected_regular_file_count=_integer(integrity, "regular_file_count", "receipt.integrity"),
        expected_mode=_mode(
            _text(controller_copy, "mode", "receipt.retention.controller_copy"),
            "receipt.retention.controller_copy.mode",
        ),
        expected_parent_mode=_mode(
            _text(controller_copy, "parent_mode", "receipt.retention.controller_copy"),
            "receipt.retention.controller_copy.parent_mode",
        ),
    )
    expected_result = {
        "restoreArtifactCount": _integer(integrity, "restore_artifact_count", "receipt.integrity"),
        "nestedArchiveCount": _integer(integrity, "nested_archive_count", "receipt.integrity"),
        "sqliteIntegrity": _text(integrity, "sqlite_integrity", "receipt.integrity"),
    }
    for field, expected in expected_result.items():
        if result[field] != expected:
            raise CapsuleError(f"{field} does not match the retained receipt")
    result["receiptId"] = expected_receipt_id
    result["receiptSha256"] = expected_receipt_sha256
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capsule", type=Path)
    parser.add_argument("--baseline-id")
    parser.add_argument("--sha256")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--ready-sha256")
    parser.add_argument("--size-bytes", type=int)
    parser.add_argument("--regular-file-count", type=int)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--receipt-id")
    args = parser.parse_args()
    try:
        receipt_arguments = (args.receipt, args.receipt_sha256, args.receipt_id)
        if any(receipt_arguments) and not all(receipt_arguments):
            raise CapsuleError(
                "--receipt, --receipt-sha256, and --receipt-id must be supplied together"
            )
        if args.receipt is not None:
            result = verify_capsule_against_receipt(
                args.capsule,
                args.receipt,
                expected_receipt_sha256=args.receipt_sha256,
                expected_receipt_id=args.receipt_id,
            )
        else:
            if not args.baseline_id:
                raise CapsuleError("--baseline-id is required without --receipt")
            result = verify_capsule(
                args.capsule,
                baseline_id=args.baseline_id,
                expected_sha256=args.sha256,
                expected_manifest_sha256=args.manifest_sha256,
                expected_ready_sha256=args.ready_sha256,
                expected_size_bytes=args.size_bytes,
                expected_regular_file_count=args.regular_file_count,
            )
    except (CapsuleError, OSError, tarfile.TarError, yaml.YAMLError, json.JSONDecodeError) as error:
        raise SystemExit(f"private rollback capsule rejected: {error}") from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
