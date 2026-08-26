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


def development_manifest() -> dict:
    return yaml.safe_load((ROOT / "deployment/release-manifest.yml").read_text())


def artifact(component: str, kind: str, name: str, *, platform: dict | None = None) -> dict:
    return {
        "name": name,
        "kind": kind,
        "url": f"https://example.invalid/releases/download/v1.2.3/{name}",
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
    return {
        "version": "1.2.3",
        "repository": f"example/{name}",
        "source_mode": "github-release-assets",
        "immutable": True,
        "artifacts": artifacts,
        "provenance": {
            "repository": f"example/{name}",
            "commit": "2" * 40,
            "tag": "v1.2.3",
            "workflow_run": "1234",
            "url": f"https://example.invalid/releases/download/v1.2.3/{name}.provenance.json",
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
    return manifest


def test_checked_in_manifest_is_explicit_mutable_development_input() -> None:
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


def test_appliance_manifest_resolves_exact_target_artifacts() -> None:
    result = VALIDATOR.validate_manifest(appliance_manifest(), mode="appliance", target=TARGET)

    assert result["release"] is True
    assert result["mutable"] is False
    assert set(result["selectedArtifacts"]) == set(VALIDATOR.REQUIRED_ARTIFACTS)
    assert result["selectedArtifacts"]["wyreplumber_wheel"]["name"].endswith(
        "linux_aarch64.whl"
    )


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
