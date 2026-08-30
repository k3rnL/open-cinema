from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.finalize_release_manifest import (
    _verified_portable_provenance,
    finalize_manifest,
    validate_finalized_manifest,
)
from scripts.verify_release_dist import verify_tag

ROOT = Path(__file__).parents[1]


def test_checked_in_release_template_is_exact_and_not_directly_promotable() -> None:
    document = yaml.safe_load((ROOT / "deployment" / "release-manifest.yml").read_text())

    assert document["release_id"] == "open-cinema-0.3.7-candidate"
    assert document["input_mode"] == "appliance"
    assert document["status"] == "experimental"
    assert document["promotable"] is False
    assert "not deployable" in document["candidate_notice"]
    assert all("not deployable" not in item for item in document["limitations"])

    components = document["components"]
    assert components["open_cinema"] == {
        "version": "0.3.7",
        "repository": "k3rnL/open-cinema",
        "source_mode": "tag-build-finalization-placeholder",
        "immutable": False,
    }
    assert components["wyreplumber"]["immutable"] is True
    assert components["wyreplumber"]["commit"] == ("9d55ab1200ee7c484743fe57339a1f56d2c9fcd1")
    assert components["wyreplumber"]["artifacts"][0]["sha256"] == (
        "cfb92cd7f407c87717f1f539ff3e04573d0cd2224ef744f8efb847a7938e05fd"
    )
    assert components["management_ui"]["source_mode"] == "coordinated-release-mirror"
    assert components["pcm_auto_decoder"]["source_mode"] == "coordinated-release-mirror"
    assert components["camilladsp"]["immutable"] is False
    assert components["pycamilladsp"]["immutable"] is False


def test_retained_v032_appliance_manifest_is_exact_and_promotable() -> None:
    manifest_path = ROOT / "deployment" / "releases" / "open-cinema-0.3.2.yml"
    manifest_bytes = manifest_path.read_bytes()
    document = yaml.safe_load(manifest_bytes)

    assert hashlib.sha256(manifest_bytes).hexdigest() == (
        "c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2"
    )
    assert document["release_id"] == "open-cinema-0.3.2"
    assert document["finalized_by"] == {
        "repository": "k3rnL/open-cinema",
        "commit": "4ccda8e6165da6484ac0b7590ca6f03f8f4226f6",
        "tag": "v0.3.2",
        "workflow_run": "https://github.com/k3rnL/open-cinema/actions/runs/33021891788",
    }
    validate_finalized_manifest(document)


def test_release_workflow_installs_manifest_tooling_before_finalization() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    install = 'uv pip install --system "PyYAML==6.0.3"'
    finalization = "Generate provenance and finalize the coordinated manifest"
    assert install in workflow
    assert workflow.index(install) < workflow.index(finalization)


