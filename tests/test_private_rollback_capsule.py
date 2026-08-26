from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest
import yaml

from deployment.scripts.verify_private_rollback_capsule import (
    CapsuleError,
    verify_capsule,
    verify_capsule_against_receipt,
)

BASELINE_ID = "transition-20260826T000000-aaaaaaaaaaaa"
ARCHIVES = {
    "application.tar.gz",
    "managed-static.tar.gz",
    "processor-binaries.tar.gz",
    "processor-runtime.tar.gz",
    "web.tar.gz",
    "wyreplumber.tar.gz",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_nested_archive(path: Path, *, unsafe: bool = False) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        payload = b"fixture"
        member = tarfile.TarInfo("../../escape" if unsafe else "fixture/content.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def build_capsule(tmp_path: Path, *, unsafe_archive: bool = False) -> tuple[Path, int]:
    tmp_path.chmod(0o700)
    bundle = tmp_path / BASELINE_ID
    bundle.mkdir()
    for name in sorted(ARCHIVES):
        write_nested_archive(
            bundle / name,
            unsafe=unsafe_archive and name == "application.tar.gz",
        )

    database = sqlite3.connect(bundle / "db.sqlite3")
    database.execute("CREATE TABLE fixture (value TEXT NOT NULL)")
    database.execute("INSERT INTO fixture VALUES ('private')")
    database.commit()
    database.close()
    (bundle / "dynamic-state.json").write_text("{}\n")
    (bundle / "release-manifest.yml").write_text("schema_version: 1\n")

    artifact_names = sorted(ARCHIVES | {"db.sqlite3", "dynamic-state.json", "release-manifest.yml"})
    artifacts = {name: digest(bundle / name) for name in artifact_names}
    manifest = {
        "schema_version": 1,
        "kind": "open-cinema-coordinated-transition-backup",
        "bundle_id": BASELINE_ID,
        "release_manifest_sha256": artifacts["release-manifest.yml"],
        "artifacts": artifacts,
        "restore": {"strategy": "coordinated-full-generation"},
    }
    (bundle / "manifest.yml").write_text(yaml.safe_dump(manifest, sort_keys=True))
    (bundle / "READY").write_text(json.dumps(artifacts, sort_keys=True) + "\n")

    capsule = tmp_path / f"{BASELINE_ID}.tar.gz"
    with tarfile.open(capsule, mode="w:gz") as archive:
        archive.add(bundle, arcname=BASELINE_ID)
    capsule.chmod(0o400)
    return capsule, len([path for path in bundle.rglob("*") if path.is_file()])


def build_receipt(tmp_path: Path, capsule: Path, file_count: int) -> tuple[Path, dict]:
    with tarfile.open(capsule, mode="r:gz") as archive:
        manifest = archive.extractfile(f"{BASELINE_ID}/manifest.yml").read()
        ready = archive.extractfile(f"{BASELINE_ID}/READY").read()
    document = {
        "schema_version": 1,
        "receipt_id": "replacement-v1",
        "kind": "private-full-generation-replacement",
        "baseline_id": BASELINE_ID,
        "public": False,
        "retention": {
            "appliance_copy": {"present": True, "immutable_flag": True},
            "controller_copy": {
                "present": True,
                "mode": "0400",
                "parent_mode": "0700",
                "immutable_flag": False,
            },
            "minimum_copies": 2,
        },
        "integrity": {
            "capsule_sha256": digest(capsule),
            "capsule_size_bytes": capsule.stat().st_size,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "ready_sha256": hashlib.sha256(ready).hexdigest(),
            "regular_file_count": file_count,
            "restore_artifact_count": 9,
            "nested_archive_count": 6,
            "sqlite_integrity": "ok",
        },
        "verification": {"result": "verified"},
    }
    receipt = tmp_path / "receipt.yml"
    receipt.write_text(yaml.safe_dump(document, sort_keys=True))
    return receipt, document


def test_private_capsule_verifies_full_restore_boundary(tmp_path: Path) -> None:
    capsule, file_count = build_capsule(tmp_path)
    with tarfile.open(capsule, mode="r:gz") as archive:
        manifest = archive.extractfile(f"{BASELINE_ID}/manifest.yml").read()
        ready = archive.extractfile(f"{BASELINE_ID}/READY").read()

    result = verify_capsule(
        capsule,
        baseline_id=BASELINE_ID,
        expected_sha256=digest(capsule),
        expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        expected_ready_sha256=hashlib.sha256(ready).hexdigest(),
        expected_size_bytes=capsule.stat().st_size,
        expected_regular_file_count=file_count,
    )

    assert result["result"] == "verified"
    assert result["restoreArtifactCount"] == 9
    assert result["nestedArchiveCount"] == 6
    assert result["sqliteIntegrity"] == "ok"


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("expected_sha256", "0" * 64, "SHA-256"),
        ("expected_size_bytes", 1, "size"),
        ("expected_regular_file_count", 1, "file count"),
    ],
)
def test_private_capsule_rejects_receipt_disagreement(
    tmp_path: Path, argument: str, value: object, message: str
) -> None:
    capsule, _ = build_capsule(tmp_path)

    with pytest.raises(CapsuleError, match=message):
        verify_capsule(capsule, baseline_id=BASELINE_ID, **{argument: value})


