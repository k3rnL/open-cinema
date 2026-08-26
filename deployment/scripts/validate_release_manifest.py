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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
VERSION_PATTERN = re.compile(r"\d+(?:\.\d+){1,2}")
DEFAULT_COMPATIBILITY_PATH = Path(__file__).resolve().parents[1] / "compatibility.yml"
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
VERSIONED_COMPATIBILITY_COMPONENTS = (
    "wyreplumber",
    "pcm_auto_decoder",
    "camilladsp",
    "pycamilladsp",
)
PLATFORM_SELECTOR_KEYS = frozenset(
    {
        "distribution_family",
        "distribution_major",
        "distribution_codename",
        "architecture",
        "python_abi",
        "wireplumber_api_family",
    }
)
COORDINATED_RELEASE_ASSET_MODES = frozenset(
    {
        "coordinated-release-mirror",
        "upstream-source-built-wheel",
    }
)


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
    return any(
        (
            re.search(r"(?:^|[^a-z0-9])mutable(?:$|[^a-z0-9])", lowered)
            if marker == "mutable"
            else marker in lowered
        )
        for marker in MUTABLE_MARKERS
    )


def _version_tuple(value: str, *, path: str) -> tuple[int, int, int]:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise ManifestError(f"{path} must be a numeric major.minor[.patch] version")
    parts = [int(part) for part in value.split(".")]
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts)  # type: ignore[return-value]


def _validate_compatibility(
    document: dict[str, Any],
    components: dict[str, dict[str, Any]],
    compatibility: dict[str, Any],
) -> None:
    matrix_id = _text(compatibility, "matrix_id", "compatibility")
    platform = _mapping(document.get("platform"), "platform")
    if platform.get("compatibility_matrix") != matrix_id:
        raise ManifestError(
            "platform.compatibility_matrix does not match the loaded compatibility matrix"
        )

    constraints = _mapping(compatibility.get("components"), "compatibility.components")
    for name in VERSIONED_COMPATIBILITY_COMPONENTS:
        component = components[name]
        constraint = _mapping(constraints.get(name), f"compatibility.components.{name}")
        version = _text(component, "version", f"components.{name}")
        minimum = _text(constraint, "minimum", f"compatibility.components.{name}")
        maximum = _text(
            constraint,
            "maximum_exclusive",
            f"compatibility.components.{name}",
        )
        observed_version = _version_tuple(version, path=f"components.{name}.version")
        if not (
            _version_tuple(minimum, path=f"compatibility.components.{name}.minimum")
            <= observed_version
            < _version_tuple(
                maximum,
                path=f"compatibility.components.{name}.maximum_exclusive",
            )
        ):
            raise ManifestError(
                f"components.{name}.version {version} is outside compatibility range "
                f"[{minimum}, {maximum})"
            )

    contracts = _mapping(document.get("contracts"), "contracts")
    wyreplumber = _mapping(constraints.get("wyreplumber"), "compatibility.components.wyreplumber")
    if str(contracts.get("wyreplumber_orchestration")) != str(
        wyreplumber.get("required_api_contract")
    ):
        raise ManifestError("contracts.wyreplumber_orchestration does not match compatibility.yml")

    decoder_constraint = _mapping(
        constraints.get("pcm_auto_decoder"),
        "compatibility.components.pcm_auto_decoder",
    )
    decoder_component = components["pcm_auto_decoder"]
    if str(contracts.get("decoder_status_protocol")) != str(
        decoder_constraint.get("status_protocol")
    ):
        raise ManifestError("contracts.decoder_status_protocol does not match compatibility.yml")
    if decoder_component.get("status_protocol") != decoder_constraint.get("status_protocol"):
        raise ManifestError(
            "components.pcm_auto_decoder.status_protocol does not match compatibility.yml"
        )
    if decoder_component.get("backend") != decoder_constraint.get("backend"):
        raise ManifestError("components.pcm_auto_decoder.backend does not match compatibility.yml")

    camilladsp_constraint = _mapping(
        constraints.get("camilladsp"), "compatibility.components.camilladsp"
    )
    if components["camilladsp"].get("backend") != camilladsp_constraint.get("backend"):
        raise ManifestError("components.camilladsp.backend does not match compatibility.yml")


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


def _github_release_asset_url(
    value: str,
    *,
    repository: str,
    tag: str,
    artifact_name: str,
    path: str,
) -> str:
    """Require one exact GitHub release-asset location for a declared identity."""

    _immutable_url(value, artifact_name=artifact_name, path=path)
    parsed = urlsplit(value)
    expected_path = f"/{repository}/releases/download/{tag}/{artifact_name}"
    if parsed.netloc.lower() != "github.com" or parsed.path != expected_path:
        raise ManifestError(f"{path} must use declared release https://github.com{expected_path}")
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


