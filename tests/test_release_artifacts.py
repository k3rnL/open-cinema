from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.finalize_release_manifest import finalize_manifest, validate_finalized_manifest
from scripts.verify_release_dist import verify_tag

ROOT = Path(__file__).parents[1]


def test_release_tag_must_match_distribution_version() -> None:
    verify_tag("v0.3.0", "0.3.0")

    with pytest.raises(AssertionError, match="!= v0.3.0"):
        verify_tag("v0.2.0", "0.3.0")

    with pytest.raises(AssertionError, match="not v<major>"):
        verify_tag("release-0.3.0", "0.3.0")


def test_portable_provenance_identifies_each_distribution(tmp_path: Path) -> None:
    wheel = tmp_path / "open_cinema-0.3.0-py3-none-any.whl"
    source = tmp_path / "open_cinema-0.3.0.tar.gz"
    wheel.write_bytes(b"wheel bytes")
    source.write_bytes(b"source bytes")
    output = tmp_path / "provenance.json"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "write_release_provenance.py"),
            "--dist-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--repository",
            "k3rnL/open-cinema",
            "--commit",
            "a" * 40,
            "--tag",
            "v0.3.0",
            "--workflow-run",
            "https://github.example/actions/runs/42",
        ],
        check=True,
    )

    document = json.loads(output.read_text())
    assert document == {
        "schemaVersion": 1,
        "project": "open-cinema",
        "repository": "k3rnL/open-cinema",
        "commit": "a" * 40,
        "tag": "v0.3.0",
        "workflowRun": "https://github.example/actions/runs/42",
        "artifacts": [
            {
                "name": wheel.name,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "sizeBytes": wheel.stat().st_size,
            },
            {
                "name": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "sizeBytes": source.stat().st_size,
            },
        ],
    }


def immutable_component(name: str) -> dict[str, object]:
    provenance_ref = f"components.{name}.provenance"
    return {
        "version": "1.2.3",
        "repository": f"example/{name}",
        "source_mode": "github-release-assets",
        "immutable": True,
        "artifacts": [
            {
                "name": f"{name}-1.2.3.tar.gz",
                "url": f"https://github.example/{name}/releases/download/v1.2.3/{name}.tar.gz",
                "sha256": "b" * 64,
                "platform": {"distribution": "debian-13", "architecture": "aarch64"},
                "provenance_ref": provenance_ref,
            }
        ],
        "provenance": {
            "repository": f"example/{name}",
            "commit": "c" * 40,
            "tag": "v1.2.3",
            "workflow_run": "https://github.example/actions/runs/1",
            "url": f"https://github.example/{name}/releases/download/v1.2.3/provenance.json",
            "sha256": "d" * 64,
        },
    }


def test_tag_workflow_finalizes_manifest_from_exact_built_bytes(tmp_path: Path) -> None:
    wheel = tmp_path / "open_cinema-0.3.0-py3-none-any.whl"
    source = tmp_path / "open_cinema-0.3.0.tar.gz"
    wheel.write_bytes(b"wheel")
    source.write_bytes(b"source")
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "project": "open-cinema",
                "repository": "k3rnL/open-cinema",
                "commit": "a" * 40,
                "tag": "v0.3.0",
                "workflowRun": "https://github.example/actions/runs/42",
                "artifacts": [
                    {"name": wheel.name, "sha256": hashlib.sha256(b"wheel").hexdigest()},
                    {"name": source.name, "sha256": hashlib.sha256(b"source").hexdigest()},
                ],
            }
        )
    )
    template = tmp_path / "template.yml"
    template.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "release_id": "open-cinema-candidate",
                "input_mode": "development",
                "status": "experimental",
                "platform": {"distribution_codename": "trixie"},
                "contracts": {"audio_api": "/api/audio/v1"},
                "components": {
                    "open_cinema": {"version": "0.3.0"},
                    **{
                        name: immutable_component(name)
                        for name in (
                            "wyreplumber",
                            "management_ui",
                            "pcm_auto_decoder",
                            "camilladsp",
                            "pycamilladsp",
                        )
                    },
                },
                "rollback": {"strategy": "previous-coordinated-release"},
            },
            sort_keys=False,
        )
    )
    output = tmp_path / "final.yml"

    document = finalize_manifest(
        template=template,
        output=output,
        dist_dir=tmp_path,
        provenance_path=provenance_path,
        repository="k3rnL/open-cinema",
        commit="a" * 40,
        tag="v0.3.0",
        workflow_run="https://github.example/actions/runs/42",
        release_base_url="https://github.example/open-cinema/releases/download/v0.3.0",
    )

    component = document["components"]["open_cinema"]
    assert document["release_id"] == "open-cinema-0.3.0"
    assert document["input_mode"] == "appliance"
    assert document["status"] == "supported"
    assert document["promotable"] is True
    assert component["immutable"] is True
    assert component["commit"] == "a" * 40
    assert [item["sha256"] for item in component["artifacts"]] == [
        hashlib.sha256(b"wheel").hexdigest(),
        hashlib.sha256(b"source").hexdigest(),
    ]
    assert yaml.safe_load(output.read_text()) == document


def test_finalized_manifest_rejects_a_mutable_dependency() -> None:
    components = {
        name: immutable_component(name)
        for name in (
            "open_cinema",
            "wyreplumber",
            "management_ui",
            "pcm_auto_decoder",
            "camilladsp",
            "pycamilladsp",
        )
    }
    components["wyreplumber"]["source_mode"] = "local-dirty-tree"

    with pytest.raises(AssertionError, match="components.wyreplumber.source_mode"):
        validate_finalized_manifest(
            {
                "schema_version": 1,
                "release_id": "open-cinema-0.3.0",
                "input_mode": "appliance",
                "status": "supported",
                "promotable": True,
                "platform": {},
                "contracts": {},
                "components": components,
                "rollback": {},
            }
        )


@pytest.mark.parametrize(
    ("status", "promotable", "message"),
    [
        ("experimental", True, "status must be supported"),
        ("supported", False, "promotable must be true"),
    ],
)
def test_finalized_manifest_rejects_non_promotable_release_state(
    status: str,
    promotable: bool,
    message: str,
) -> None:
    components = {
        name: immutable_component(name)
        for name in (
            "open_cinema",
            "wyreplumber",
            "management_ui",
            "pcm_auto_decoder",
            "camilladsp",
            "pycamilladsp",
        )
    }

    with pytest.raises(AssertionError, match=message):
        validate_finalized_manifest(
            {
                "schema_version": 1,
                "release_id": "open-cinema-0.3.0",
                "input_mode": "appliance",
                "status": status,
                "promotable": promotable,
                "platform": {},
                "contracts": {},
                "components": components,
                "rollback": {},
            }
        )