def test_release_workflow_verifies_public_immutability_with_its_scoped_token() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    publish = "Publish the complete immutable release"
    verify = "Verify the published release is immutable"
    assert "/immutable-releases" not in workflow
    assert '"repos/$GITHUB_REPOSITORY/releases/tags/$GITHUB_REF_NAME"' in workflow
    assert 'has("immutable")' in workflow
    assert 'case "$immutable" in' in workflow
    assert "repos/$GITHUB_REPOSITORY/releases/$release_id" in workflow
    assert workflow.index("false)") < workflow.index("--method DELETE")
    assert workflow.index("--method DELETE") < workflow.index("*)")
    assert workflow.index(publish) < workflow.index(verify)


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
    repository = f"example/{name}"
    kind = {
        "open_cinema": "python-wheel",
        "wyreplumber": "python-wheel",
        "management_ui": "admin-ui-archive",
        "pcm_auto_decoder": "native-archive",
        "camilladsp": "native-archive",
        "pycamilladsp": "python-wheel",
    }[name]
    suffix = ".whl" if kind == "python-wheel" else ".tar.gz"
    artifact_name = f"{name}-1.2.3{suffix}"
    platform: dict[str, object] = {
        "distribution_family": "any",
        "architecture": "any",
    }
    if kind == "python-wheel":
        platform["python_abi"] = "py3"
    if kind == "native-archive":
        platform.update(
            {
                "distribution_family": "Debian",
                "distribution_major": 13,
                "distribution_codename": "trixie",
                "architecture": "aarch64",
            }
        )
    if name == "wyreplumber":
        platform.update(
            {
                "distribution_family": "Debian",
                "distribution_major": 13,
                "distribution_codename": "trixie",
                "architecture": "aarch64",
                "python_abi": "cp313",
                "wireplumber_api_family": "0.5",
            }
        )
    return {
        "version": "1.2.3",
        "repository": repository,
        "source_mode": "github-release-assets",
        "tag": "v1.2.3",
        "commit": "c" * 40,
        "immutable": True,
        "artifacts": [
            {
                "name": artifact_name,
                "kind": kind,
                "url": (
                    f"https://github.com/{repository}/releases/download/v1.2.3/" f"{artifact_name}"
                ),
                "sha256": "b" * 64,
                "platform": platform,
                "provenance_ref": provenance_ref,
            }
        ],
        "provenance": {
            "repository": f"example/{name}",
            "commit": "c" * 40,
            "tag": "v1.2.3",
            "workflow_run": "https://github.example/actions/runs/1",
            "url": (
                f"https://github.com/{repository}/releases/download/v1.2.3/"
                f"{name}.provenance.json"
            ),
            "sha256": "d" * 64,
        },
    }


def replacement_rollback() -> dict[str, object]:
    return {
        "strategy": "private-full-generation-replacement",
        "close_window": False,
        "previous": {
            "kind": "private-replacement-baseline",
            "first_release_exception": True,
            "receipt_id": "replacement-v1",
            "receipt_path": "rollback-baselines/replacement-v1.yml",
            "receipt_sha256": "f" * 64,
            "retrieval_ref": "inventory-private:replacement-v1",
            "public": False,
            "verified": True,
        },
    }


def finalized_by() -> dict[str, str]:
    return {
        "repository": "example/open_cinema",
        "commit": "c" * 40,
        "tag": "v1.2.3",
        "workflow_run": "https://github.com/example/open_cinema/actions/runs/42",
    }