def _validate_platform_selectors(
    *,
    component_name: str,
    kind: str,
    platform: dict[str, Any],
    path: str,
) -> None:
    unknown = sorted(set(platform).difference(PLATFORM_SELECTOR_KEYS))
    if unknown:
        raise ManifestError(f"{path} contains unknown selectors: {', '.join(unknown)}")

    required = {"distribution_family", "architecture"}
    if kind in {"python-wheel", "source-archive"}:
        required.add("python_abi")
    if kind == "native-archive":
        required.update({"distribution_major", "distribution_codename"})
    if component_name == "wyreplumber":
        required.update(
            {
                "distribution_major",
                "distribution_codename",
                "python_abi",
                "wireplumber_api_family",
            }
        )

    missing = sorted(required.difference(platform))
    if missing:
        raise ManifestError(f"{path} is missing required selectors: {', '.join(missing)}")

    if kind == "native-archive" and str(platform["architecture"]).lower() in {"any", "all"}:
        raise ManifestError(f"{path}.architecture must select one native architecture")
    if component_name == "wyreplumber":
        if str(platform["architecture"]).lower() in {"any", "all"}:
            raise ManifestError(f"{path}.architecture must select one native architecture")
        python_abi = str(platform["python_abi"]).lower()
        if re.fullmatch(r"cp\d+", python_abi) is None:
            raise ManifestError(f"{path}.python_abi must select one CPython ABI")
        if str(platform["wireplumber_api_family"]).lower() in {"any", "all"}:
            raise ManifestError(
                f"{path}.wireplumber_api_family must select one WirePlumber API family"
            )


def _validate_rollback(document: dict[str, Any]) -> None:
    rollback = _mapping(document.get("rollback"), "rollback")
    strategy = _text(rollback, "strategy", "rollback")
    previous = _mapping(rollback.get("previous"), "rollback.previous")
    if strategy == "private-full-generation-replacement":
        if previous.get("kind") != "private-replacement-baseline":
            raise ManifestError("rollback.previous.kind must identify the private replacement")
        if previous.get("first_release_exception") is not True:
            raise ManifestError("private replacement baseline must be a first-release exception")
        _text(previous, "receipt_id", "rollback.previous")
        receipt_path = PurePosixPath(_text(previous, "receipt_path", "rollback.previous"))
        if receipt_path.is_absolute() or ".." in receipt_path.parts:
            raise ManifestError("rollback.previous.receipt_path must be repository-relative")
        _sha256(previous, "receipt_sha256", "rollback.previous")
        retrieval_ref = _text(previous, "retrieval_ref", "rollback.previous")
        if not retrieval_ref.startswith("inventory-private:"):
            raise ManifestError("rollback.previous.retrieval_ref must remain private")
        if previous.get("public") is not False or previous.get("verified") is not True:
            raise ManifestError("private replacement baseline must be non-public and verified")
    elif strategy == "previous-coordinated-release":
        _text(previous, "release_id", "rollback.previous")
        manifest_name = _text(previous, "name", "rollback.previous")
        _immutable_url(
            _text(previous, "url", "rollback.previous"),
            artifact_name=manifest_name,
            path="rollback.previous.url",
        )
        _sha256(previous, "sha256", "rollback.previous")
        if previous.get("retained") is not True:
            raise ManifestError("rollback.previous.retained must be true")
    else:
        raise ManifestError(f"unsupported rollback strategy: {strategy}")


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

    _validate_rollback(document)
    components = _mapping(document.get("components"), "components")
    missing = sorted(set(REQUIRED_COMPONENTS).difference(components))
    if missing:
        raise ManifestError(f"manifest is missing components: {', '.join(missing)}")
    return {name: _mapping(value, f"components.{name}") for name, value in components.items()}


def _validate_artifact(
    *,
    component_name: str,
    artifact: dict[str, Any],
    index: int,
    target: Target,
    provenance_refs: set[str],
    release_repository: str,
    release_tag: str,
) -> dict[str, Any]:
    path = f"components.{component_name}.artifacts[{index}]"
    name = _text(artifact, "name", path)
    kind = _text(artifact, "kind", path)
    _github_release_asset_url(
        _text(artifact, "url", path),
        repository=release_repository,
        tag=release_tag,
        artifact_name=name,
        path=f"{path}.url",
    )
    _sha256(artifact, "sha256", path)
    platform = _mapping(artifact.get("platform"), f"{path}.platform")
    if not platform:
        raise ManifestError(f"{path}.platform must contain explicit selectors")
    _validate_platform_selectors(
        component_name=component_name,
        kind=kind,
        platform=platform,
        path=f"{path}.platform",
    )
    provenance_ref = _text(artifact, "provenance_ref", path)
    if provenance_ref not in provenance_refs:
        expected = ", ".join(sorted(provenance_refs))
        raise ManifestError(f"{path}.provenance_ref must be one of: {expected}")
    result = dict(artifact)
    result["matches_target"] = _platform_matches(platform, target)
    return result


