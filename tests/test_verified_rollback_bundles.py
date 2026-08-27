from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from deployment.scripts.verify_retained_rollback_bundles import inspect_root

BUNDLE_ID = "transition-20260826T000000-aaaaaaaaaaaa"
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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_bundle(
    root: Path,
    *,
    bundle_id: str = BUNDLE_ID,
    schema: int = 2,
    input_mode: str = "appliance",
    include_wyreplumber: bool = False,
) -> Path:
    bundle = root / bundle_id
    bundle.mkdir()
    names = set(REQUIRED_ARTIFACTS)
    if include_wyreplumber:
        names.add("wyreplumber.tar.gz")
    for name in names:
        (bundle / name).write_bytes(name.encode())
    artifacts = {name: _digest(bundle / name) for name in sorted(names)}
    restore = {"strategy": "coordinated-full-generation"}
    if schema == 2:
        restore.update(
            application_archive="application.tar.gz",
            web_archive="web.tar.gz",
            processor_binary_archive="processor-binaries.tar.gz",
            processor_runtime_archive="processor-runtime.tar.gz",
            managed_static_archive="managed-static.tar.gz",
            database="db.sqlite3",
            release_manifest="release-manifest.yml",
            wyreplumber_archive="wyreplumber.tar.gz" if include_wyreplumber else None,
        )
    manifest = {
        "schema_version": schema,
        "kind": "open-cinema-coordinated-transition-backup",
        "bundle_id": bundle_id,
        "previous_candidate_digest": "b" * 64,
        "artifacts": artifacts,
        "restore": restore,
    }
    if schema == 2:
        manifest.update(
            previous_input_mode=input_mode,
        )
    (bundle / "manifest.yml").write_text(yaml.safe_dump(manifest, sort_keys=True))
    (bundle / "READY").write_text(json.dumps(artifacts, sort_keys=True))
    return bundle


def test_inspect_root_lists_only_complete_verified_bundles(tmp_path: Path) -> None:
    schema_one = _build_bundle(tmp_path, schema=1, include_wyreplumber=True)
    schema_two = _build_bundle(
        tmp_path,
        bundle_id="transition-20260826T000001-bbbbbbbbbbbb",
        input_mode="development",
        include_wyreplumber=True,
    )
    broken = _build_bundle(
        tmp_path,
        bundle_id="transition-20260826T000002-cccccccccccc",
    )
    (broken / "application.tar.gz").write_bytes(b"tampered")

    result = inspect_root(tmp_path)

    assert result == {
        "verifiedBundleIds": [schema_one.name, schema_two.name],
        "rejectedBundleIds": [broken.name],
    }


def test_inspect_root_rejects_invalid_ids_symlinks_and_schema_two_contract_gaps(
    tmp_path: Path,
) -> None:
    invalid = _build_bundle(tmp_path, bundle_id="transition-not-an-id")
    development_without_source = _build_bundle(
        tmp_path,
        bundle_id="transition-20260826T000001-bbbbbbbbbbbb",
        input_mode="development",
    )
    symlinked = _build_bundle(
        tmp_path,
        bundle_id="transition-20260826T000002-cccccccccccc",
    )
    (symlinked / "READY").unlink()
    (symlinked / "READY").symlink_to(symlinked / "manifest.yml")
    malformed_digest = _build_bundle(
        tmp_path,
        bundle_id="transition-20260826T000003-dddddddddddd",
    )
    manifest_path = malformed_digest / "manifest.yml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["previous_candidate_digest"] = "UPPERCASE"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=True))

    result = inspect_root(tmp_path)

    assert result["verifiedBundleIds"] == []
    assert result["rejectedBundleIds"] == sorted(
        [invalid.name, development_without_source.name, symlinked.name, malformed_digest.name]
    )


def test_cli_emits_inventory_but_fails_for_a_non_directory_root(tmp_path: Path) -> None:
    _build_bundle(tmp_path)
    script = Path("deployment/scripts/verify_retained_rollback_bundles.py")

    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "rejectedBundleIds": [],
        "verifiedBundleIds": [BUNDLE_ID],
    }

    non_directory = tmp_path / "not-a-directory"
    non_directory.write_text("x")
    failed = subprocess.run(
        [sys.executable, str(script), "--root", str(non_directory)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode != 0