def write_portable_provenance(
    path: Path,
    *,
    artifact_path: Path,
    project: str,
    repository: str,
    version: str,
    commit: str = "e" * 40,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "project": project,
                "repository": repository,
                "commit": commit,
                "tag": f"v{version}",
                "workflowRun": "https://github.example/actions/runs/84",
                "artifacts": [
                    {
                        "name": artifact_path.name,
                        "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                        "sizeBytes": artifact_path.stat().st_size,
                    }
                ],
            }
        )
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("repository", "provenance repository"),
        ("tag", "provenance tag"),
        ("name", "exactly one record"),
        ("digest", "digest mismatch"),
        ("size", "size mismatch"),
    ],
)
def test_portable_dependency_provenance_rejects_disagreement(
    tmp_path: Path, mutation: str, message: str
) -> None:
    artifact_path = tmp_path / "dependency-1.2.3.tar.gz"
    artifact_path.write_bytes(b"dependency")
    provenance_path = tmp_path / "dependency-provenance.json"
    write_portable_provenance(
        provenance_path,
        artifact_path=artifact_path,
        project="dependency",
        repository="example/dependency",
        version="1.2.3",
    )
    document = json.loads(provenance_path.read_text())
    if mutation == "repository":
        document["repository"] = "example/wrong"
    elif mutation == "tag":
        document["tag"] = "v9.9.9"
    elif mutation == "name":
        document["artifacts"][0]["name"] = "wrong.tar.gz"
    elif mutation == "digest":
        document["artifacts"][0]["sha256"] = "0" * 64
    elif mutation == "size":
        document["artifacts"][0]["sizeBytes"] += 1
    provenance_path.write_text(json.dumps(document))

    with pytest.raises(AssertionError, match=message):
        _verified_portable_provenance(
            path=provenance_path,
            artifact_path=artifact_path,
            project="dependency",
            repository="example/dependency",
            version="1.2.3",
        )


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
    pycamilladsp_wheel = tmp_path / "camilladsp-1.2.3-py3-none-any.whl"
    pycamilladsp_wheel.write_bytes(b"pycamilladsp wheel")
    pycamilladsp_provenance = tmp_path / "pycamilladsp-provenance.json"
    write_portable_provenance(
        pycamilladsp_provenance,
        artifact_path=pycamilladsp_wheel,
        project="pycamilladsp",
        repository="example/pycamilladsp",
        version="1.2.3",
    )
    camilladsp_archive = tmp_path / "camilladsp-1.2.3.tar.gz"
    camilladsp_archive.write_bytes(b"camilladsp archive")
    camilladsp_provenance = tmp_path / "camilladsp-provenance.json"
    write_portable_provenance(
        camilladsp_provenance,
        artifact_path=camilladsp_archive,
        project="camilladsp",
        repository="example/camilladsp",
        version="1.2.3",
    )
    dependency_components = {
        name: immutable_component(name)
        for name in (
            "wyreplumber",
            "management_ui",
            "pcm_auto_decoder",
            "camilladsp",
            "pycamilladsp",
        )
    }
    dependency_components["camilladsp"]["artifacts"][0]["sha256"] = hashlib.sha256(
        camilladsp_archive.read_bytes()
    ).hexdigest()
    ui_component = dependency_components["management_ui"]
    ui_artifact = tmp_path / ui_component["artifacts"][0]["name"]
    ui_artifact.write_bytes(b"management ui archive")
    ui_provenance = tmp_path / "management-ui-provenance.json"
    ui_provenance.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "project": "management-ui",
                "version": "1.2.3",
                "repository": "example/management_ui",
                "tag": "v1.2.3",
                "commit": "c" * 40,
                "workflowRun": "https://github.example/actions/runs/1",
                "artifact": ui_artifact.name,
                "sha256": hashlib.sha256(ui_artifact.read_bytes()).hexdigest(),
            }
        )
    )
    ui_component["source_mode"] = "coordinated-release-mirror"
    ui_component["artifacts"][0]["sha256"] = hashlib.sha256(ui_artifact.read_bytes()).hexdigest()
    ui_component["provenance"]["url"] = (
        "https://github.com/example/management_ui/releases/download/v1.2.3/" + ui_provenance.name
    )
    ui_component["provenance"]["sha256"] = hashlib.sha256(ui_provenance.read_bytes()).hexdigest()

    decoder_component = dependency_components["pcm_auto_decoder"]
    decoder_artifact = tmp_path / decoder_component["artifacts"][0]["name"]
    decoder_artifact.write_bytes(b"decoder archive")
    decoder_provenance = tmp_path / "decoder-provenance.json"
    decoder_provenance.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "project": "pcm-auto-decoder",
                "version": "1.2.3",
                "tag": "v1.2.3",
                "source": {
                    "repository": "example/pcm_auto_decoder",
                    "commit": "c" * 40,
                },
                "build": {"runUrl": "https://github.example/actions/runs/1"},
                "artifact": {
                    "name": decoder_artifact.name,
                    "sha256": hashlib.sha256(decoder_artifact.read_bytes()).hexdigest(),
                },
            }
        )
    )
    decoder_component["source_mode"] = "coordinated-release-mirror"
    decoder_component["artifacts"][0]["sha256"] = hashlib.sha256(
        decoder_artifact.read_bytes()
    ).hexdigest()
    decoder_component["provenance"]["url"] = (
        "https://github.com/example/pcm_auto_decoder/releases/download/v1.2.3/"
        + decoder_provenance.name
    )
    decoder_component["provenance"]["sha256"] = hashlib.sha256(
        decoder_provenance.read_bytes()
    ).hexdigest()
    template = tmp_path / "template.yml"
    template.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "release_id": "open-cinema-candidate",
                "input_mode": "development",
                "status": "experimental",
                "candidate_notice": "This tag-build template is not deployable.",
                "platform": {"distribution_codename": "trixie"},
                "contracts": {"audio_api": "/api/audio/v1"},
                "components": {
                    "open_cinema": {"version": "0.3.0"},
                    **dependency_components,
                },
                "rollback": replacement_rollback(),
                "limitations": [
                    "This tag-build template is not deployable; use the finalized manifest.",
                    "Quantitative Raspberry Pi performance acceptance remains pending.",
                ],
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
        release_base_url="https://github.com/k3rnL/open-cinema/releases/download/v0.3.0",
        pycamilladsp_wheel=pycamilladsp_wheel,
        pycamilladsp_provenance_path=pycamilladsp_provenance,
        camilladsp_artifact=camilladsp_archive,
        camilladsp_provenance_path=camilladsp_provenance,
    )

    component = document["components"]["open_cinema"]
    assert document["release_id"] == "open-cinema-0.3.0"
    assert document["input_mode"] == "appliance"
    assert document["status"] == "supported"
    assert document["promotable"] is True
    assert "candidate_notice" not in document
    assert document["limitations"] == [
        "Quantitative Raspberry Pi performance acceptance remains pending."
    ]
    assert component["immutable"] is True
    assert component["commit"] == "a" * 40
    assert all("distribution_family" in item["platform"] for item in component["artifacts"])
    assert document["components"]["pycamilladsp"]["commit"] == "e" * 40
    assert document["components"]["camilladsp"]["commit"] == "e" * 40
    assert document["components"]["camilladsp"]["artifacts"][0]["url"].startswith(
        "https://github.com/k3rnL/open-cinema/releases/download/v0.3.0/"
    )
    assert document["components"]["management_ui"]["artifacts"][0]["url"].startswith(
        "https://github.com/k3rnL/open-cinema/releases/download/v0.3.0/"
    )
    assert document["components"]["pcm_auto_decoder"]["artifacts"][0]["url"].startswith(
        "https://github.com/k3rnL/open-cinema/releases/download/v0.3.0/"
    )
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
                "rollback": replacement_rollback(),
                "finalized_by": finalized_by(),
            }
        )