def test_private_capsule_rejects_unsafe_nested_archive(tmp_path: Path) -> None:
    capsule, _ = build_capsule(tmp_path, unsafe_archive=True)

    with pytest.raises(CapsuleError, match="unsafe member path"):
        verify_capsule(capsule, baseline_id=BASELINE_ID)


def test_private_capsule_verifies_every_committed_receipt_assertion(tmp_path: Path) -> None:
    capsule, file_count = build_capsule(tmp_path)
    receipt, _ = build_receipt(tmp_path, capsule, file_count)

    result = verify_capsule_against_receipt(
        capsule,
        receipt,
        expected_receipt_sha256=digest(receipt),
        expected_receipt_id="replacement-v1",
    )

    assert result["baselineId"] == BASELINE_ID
    assert result["receiptId"] == "replacement-v1"
    assert result["receiptSha256"] == digest(receipt)
    assert result["result"] == "verified"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda document: document["integrity"].update(restore_artifact_count=8),
            "restoreArtifactCount",
        ),
        (
            lambda document: document["integrity"].update(nested_archive_count=5),
            "nestedArchiveCount",
        ),
        (lambda document: document["retention"].update(minimum_copies=1), "at least two copies"),
        (lambda document: document["verification"].update(result="failed"), "not marked verified"),
    ],
)
def test_private_capsule_rejects_receipt_contract_disagreement(
    tmp_path: Path, mutator, message: str
) -> None:
    capsule, file_count = build_capsule(tmp_path)
    receipt, document = build_receipt(tmp_path, capsule, file_count)
    mutator(document)
    receipt.write_text(yaml.safe_dump(document, sort_keys=True))

    with pytest.raises(CapsuleError, match=message):
        verify_capsule_against_receipt(
            capsule,
            receipt,
            expected_receipt_sha256=digest(receipt),
            expected_receipt_id="replacement-v1",
        )


def test_private_capsule_rejects_manifest_receipt_identity_or_digest_mismatch(
    tmp_path: Path,
) -> None:
    capsule, file_count = build_capsule(tmp_path)
    receipt, _ = build_receipt(tmp_path, capsule, file_count)

    with pytest.raises(CapsuleError, match="receipt SHA-256"):
        verify_capsule_against_receipt(
            capsule,
            receipt,
            expected_receipt_sha256="0" * 64,
            expected_receipt_id="replacement-v1",
        )
    with pytest.raises(CapsuleError, match="receipt identity"):
        verify_capsule_against_receipt(
            capsule,
            receipt,
            expected_receipt_sha256=digest(receipt),
            expected_receipt_id="replacement-v2",
        )


def test_private_capsule_rejects_controller_permission_drift(tmp_path: Path) -> None:
    capsule, file_count = build_capsule(tmp_path)
    receipt, _ = build_receipt(tmp_path, capsule, file_count)
    capsule.chmod(0o600)

    with pytest.raises(CapsuleError, match="mode does not match"):
        verify_capsule_against_receipt(
            capsule,
            receipt,
            expected_receipt_sha256=digest(receipt),
            expected_receipt_id="replacement-v1",
        )
