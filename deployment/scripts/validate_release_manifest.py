#!/usr/bin/env python3
"""Validate and resolve an Open Cinema deployment release manifest.

The command intentionally runs on the Ansible controller before any role can
change the appliance.  Development manifests describe mutable local trees;
appliance manifests must describe only immutable, content-addressed artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
MUTABLE_MARKERS = (
    "dirty",
    "editable",
    "floating",
    "latest",
    "local-directory",
    "local-source",
    "mutable",
    "working-tree",
)
MUTABLE_URL_MARKERS = (
    "/archive/heads/",
    "/archive/main",
    "/archive/master",
    "/heads/",
    "/latest",
    "/raw/main/",
    "/raw/master/",
)
REQUIRED_COMPONENTS = (
    "open_cinema",
    "wyreplumber",
    "management_ui",
    "pcm_auto_decoder",
    "camilladsp",
    "pycamilladsp",
)
LOCAL_COMPONENTS = (
    "open_cinema",
    "wyreplumber",
    "management_ui",
    "pcm_auto_decoder",
)
REQUIRED_ARTIFACTS = {
    "open_cinema_source": ("open_cinema", "source-archive"),
    "open_cinema_wheel": ("open_cinema", "python-wheel"),
    "wyreplumber_wheel": ("wyreplumber", "python-wheel"),
    "management_ui_admin": ("management_ui", "admin-ui-archive"),
    "management_ui_on_box": ("management_ui", "on-box-ui-archive"),
    "pcm_auto_decoder": ("pcm_auto_decoder", "native-archive"),
    "camilladsp": ("camilladsp", "native-archive"),
    "pycamilladsp_wheel": ("pycamilladsp", "python-wheel"),
}


class ManifestError(ValueError):
    """One or more manifest guarantees were not satisfied."""


@dataclass(frozen=True)
class Target:
    distribution_family: str
    distribution_major: str
    distribution_codename: str
    architecture: str
    python_abi: str
    wireplumber_api_family: str


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path} must be a mapping")
    return value


def _text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _sha256(mapping: dict[str, Any], key: str, path: str) -> str:
    value = _text(mapping, key, path)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ManifestError(f"{path}.{key} must be a lowercase SHA-256 digest")
    return value


def _contains_mutable_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in MUTABLE_MARKERS)


def _immutable_url(value: str, *, artifact_name: str, path: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ManifestError(f"{path} must be an HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ManifestError(f"{path} must not use a mutable query string or fragment")
    lowered = parsed.path.lower()
    if any(marker in lowered for marker in MUTABLE_URL_MARKERS):
        raise ManifestError(f"{path} contains a floating or latest reference")
    if artifact_name and not parsed.path.endswith(f"/{artifact_name}"):
        raise ManifestError(f"{path} must end with the declared artifact name")
    return value


def _normal_architecture(value: str) -> str:
    aliases = {"arm64": "aarch64", "linux_aarch64": "aarch64", "linux_arm64": "aarch64"}
    return aliases.get(value.lower(), value.lower())


def _selector_value_matches(actual: str, expected: str) -> bool:
    actual = actual.lower()
    expected = expected.lower()
    if expected.startswith("cp") and actual in {"py3", "source"}:
        return True
    return actual in {"any", "all", expected}


def _platform_matches(platform: dict[str, Any], target: Target) -> bool:
    comparisons = {
        "distribution_family": target.distribution_family,
        "distribution_major": target.distribution_major,
        "distribution_codename": target.distribution_codename,
        "python_abi": target.python_abi,
        "wireplumber_api_family": target.wireplumber_api_family,
    }
    for key, expected in comparisons.items():
        if key in platform and not _selector_value_matches(str(platform[key]), expected):
            return False
    if "architecture" in platform:
        actual_architecture = _normal_architecture(str(platform["architecture"]))
        if actual_architecture not in {"any", "all", _normal_architecture(target.architecture)}:
            return False
    return True


def _platform_specificity(platform: dict[str, Any]) -> int:
    return sum(str(value).lower() not in {"any", "all"} for value in platform.values())


def _validate_common(document: dict[str, Any], *, target: Target) -> dict[str, dict[str, Any]]:
    if document.get("schema_version") != 1:
        raise ManifestError("schema_version must be 1")
    _text(document, "release_id", "manifest")
    if document.get("status") not in {"experimental", "supported"}:
        raise ManifestError("manifest.status must be experimental or supported")
    if not isinstance(document.get("promotable"), bool):
        raise ManifestError("manifest.promotable must be a boolean")
    if document.get("runtime_profile") != "full":
        raise ManifestError("manifest.runtime_profile must be full")

    platform = _mapping(document.get("platform"), "platform")
    expected_platform = {
        "distribution_family": target.distribution_family,
        "distribution_major": target.distribution_major,
        "distribution_codename": target.distribution_codename,
        "architecture": target.architecture,
    }
    for key, expected in expected_platform.items():
        actual = platform.get(key)
        if actual is None or str(actual).lower() != str(expected).lower():
            raise ManifestError(f"platform.{key} {actual!r} does not select {expected!r}")

    contracts = _mapping(document.get("contracts"), "contracts")
    if str(contracts.get("wireplumber_api_family")) != target.wireplumber_api_family:
        raise ManifestError("contracts.wireplumber_api_family does not match the target")
    for key in (
        "audio_api",
        "orchestration_schema",
        "desired_graph_schema",
        "ui_dto_schema",
        "processing_plugin",
        "processing_driver",
        "wyreplumber_orchestration",
        "wyreplumber_runtime_value_schema",
        "decoder_status_protocol",
        "decoder_output",
    ):
        if key not in contracts:
            raise ManifestError(f"contracts.{key} is required")

    _mapping(document.get("rollback"), "rollback")
    components = _mapping(document.get("components"), "components")
    missing = sorted(set(REQUIRED_COMPONENTS).difference(components))
    if missing:
        raise ManifestError(f"manifest is missing components: {', '.join(missing)}")
    return {name: _mapping(value, f"components.{name}") for name, value in components.items()}


def _validate_artifact(
    *, component_name: str, artifact: dict[str, Any], index: int, target: Target
) -> dict[str, Any]:
    path = f"components.{component_name}.artifacts[{index}]"
    name = _text(artifact, "name", path)
    _text(artifact, "kind", path)
    _immutable_url(_text(artifact, "url", path), artifact_name=name, path=f"{path}.url")
    _sha256(artifact, "sha256", path)
    platform = _mapping(artifact.get("platform"), f"{path}.platform")
    if not platform:
        raise ManifestError(f"{path}.platform must contain explicit selectors")
    expected_ref = f"components.{component_name}.provenance"
    if artifact.get("provenance_ref") != expected_ref:
        raise ManifestError(f"{path}.provenance_ref must be {expected_ref}")
    result = dict(artifact)
    result["matches_target"] = _platform_matches(platform, target)
    return result


def _validate_immutable_component(
    name: str, component: dict[str, Any], *, target: Target
) -> list[dict[str, Any]]:
    path = f"components.{name}"
    if component.get("compatibility_ref"):
        return []
    if component.get("immutable") is not True:
        raise ManifestError(f"{path}.immutable must be true in appliance mode")
    source_mode = _text(component, "source_mode", path)
    if _contains_mutable_marker(source_mode):
        raise ManifestError(f"{path}.source_mode is mutable: {source_mode!r}")
    version = _text(component, "version", path)

    artifacts = component.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError(f"{path}.artifacts must be a non-empty list")
    validated = [
        _validate_artifact(component_name=name, artifact=_mapping(value, f"{path}.artifacts[{index}]"), index=index, target=target)
        for index, value in enumerate(artifacts)
    ]
    names = [artifact["name"] for artifact in validated]
    if len(names) != len(set(names)):
        raise ManifestError(f"{path}.artifacts contains duplicate names")

    provenance = _mapping(component.get("provenance"), f"{path}.provenance")
    repository = _text(provenance, "repository", f"{path}.provenance")
    commit = _text(provenance, "commit", f"{path}.provenance")
    tag = _text(provenance, "tag", f"{path}.provenance")
    _text(provenance, "workflow_run", f"{path}.provenance")
    provenance_name = urlsplit(_text(provenance, "url", f"{path}.provenance")).path.rsplit("/", 1)[-1]
    _immutable_url(
        _text(provenance, "url", f"{path}.provenance"),
        artifact_name=provenance_name,
        path=f"{path}.provenance.url",
    )
    _sha256(provenance, "sha256", f"{path}.provenance")
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise ManifestError(f"{path}.provenance.commit must be a full lowercase Git object ID")
    if tag not in {version, f"v{version}"}:
        raise ManifestError(f"{path}.provenance.tag must agree with version {version}")
    declared_repository = component.get("repository")
    if declared_repository is not None and declared_repository != repository:
        raise ManifestError(f"{path}.repository must agree with provenance.repository")
    return validated


def _select_artifact(
    artifacts: Iterable[dict[str, Any]], *, component: str, kind: str
) -> dict[str, Any]:
    matches = [
        artifact
        for artifact in artifacts
        if artifact.get("kind") == kind and artifact.get("matches_target") is True
    ]
    if not matches:
        raise ManifestError(f"components.{component} has no target-compatible {kind} artifact")
    specificity = max(_platform_specificity(_mapping(item["platform"], "artifact.platform")) for item in matches)
    selected = [
        item
        for item in matches
        if _platform_specificity(_mapping(item["platform"], "artifact.platform")) == specificity
    ]
    if len(selected) != 1:
        names = ", ".join(sorted(item["name"] for item in selected))
        raise ManifestError(f"components.{component} has ambiguous {kind} artifacts: {names}")
    result = dict(selected[0])
    result.pop("matches_target", None)
    result["component"] = component
    return result


def validate_manifest(document: dict[str, Any], *, mode: str, target: Target) -> dict[str, Any]:
    """Validate *document* and return the resolved deployment identity."""

    components = _validate_common(document, target=target)
    declared_mode = document.get("input_mode")
    if declared_mode != mode:
        raise ManifestError(
            f"manifest.input_mode {declared_mode!r} does not match requested mode {mode!r}"
        )

    if mode == "development":
        if document.get("status") != "experimental" or document.get("promotable") is not False:
            raise ManifestError("development manifests must be experimental and non-promotable")
        mutable_components: list[str] = []
        for name in LOCAL_COMPONENTS:
            component = components[name]
            if component.get("immutable") is not False:
                raise ManifestError(f"components.{name}.immutable must be false in development mode")
            if not _contains_mutable_marker(_text(component, "source_mode", f"components.{name}")):
                raise ManifestError(f"components.{name}.source_mode must visibly identify mutable input")
            mutable_components.append(name)

        selected_artifacts: dict[str, dict[str, Any]] = {}
        camilla = components["camilladsp"]
        if isinstance(camilla.get("artifacts"), list):
            validated = [
                _validate_artifact(
                    component_name="camilladsp",
                    artifact=_mapping(value, f"components.camilladsp.artifacts[{index}]"),
                    index=index,
                    target=target,
                )
                for index, value in enumerate(camilla["artifacts"])
            ]
            selected_artifacts["camilladsp"] = _select_artifact(
                validated, component="camilladsp", kind="native-archive"
            )
        return {
            "schemaVersion": 1,
            "inputMode": mode,
            "release": False,
            "mutable": True,
            "mutableComponents": mutable_components,
            "selectedArtifacts": selected_artifacts,
        }

    if mode != "appliance":
        raise ManifestError(f"unsupported input mode: {mode}")
    if document.get("status") != "supported" or document.get("promotable") is not True:
        raise ManifestError("appliance manifests must be supported and promotable")

    validated_artifacts: dict[str, list[dict[str, Any]]] = {}
    for name, component in components.items():
        validated_artifacts[name] = _validate_immutable_component(name, component, target=target)

    selected_artifacts = {
        output_name: _select_artifact(
            validated_artifacts[component_name], component=component_name, kind=kind
        )
        for output_name, (component_name, kind) in REQUIRED_ARTIFACTS.items()
    }
    return {
        "schemaVersion": 1,
        "inputMode": mode,
        "release": True,
        "mutable": False,
        "mutableComponents": [],
        "selectedArtifacts": selected_artifacts,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("development", "appliance"), required=True)
    parser.add_argument("--distribution-family", required=True)
    parser.add_argument("--distribution-major", required=True)
    parser.add_argument("--distribution-codename", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--python-abi", required=True)
    parser.add_argument("--wireplumber-api-family", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        document = _mapping(yaml.safe_load(args.manifest.read_text()), "manifest")
        result = validate_manifest(
            document,
            mode=args.mode,
            target=Target(
                distribution_family=args.distribution_family,
                distribution_major=args.distribution_major,
                distribution_codename=args.distribution_codename,
                architecture=args.architecture,
                python_abi=args.python_abi,
                wireplumber_api_family=args.wireplumber_api_family,
            ),
        )
    except (ManifestError, OSError, yaml.YAMLError) as error:
        print(f"release manifest rejected: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
