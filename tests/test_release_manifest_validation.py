from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
VALIDATOR_PATH = ROOT / "deployment/scripts/validate_release_manifest.py"
SPEC = importlib.util.spec_from_file_location("validate_release_manifest", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


TARGET = VALIDATOR.Target(
    distribution_family="Debian",
    distribution_major="13",
    distribution_codename="trixie",
    architecture="aarch64",
    python_abi="cp313",
    wireplumber_api_family="0.5",
)

COMPONENT_VERSIONS = {
    "wyreplumber": "0.2.0",
    "pcm_auto_decoder": "0.2.2",
    "camilladsp": "4.1.3",
    "pycamilladsp": "4.0.0",
}


def development_manifest() -> dict:
    return yaml.safe_load((ROOT / "deployment/development-manifest.yml").read_text())


def artifact(component: str, kind: str, name: str, *, platform: dict | None = None) -> dict:
    version = COMPONENT_VERSIONS.get(component, "1.2.3")
    repository = f"example/{component}"
    return {
        "name": name,
        "kind": kind,
        "url": f"https://github.com/{repository}/releases/download/v{version}/{name}",
        "sha256": "1" * 64,
        "platform": platform
        or {
            "distribution_family": "Debian",
            "distribution_major": 13,
            "distribution_codename": "trixie",
            "architecture": "aarch64",
        },
        "provenance_ref": f"components.{component}.provenance",
    }


def component(name: str, artifacts: list[dict]) -> dict:
    version = COMPONENT_VERSIONS.get(name, "1.2.3")
    return {
        "version": version,
        "repository": f"example/{name}",
        "source_mode": "github-release-assets",
        "tag": f"v{version}",
        "commit": "2" * 40,
        "immutable": True,
        "artifacts": artifacts,
        "provenance": {
            "repository": f"example/{name}",
            "commit": "2" * 40,
            "tag": f"v{version}",
            "workflow_run": "1234",
            "url": (
                f"https://github.com/example/{name}/releases/download/"
                f"v{version}/{name}.provenance.json"
            ),
            "sha256": "3" * 64,
        },
    }


def appliance_manifest() -> dict:
    manifest = copy.deepcopy(development_manifest())
    manifest.update(
        {
            "release_id": "open-cinema-1.2.3",
            "input_mode": "appliance",
            "status": "supported",
            "promotable": True,
        }
    )
    manifest["components"].update(
        {
            "open_cinema": component(
                "open_cinema",
                [
                    artifact(
                        "open_cinema",
                        "source-archive",
                        "open-cinema.tar.gz",
                        platform={
                            "distribution_family": "any",
                            "architecture": "any",
                            "python_abi": "source",
                        },
                    ),
                    artifact(
                        "open_cinema",
                        "python-wheel",
                        "open_cinema-py3-none-any.whl",
                        platform={
                            "distribution_family": "any",
                            "architecture": "any",
                            "python_abi": "py3",
                        },
                    ),
                ],
            ),
            "wyreplumber": component(
                "wyreplumber",
                [
                    artifact(
                        "wyreplumber",
                        "python-wheel",
                        "wyreplumber-cp313-linux_aarch64.whl",
                        platform={
                            "distribution_family": "Debian",
                            "distribution_major": 13,
                            "distribution_codename": "trixie",
                            "architecture": "aarch64",
                            "python_abi": "cp313",
                            "wireplumber_api_family": "0.5",
                        },
                    )
                ],
            ),
            "management_ui": component(
                "management_ui",
                [
                    artifact("management_ui", "admin-ui-archive", "admin.tar.gz"),
                    artifact("management_ui", "on-box-ui-archive", "on-box.tar.gz"),
                ],
            ),
            "pcm_auto_decoder": component(
                "pcm_auto_decoder",
                [artifact("pcm_auto_decoder", "native-archive", "decoder.tar.gz")],
            ),
            "camilladsp": component(
                "camilladsp", [artifact("camilladsp", "native-archive", "camilladsp.tar.gz")]
            ),
            "pycamilladsp": component(
                "pycamilladsp",
                [
                    artifact(
                        "pycamilladsp",
                        "python-wheel",
                        "camilladsp-py3-none-any.whl",
                        platform={
                            "distribution_family": "any",
                            "architecture": "any",
                            "python_abi": "py3",
                        },
                    )
                ],
            ),
        }
    )
    manifest["components"]["pcm_auto_decoder"].update({"backend": "pipewire", "status_protocol": 2})
    manifest["components"]["camilladsp"]["backend"] = "pipewire"
    return manifest


def test_checked_in_development_manifest_is_explicit_mutable_input() -> None:
    result = VALIDATOR.validate_manifest(development_manifest(), mode="development", target=TARGET)

    assert result["release"] is False
    assert result["mutable"] is True
    assert result["mutableComponents"] == [
        "open_cinema",
        "wyreplumber",
        "management_ui",
        "pcm_auto_decoder",
    ]
    assert result["selectedArtifacts"]["camilladsp"]["sha256"] == "ca8b6c" + (
        "c32bda29bd7cb38f7bcda5fcc6f5e69690b3d0efaa23b6c3c05c45696c"
    )


def test_immutable_source_mode_is_not_misclassified_as_mutable() -> None:
    assert not VALIDATOR._contains_mutable_marker("github-immutable-release-assets")
    assert VALIDATOR._contains_mutable_marker("github-mutable-release-assets")


def test_appliance_manifest_resolves_exact_target_artifacts() -> None:
    result = VALIDATOR.validate_manifest(appliance_manifest(), mode="appliance", target=TARGET)

    assert result["release"] is True
    assert result["mutable"] is False
    assert set(result["selectedArtifacts"]) == set(VALIDATOR.REQUIRED_ARTIFACTS)
    assert result["selectedArtifacts"]["wyreplumber_wheel"]["name"].endswith("linux_aarch64.whl")


def test_appliance_manifest_resolves_per_artifact_ui_provenance() -> None:
    manifest = appliance_manifest()
    ui = manifest["components"]["management_ui"]
    shared = ui["provenance"]
    ui["provenance"] = {
        "admin": shared,
        "on_box": {**shared, "url": shared["url"].replace(".provenance", ".on-box.provenance")},
    }
    ui["artifacts"][0]["provenance_ref"] = "components.management_ui.provenance.admin"
    ui["artifacts"][1]["provenance_ref"] = "components.management_ui.provenance.on_box"

    result = VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)

    assert result["selectedArtifacts"]["management_ui_admin"]["provenance_ref"].endswith(".admin")
    assert result["selectedArtifacts"]["management_ui_on_box"]["provenance_ref"].endswith(".on_box")