def _validate_immutable_component(
    name: str,
    component: dict[str, Any],
    *,
    target: Target,
    coordinated_release: dict[str, Any] | None,
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
    repository = _text(component, "repository", path)
    commit = _text(component, "commit", path)
    tag = _text(component, "tag", path)
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise ManifestError(f"{path}.commit must be a full lowercase Git object ID")
    if tag != f"v{version}":
        raise ManifestError(f"{path}.tag must agree with version {version}")

    if source_mode in COORDINATED_RELEASE_ASSET_MODES:
        if coordinated_release is None:
            raise ManifestError(
                f"{path}.source_mode requires manifest.finalized_by release identity"
            )
        release_repository = _text(coordinated_release, "repository", "finalized_by")
        release_tag = _text(coordinated_release, "tag", "finalized_by")
    else:
        release_repository = repository
        release_tag = tag

    provenance_path = f"{path}.provenance"
    raw_provenance = _mapping(component.get("provenance"), provenance_path)
    if "repository" in raw_provenance:
        provenance_records = {provenance_path: raw_provenance}
    else:
        if not raw_provenance:
            raise ManifestError(f"{provenance_path} must not be empty")
        provenance_records = {
            f"{provenance_path}.{key}": _mapping(value, f"{provenance_path}.{key}")
            for key, value in raw_provenance.items()
        }
    for record_path, provenance in provenance_records.items():
        provenance_repository = _text(provenance, "repository", record_path)
        provenance_commit = _text(provenance, "commit", record_path)
        provenance_tag = _text(provenance, "tag", record_path)
        _text(provenance, "workflow_run", record_path)
        provenance_url = _text(provenance, "url", record_path)
        provenance_name = urlsplit(provenance_url).path.rsplit("/", 1)[-1]
        _github_release_asset_url(
            provenance_url,
            repository=release_repository,
            tag=release_tag,
            artifact_name=provenance_name,
            path=f"{record_path}.url",
        )
        _sha256(provenance, "sha256", record_path)
        if provenance_repository != repository:
            raise ManifestError(f"{record_path}.repository must agree with {path}.repository")
        if provenance_commit != commit:
            raise ManifestError(f"{record_path}.commit must agree with {path}.commit")
        if provenance_tag != tag:
            raise ManifestError(f"{record_path}.tag must agree with {path}.tag")

    artifacts = component.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError(f"{path}.artifacts must be a non-empty list")
    validated = [
        _validate_artifact(
            component_name=name,
            artifact=_mapping(value, f"{path}.artifacts[{index}]"),
            index=index,
            target=target,
            provenance_refs=set(provenance_records),
            release_repository=release_repository,
            release_tag=release_tag,
        )
        for index, value in enumerate(artifacts)
    ]
    names = [artifact["name"] for artifact in validated]
    if len(names) != len(set(names)):
        raise ManifestError(f"{path}.artifacts contains duplicate names")

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
    specificity = max(
        _platform_specificity(_mapping(item["platform"], "artifact.platform")) for item in matches
    )
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


def validate_manifest(
    document: dict[str, Any],
    *,
    mode: str,
    target: Target,
    compatibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate *document* and return the resolved deployment identity."""

    components = _validate_common(document, target=target)
    if compatibility is None:
        compatibility = _mapping(
            yaml.safe_load(DEFAULT_COMPATIBILITY_PATH.read_text()),
            "compatibility",
        )
    _validate_compatibility(document, components, compatibility)
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
                raise ManifestError(
                    f"components.{name}.immutable must be false in development mode"
                )
            if not _contains_mutable_marker(_text(component, "source_mode", f"components.{name}")):
                raise ManifestError(
                    f"components.{name}.source_mode must visibly identify mutable input"
                )
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
                    provenance_refs={"components.camilladsp.provenance"},
                    release_repository=_text(camilla, "repository", "components.camilladsp"),
                    release_tag=f"v{_text(camilla, 'version', 'components.camilladsp')}",
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
    raw_finalized_by = document.get("finalized_by")
    coordinated_release = (
        _mapping(raw_finalized_by, "finalized_by") if raw_finalized_by is not None else None
    )
    if coordinated_release is not None:
        open_cinema = components["open_cinema"]
        for key in ("repository", "tag", "commit"):
            coordinated_value = _text(coordinated_release, key, "finalized_by")
            open_cinema_value = _text(open_cinema, key, "components.open_cinema")
            if coordinated_value != open_cinema_value:
                raise ManifestError(
                    f"finalized_by.{key} must agree with components.open_cinema.{key}"
                )
    for name, component in components.items():
        validated_artifacts[name] = _validate_immutable_component(
            name,
            component,
            target=target,
            coordinated_release=coordinated_release,
        )

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
    parser.add_argument(
        "--compatibility",
        type=Path,
        default=DEFAULT_COMPATIBILITY_PATH,
    )
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
        compatibility = _mapping(
            yaml.safe_load(args.compatibility.read_text()),
            "compatibility",
        )
        result = validate_manifest(
            document,
            mode=args.mode,
            compatibility=compatibility,
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