def test_finalized_manifest_accepts_per_artifact_provenance() -> None:
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
    ui = components["management_ui"]
    base_provenance = ui["provenance"]
    ui["provenance"] = {
        "admin": base_provenance,
        "on_box": {
            **base_provenance,
            "url": base_provenance["url"].replace("provenance", "on-box-provenance"),
        },
    }
    ui["artifacts"].append(
        {
            **ui["artifacts"][0],
            "name": "management_ui-on-box-1.2.3.tar.gz",
            "url": "https://github.com/example/management_ui/releases/download/v1.2.3/management_ui-on-box-1.2.3.tar.gz",
            "provenance_ref": "components.management_ui.provenance.on_box",
        }
    )
    ui["artifacts"][0]["provenance_ref"] = "components.management_ui.provenance.admin"

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
            "rollback": replacement_rollback(),
            "finalized_by": finalized_by(),
        }
    )


def test_finalized_manifest_rejects_a_coordinated_identity_different_from_open_cinema() -> None:
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
    coordinated_identity = finalized_by()
    coordinated_identity["tag"] = "v9.9.9"

    with pytest.raises(
        AssertionError,
        match=r"finalized_by\.tag must agree with components\.open_cinema\.tag",
    ):
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
                "rollback": replacement_rollback(),
                "finalized_by": coordinated_identity,
            }
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda components: components["wyreplumber"]["artifacts"][0].update(
                {
                    "url": components["wyreplumber"]["artifacts"][0]["url"].replace(
                        "/v1.2.3/", "/v9.9.9/"
                    )
                }
            ),
            "must use declared release",
        ),
        (
            lambda components: components["wyreplumber"]["artifacts"][0]["platform"].update(
                {"typo_architecture": "x86_64"}
            ),
            "unknown selectors: typo_architecture",
        ),
    ],
)
def test_finalized_manifest_rejects_wrong_release_locations_or_platform_selectors(
    mutation, message: str
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
    mutation(components)

    with pytest.raises(AssertionError, match=message):
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
                "rollback": replacement_rollback(),
                "finalized_by": finalized_by(),
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
                "rollback": replacement_rollback(),
                "finalized_by": finalized_by(),
            }
        )