def test_appliance_manifest_rejects_an_artifact_from_another_release_tag() -> None:
    manifest = appliance_manifest()
    wheel = manifest["components"]["wyreplumber"]["artifacts"][0]
    wheel["url"] = wheel["url"].replace("/v0.2.0/", "/v9.9.9/")

    with pytest.raises(VALIDATOR.ManifestError, match="must use declared release"):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)


def test_appliance_manifest_allows_assets_in_the_finalized_coordinated_mirror() -> None:
    manifest = appliance_manifest()
    manifest["finalized_by"] = {
        "repository": "example/open_cinema",
        "tag": "v1.2.3",
        "commit": "2" * 40,
        "workflow_run": "https://github.com/example/open_cinema/actions/runs/42",
    }
    ui = manifest["components"]["management_ui"]
    ui["source_mode"] = "coordinated-release-mirror"
    for artifact_document in ui["artifacts"]:
        artifact_document["url"] = (
            "https://github.com/example/open_cinema/releases/download/v1.2.3/"
            + artifact_document["name"]
        )
    ui["provenance"]["url"] = (
        "https://github.com/example/open_cinema/releases/download/v1.2.3/"
        "management_ui.provenance.json"
    )

    result = VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)

    assert result["selectedArtifacts"]["management_ui_admin"]["component"] == "management_ui"


def test_appliance_manifest_rejects_a_mirror_release_identity_different_from_open_cinema() -> None:
    manifest = appliance_manifest()
    manifest["finalized_by"] = {
        "repository": "example/another-release",
        "tag": "v1.2.3",
        "commit": "2" * 40,
        "workflow_run": "https://github.com/example/another-release/actions/runs/42",
    }

    with pytest.raises(
        VALIDATOR.ManifestError,
        match=r"finalized_by\.repository must agree with components\.open_cinema\.repository",
    ):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda platform: platform.update({"typo_architecture": platform.pop("architecture")}),
            "unknown selectors: typo_architecture",
        ),
        (lambda platform: platform.pop("architecture"), "missing required selectors: architecture"),
        (lambda platform: platform.pop("python_abi"), "missing required selectors: python_abi"),
        (
            lambda platform: platform.pop("wireplumber_api_family"),
            "missing required selectors: wireplumber_api_family",
        ),
    ],
)
def test_appliance_manifest_rejects_incomplete_or_unknown_native_wheel_selectors(
    mutation, message: str
) -> None:
    manifest = appliance_manifest()
    platform = manifest["components"]["wyreplumber"]["artifacts"][0]["platform"]
    mutation(platform)

    with pytest.raises(VALIDATOR.ManifestError, match=message):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)


@pytest.mark.parametrize(
    ("component_name", "version"),
    (
        ("wyreplumber", "0.1.9"),
        ("pcm_auto_decoder", "0.2.1"),
        ("camilladsp", "5.0.0"),
        ("pycamilladsp", "5.0.0"),
    ),
)
def test_appliance_manifest_rejects_component_outside_compatibility_range(
    component_name: str,
    version: str,
) -> None:
    manifest = appliance_manifest()
    component_document = manifest["components"][component_name]
    component_document["version"] = version
    component_document["tag"] = f"v{version}"
    component_document["provenance"]["tag"] = f"v{version}"

    with pytest.raises(
        VALIDATOR.ManifestError,
        match=rf"components\.{component_name}\.version .* outside compatibility range",
    ):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)


def test_manifest_rejects_another_compatibility_matrix_identity() -> None:
    manifest = appliance_manifest()
    manifest["platform"]["compatibility_matrix"] = "another-matrix"

    with pytest.raises(VALIDATOR.ManifestError, match="compatibility_matrix"):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda manifest: manifest["components"]["open_cinema"].update(
                {"source_mode": "editable-local-directory"}
            ),
            "source_mode is mutable",
        ),
        (
            lambda manifest: manifest["components"]["wyreplumber"]["artifacts"][0].update(
                {"sha256": "unpinned"}
            ),
            "lowercase SHA-256",
        ),
        (
            lambda manifest: manifest["components"]["management_ui"]["artifacts"][0].update(
                {
                    "url": "https://example.invalid/releases/latest/admin.tar.gz",
                }
            ),
            "floating or latest",
        ),
        (
            lambda manifest: manifest.update({"input_mode": "development"}),
            "does not match requested mode",
        ),
        (
            lambda manifest: manifest.update({"status": "experimental"}),
            "must be supported and promotable",
        ),
        (
            lambda manifest: manifest.update({"promotable": False}),
            "must be supported and promotable",
        ),
    ],
)
def test_appliance_manifest_rejects_mutable_or_unpinned_inputs(mutation, message: str) -> None:
    manifest = appliance_manifest()
    mutation(manifest)

    with pytest.raises(VALIDATOR.ManifestError, match=message):
        VALIDATOR.validate_manifest(manifest, mode="appliance", target=TARGET)
