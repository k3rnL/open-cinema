#!/usr/bin/env python3
"""Finalize the coordinated manifest with the tag-built Open Cinema bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MUTABLE_SOURCE_MARKERS = ("dirty", "editable", "floating", "local-source", "latest")
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be a mapping")
    return value


def _text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"{path}.{key} must be a non-empty string")
    return value


def _digest(mapping: dict[str, Any], key: str, path: str) -> str:
    value = _text(mapping, key, path)
    if not SHA256_PATTERN.fullmatch(value):
        raise AssertionError(f"{path}.{key} must be a lowercase SHA-256 digest")
    return value


def _github_release_asset_url(
    value: str,
    *,
    repository: str,
    tag: str,
    artifact_name: str,
    path: str,
) -> str:
    parsed = urlsplit(value)
    expected_path = f"/{repository}/releases/download/{tag}/{artifact_name}"
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise AssertionError(f"{path} must use declared release https://github.com{expected_path}")
    return value


def _validate_platform_selectors(
    *,
    component_name: str,
    kind: str,
    platform: dict[str, Any],
    path: str,
) -> None:
    unknown = sorted(set(platform).difference(PLATFORM_SELECTOR_KEYS))
    if unknown:
        raise AssertionError(f"{path} contains unknown selectors: {', '.join(unknown)}")

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
        raise AssertionError(f"{path} is missing required selectors: {', '.join(missing)}")

    if kind == "native-archive" and str(platform["architecture"]).lower() in {"any", "all"}:
        raise AssertionError(f"{path}.architecture must select one native architecture")
    if component_name == "wyreplumber":
        if str(platform["architecture"]).lower() in {"any", "all"}:
            raise AssertionError(f"{path}.architecture must select one native architecture")
        if re.fullmatch(r"cp\d+", str(platform["python_abi"]).lower()) is None:
            raise AssertionError(f"{path}.python_abi must select one CPython ABI")
        if str(platform["wireplumber_api_family"]).lower() in {"any", "all"}:
            raise AssertionError(
                f"{path}.wireplumber_api_family must select one WirePlumber API family"
            )


def _immutable_component(
    name: str,
    component: dict[str, Any],
    *,
    coordinated_repository: str,
    coordinated_tag: str,
) -> None:
    path = f"components.{name}"
    if component.get("compatibility_ref"):
        return
    if component.get("immutable") is not True:
        raise AssertionError(f"{path}.immutable must be true")

    source_mode = _text(component, "source_mode", path).lower()
    if any(marker in source_mode for marker in MUTABLE_SOURCE_MARKERS):
        raise AssertionError(f"{path}.source_mode is mutable: {source_mode!r}")
    version = _text(component, "version", path)
    repository = _text(component, "repository", path)
    commit = _text(component, "commit", path)
    tag = _text(component, "tag", path)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AssertionError(f"{path}.commit must be a full lowercase Git object ID")
    if tag != f"v{version}":
        raise AssertionError(f"{path}.tag must agree with version {version}")
    if source_mode in COORDINATED_RELEASE_ASSET_MODES:
        release_repository = coordinated_repository
        release_tag = coordinated_tag
    else:
        release_repository = repository
        release_tag = tag

    provenance_path = f"{path}.provenance"
    raw_provenance = _mapping(component.get("provenance"), provenance_path)
    if "repository" in raw_provenance:
        provenance_records = {provenance_path: raw_provenance}
    else:
        if not raw_provenance:
            raise AssertionError(f"{provenance_path} must not be empty")
        provenance_records = {
            f"{provenance_path}.{key}": _mapping(value, f"{provenance_path}.{key}")
            for key, value in raw_provenance.items()
        }
    for record_path, provenance in provenance_records.items():
        if _text(provenance, "repository", record_path) != repository:
            raise AssertionError(f"{record_path}.repository must agree with {path}.repository")
        if _text(provenance, "commit", record_path) != commit:
            raise AssertionError(f"{record_path}.commit must agree with {path}.commit")
        if _text(provenance, "tag", record_path) != tag:
            raise AssertionError(f"{record_path}.tag must agree with {path}.tag")
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
        _digest(provenance, "sha256", record_path)

    artifacts = component.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AssertionError(f"{path}.artifacts must be a non-empty list")
    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{path}.artifacts[{index}]"
        artifact = _mapping(raw_artifact, artifact_path)
        name_value = _text(artifact, "name", artifact_path)
        kind = _text(artifact, "kind", artifact_path)
        _github_release_asset_url(
            _text(artifact, "url", artifact_path),
            repository=release_repository,
            tag=release_tag,
            artifact_name=name_value,
            path=f"{artifact_path}.url",
        )
        _digest(artifact, "sha256", artifact_path)
        platform = _mapping(artifact.get("platform"), f"{artifact_path}.platform")
        _validate_platform_selectors(
            component_name=name,
            kind=kind,
            platform=platform,
            path=f"{artifact_path}.platform",
        )
        provenance_ref = _text(artifact, "provenance_ref", artifact_path)
        if provenance_ref not in provenance_records:
            expected = ", ".join(sorted(provenance_records))
            raise AssertionError(
                f"{artifact_path}.provenance_ref must reference one of: {expected}"
            )


def _verified_portable_provenance(
    *,
    path: Path,
    artifact_path: Path,
    project: str,
    repository: str,
    version: str,
) -> dict[str, Any]:
    provenance = _mapping(json.loads(path.read_text()), f"provenance[{project}]")
    tag = f"v{version}"
    expected = {
        "project": project,
        "repository": repository,
        "tag": tag,
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise AssertionError(f"{project} provenance {key} {provenance.get(key)!r} != {value!r}")
    commit = _text(provenance, "commit", f"provenance[{project}]")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AssertionError(f"{project} provenance commit must be a full Git object ID")
    _text(provenance, "workflowRun", f"provenance[{project}]")

    records = [
        record
        for record in provenance.get("artifacts", [])
        if isinstance(record, dict) and record.get("name") == artifact_path.name
    ]
    if len(records) != 1:
        raise AssertionError(
            f"{project} provenance must contain exactly one record for {artifact_path.name}"
        )
    record = records[0]
    digest = sha256(artifact_path)
    if record.get("sha256") != digest:
        raise AssertionError(f"{project} provenance digest mismatch for {artifact_path.name}")
    if record.get("sizeBytes") != artifact_path.stat().st_size:
        raise AssertionError(f"{project} provenance size mismatch for {artifact_path.name}")
    return provenance


def _verified_mirrored_provenance(
    *,
    path: Path,
    artifact_path: Path,
    repository: str,
    commit: str,
    version: str,
    tag: str,
    workflow_run: str,
) -> None:
    """Verify the portable records emitted by the independently released UI/decoder."""

    provenance = _mapping(json.loads(path.read_text()), f"provenance[{path.name}]")
    source = provenance.get("source")
    source_mapping = source if isinstance(source, dict) else provenance
    observed = {
        "repository": source_mapping.get("repository"),
        "commit": source_mapping.get("commit"),
        "version": provenance.get("version"),
        "tag": provenance.get("tag"),
        "workflow_run": provenance.get("workflowRun")
        or _mapping(provenance.get("build"), f"provenance[{path.name}].build").get("runUrl"),
    }
    expected = {
        "repository": repository,
        "commit": commit,
        "version": version,
        "tag": tag,
        "workflow_run": workflow_run,
    }
    for key, value in expected.items():
        if observed[key] != value:
            raise AssertionError(
                f"mirrored provenance {path.name} {key} {observed[key]!r} != {value!r}"
            )

    raw_artifact = provenance.get("artifact")
    if isinstance(raw_artifact, str):
        artifact_name = raw_artifact
        artifact_digest = provenance.get("sha256")
    else:
        artifact = _mapping(raw_artifact, f"provenance[{path.name}].artifact")
        artifact_name = artifact.get("name")
        artifact_digest = artifact.get("sha256")
    if artifact_name != artifact_path.name:
        raise AssertionError(f"mirrored provenance {path.name} artifact name mismatch")
    if artifact_digest != sha256(artifact_path):
        raise AssertionError(f"mirrored provenance {path.name} artifact digest mismatch")


def _finalize_mirrored_component(
    *,
    component_name: str,
    component: dict[str, Any],
    dist_dir: Path,
    release_url: str,
) -> None:
    """Bind an independently built dependency to bytes mirrored into this release."""

    path = f"components.{component_name}"
    version = _text(component, "version", path)
    repository = _text(component, "repository", path)
    commit = _text(component, "commit", path)
    tag = _text(component, "tag", path)
    if component.get("source_mode") != "coordinated-release-mirror":
        return

    raw_provenance = _mapping(component.get("provenance"), f"{path}.provenance")
    if "repository" in raw_provenance:
        provenance_records = {f"{path}.provenance": raw_provenance}
    else:
        provenance_records = {
            f"{path}.provenance.{key}": _mapping(value, f"{path}.provenance.{key}")
            for key, value in raw_provenance.items()
        }
    artifacts = component.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AssertionError(f"{path}.artifacts must be a non-empty list")

    provenance_files: dict[str, Path] = {}
    for record_path, record in provenance_records.items():
        source_provenance_url = _text(record, "url", record_path)
        provenance_name = urlsplit(source_provenance_url).path.rsplit("/", 1)[-1]
        _github_release_asset_url(
            source_provenance_url,
            repository=repository,
            tag=tag,
            artifact_name=provenance_name,
            path=f"{record_path}.url",
        )
        provenance_file = dist_dir / provenance_name
        if not provenance_file.is_file():
            raise AssertionError(f"mirrored provenance is absent from dist: {provenance_name}")
        expected_digest = _digest(record, "sha256", record_path)
        if sha256(provenance_file) != expected_digest:
            raise AssertionError(f"mirrored provenance digest mismatch: {provenance_name}")
        record["url"] = f"{release_url}/{provenance_name}"
        provenance_files[record_path] = provenance_file

    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{path}.artifacts[{index}]"
        artifact = _mapping(raw_artifact, artifact_path)
        artifact_name = _text(artifact, "name", artifact_path)
        _github_release_asset_url(
            _text(artifact, "url", artifact_path),
            repository=repository,
            tag=tag,
            artifact_name=artifact_name,
            path=f"{artifact_path}.url",
        )
        artifact_file = dist_dir / artifact_name
        if not artifact_file.is_file():
            raise AssertionError(f"mirrored artifact is absent from dist: {artifact_file.name}")
        if sha256(artifact_file) != _digest(artifact, "sha256", artifact_path):
            raise AssertionError(f"mirrored artifact digest mismatch: {artifact_file.name}")
        provenance_ref = _text(artifact, "provenance_ref", artifact_path)
        provenance_record = provenance_records.get(provenance_ref)
        provenance_file = provenance_files.get(provenance_ref)
        if provenance_record is None or provenance_file is None:
            raise AssertionError(f"{artifact_path}.provenance_ref does not resolve")
        _verified_mirrored_provenance(
            path=provenance_file,
            artifact_path=artifact_file,
            repository=repository,
            commit=commit,
            version=version,
            tag=tag,
            workflow_run=_text(provenance_record, "workflow_run", provenance_ref),
        )
        artifact["url"] = f"{release_url}/{artifact_file.name}"
        artifact["size_bytes"] = artifact_file.stat().st_size

    component["immutable"] = True


def _validate_rollback(document: dict[str, Any]) -> None:
    rollback = _mapping(document.get("rollback"), "rollback")
    strategy = _text(rollback, "strategy", "rollback")
    previous = _mapping(rollback.get("previous"), "rollback.previous")
    if strategy == "private-full-generation-replacement":
        if previous.get("kind") != "private-replacement-baseline":
            raise AssertionError("rollback.previous.kind must identify the private replacement")
        if previous.get("first_release_exception") is not True:
            raise AssertionError("private replacement baseline must be a first-release exception")
        _text(previous, "receipt_id", "rollback.previous")
        receipt_path = _text(previous, "receipt_path", "rollback.previous")
        if receipt_path.startswith("/") or ".." in Path(receipt_path).parts:
            raise AssertionError("rollback.previous.receipt_path must be repository-relative")
        _digest(previous, "receipt_sha256", "rollback.previous")
        retrieval_ref = _text(previous, "retrieval_ref", "rollback.previous")
        if not retrieval_ref.startswith("inventory-private:"):
            raise AssertionError("rollback.previous.retrieval_ref must remain private")
        if previous.get("public") is not False or previous.get("verified") is not True:
            raise AssertionError("private replacement baseline must be non-public and verified")
    elif strategy == "previous-coordinated-release":
        _text(previous, "release_id", "rollback.previous")
        url = _text(previous, "url", "rollback.previous")
        if not url.startswith("https://") or "/latest" in url.lower():
            raise AssertionError("rollback.previous.url must be an immutable HTTPS URL")
        _digest(previous, "sha256", "rollback.previous")
        if previous.get("retained") is not True:
            raise AssertionError("rollback.previous.retained must be true")
    else:
        raise AssertionError(f"unsupported rollback strategy: {strategy}")


def validate_finalized_manifest(document: dict[str, Any]) -> None:
    """Reject incomplete or mutable coordinated release inputs."""

    if document.get("schema_version") != 1:
        raise AssertionError("schema_version must be 1")
    if document.get("input_mode") != "appliance":
        raise AssertionError("input_mode must be appliance")
    if document.get("status") != "supported":
        raise AssertionError("status must be supported")
    if document.get("promotable") is not True:
        raise AssertionError("promotable must be true")
    _text(document, "release_id", "manifest")
    _mapping(document.get("platform"), "platform")
    _mapping(document.get("contracts"), "contracts")
    _validate_rollback(document)
    finalized_by = _mapping(document.get("finalized_by"), "finalized_by")
    coordinated_repository = _text(finalized_by, "repository", "finalized_by")
    coordinated_tag = _text(finalized_by, "tag", "finalized_by")
    coordinated_commit = _text(finalized_by, "commit", "finalized_by")
    if not re.fullmatch(r"[0-9a-f]{40}", coordinated_commit):
        raise AssertionError("finalized_by.commit must be a full lowercase Git object ID")
    _text(finalized_by, "workflow_run", "finalized_by")

    components = _mapping(document.get("components"), "components")
    required = {
        "open_cinema",
        "wyreplumber",
        "management_ui",
        "pcm_auto_decoder",
        "camilladsp",
        "pycamilladsp",
    }
    missing = sorted(required.difference(components))
    if missing:
        raise AssertionError(f"manifest is missing components: {', '.join(missing)}")
    open_cinema = _mapping(components["open_cinema"], "components.open_cinema")
    for key, coordinated_value in (
        ("repository", coordinated_repository),
        ("tag", coordinated_tag),
        ("commit", coordinated_commit),
    ):
        if _text(open_cinema, key, "components.open_cinema") != coordinated_value:
            raise AssertionError(f"finalized_by.{key} must agree with components.open_cinema.{key}")
    for name, raw_component in components.items():
        _immutable_component(
            name,
            _mapping(raw_component, f"components.{name}"),
            coordinated_repository=coordinated_repository,
            coordinated_tag=coordinated_tag,
        )


def finalize_manifest(
    *,
    template: Path,
    output: Path,
    dist_dir: Path,
    provenance_path: Path,
    repository: str,
    commit: str,
    tag: str,
    workflow_run: str,
    release_base_url: str,
    pycamilladsp_wheel: Path,
    pycamilladsp_provenance_path: Path,
    camilladsp_artifact: Path,
    camilladsp_provenance_path: Path,
) -> dict[str, Any]:
    document = _mapping(yaml.safe_load(template.read_text()), "manifest")
    components = _mapping(document.get("components"), "components")
    current = _mapping(components.get("open_cinema"), "components.open_cinema")
    version = _text(current, "version", "components.open_cinema")
    if tag != f"v{version}":
        raise AssertionError(f"tag {tag!r} does not match Open Cinema {version!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AssertionError("commit must be a full lowercase Git object ID")

    provenance = _mapping(json.loads(provenance_path.read_text()), "provenance")
    expected_provenance = {
        "project": "open-cinema",
        "repository": repository,
        "commit": commit,
        "tag": tag,
        "workflowRun": workflow_run,
    }
    for key, expected in expected_provenance.items():
        if provenance.get(key) != expected:
            raise AssertionError(f"provenance {key} {provenance.get(key)!r} != {expected!r}")
    provenance_artifacts = {
        item["name"]: item
        for item in provenance.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    release_url = release_base_url.rstrip("/")
    artifacts: list[dict[str, Any]] = []
    candidates = sorted(dist_dir.glob("open_cinema-*.whl")) + sorted(
        dist_dir.glob("open_cinema-*.tar.gz")
    )
    if len(candidates) != 2:
        raise AssertionError("expected exactly one Open Cinema wheel and source archive")
    for artifact_path in candidates:
        recorded = _mapping(
            provenance_artifacts.get(artifact_path.name),
            f"provenance.artifacts[{artifact_path.name}]",
        )
        digest = sha256(artifact_path)
        if recorded.get("sha256") != digest:
            raise AssertionError(f"provenance digest mismatch for {artifact_path.name}")
        kind = "python-wheel" if artifact_path.suffix == ".whl" else "source-archive"
        artifacts.append(
            {
                "name": artifact_path.name,
                "kind": kind,
                "url": f"{release_url}/{artifact_path.name}",
                "sha256": digest,
                "size_bytes": artifact_path.stat().st_size,
                "platform": {
                    "distribution_family": "any",
                    "architecture": "any",
                    "python_abi": "py3" if kind == "python-wheel" else "source",
                },
                "provenance_ref": "components.open_cinema.provenance",
            }
        )

    components["open_cinema"] = {
        "version": version,
        "repository": repository,
        "source_mode": "github-release-assets",
        "tag": tag,
        "commit": commit,
        "immutable": True,
        "artifacts": artifacts,
        "provenance": {
            "repository": repository,
            "commit": commit,
            "tag": tag,
            "workflow_run": workflow_run,
            "url": f"{release_url}/{provenance_path.name}",
            "sha256": sha256(provenance_path),
        },
    }

    pycamilladsp_template = _mapping(components.get("pycamilladsp"), "components.pycamilladsp")
    pycamilladsp_version = _text(pycamilladsp_template, "version", "components.pycamilladsp")
    pycamilladsp_repository = _text(pycamilladsp_template, "repository", "components.pycamilladsp")
    pycamilladsp_provenance = _verified_portable_provenance(
        path=pycamilladsp_provenance_path,
        artifact_path=pycamilladsp_wheel,
        project="pycamilladsp",
        repository=pycamilladsp_repository,
        version=pycamilladsp_version,
    )
    published_pycamilladsp_wheel = dist_dir / pycamilladsp_wheel.name
    if not published_pycamilladsp_wheel.is_file() or sha256(published_pycamilladsp_wheel) != sha256(
        pycamilladsp_wheel
    ):
        raise AssertionError("pyCamillaDSP wheel is absent from or changed in release dist")
    pycamilladsp_tag = f"v{pycamilladsp_version}"
    components["pycamilladsp"] = {
        "version": pycamilladsp_version,
        "repository": pycamilladsp_repository,
        "source_mode": "upstream-source-built-wheel",
        "tag": pycamilladsp_tag,
        "commit": pycamilladsp_provenance["commit"],
        "immutable": True,
        "artifacts": [
            {
                "name": pycamilladsp_wheel.name,
                "kind": "python-wheel",
                "url": f"{release_url}/{pycamilladsp_wheel.name}",
                "sha256": sha256(pycamilladsp_wheel),
                "size_bytes": pycamilladsp_wheel.stat().st_size,
                "platform": {
                    "distribution_family": "any",
                    "architecture": "any",
                    "python_abi": "py3",
                },
                "provenance_ref": "components.pycamilladsp.provenance",
            }
        ],
        "provenance": {
            "repository": pycamilladsp_repository,
            "commit": pycamilladsp_provenance["commit"],
            "tag": pycamilladsp_tag,
            "workflow_run": pycamilladsp_provenance["workflowRun"],
            "url": f"{release_url}/{pycamilladsp_provenance_path.name}",
            "sha256": sha256(pycamilladsp_provenance_path),
        },
    }

    camilladsp_component = _mapping(components.get("camilladsp"), "components.camilladsp")
    camilladsp_version = _text(camilladsp_component, "version", "components.camilladsp")
    camilladsp_repository = _text(camilladsp_component, "repository", "components.camilladsp")
    camilladsp_artifacts = camilladsp_component.get("artifacts")
    if not isinstance(camilladsp_artifacts, list) or len(camilladsp_artifacts) != 1:
        raise AssertionError("components.camilladsp must declare exactly one artifact")
    camilladsp_record = _mapping(camilladsp_artifacts[0], "components.camilladsp.artifacts[0]")
    if camilladsp_record.get("name") != camilladsp_artifact.name:
        raise AssertionError("CamillaDSP downloaded artifact name does not match the template")
    camilladsp_tag = f"v{camilladsp_version}"
    _github_release_asset_url(
        _text(camilladsp_record, "url", "components.camilladsp.artifacts[0]"),
        repository=camilladsp_repository,
        tag=camilladsp_tag,
        artifact_name=camilladsp_artifact.name,
        path="components.camilladsp.artifacts[0].url",
    )
    if camilladsp_record.get("sha256") != sha256(camilladsp_artifact):
        raise AssertionError("CamillaDSP downloaded artifact digest does not match the template")
    camilladsp_provenance = _verified_portable_provenance(
        path=camilladsp_provenance_path,
        artifact_path=camilladsp_artifact,
        project="camilladsp",
        repository=camilladsp_repository,
        version=camilladsp_version,
    )
    published_camilladsp_artifact = dist_dir / camilladsp_artifact.name
    if not published_camilladsp_artifact.is_file() or sha256(
        published_camilladsp_artifact
    ) != sha256(camilladsp_artifact):
        raise AssertionError("CamillaDSP archive is absent from or changed in release dist")
    camilladsp_record["url"] = f"{release_url}/{camilladsp_artifact.name}"
    camilladsp_record["size_bytes"] = camilladsp_artifact.stat().st_size
    camilladsp_component.update(
        {
            "source_mode": "coordinated-release-mirror",
            "tag": camilladsp_tag,
            "commit": camilladsp_provenance["commit"],
            "immutable": True,
            "provenance": {
                "repository": camilladsp_repository,
                "commit": camilladsp_provenance["commit"],
                "tag": camilladsp_tag,
                "workflow_run": camilladsp_provenance["workflowRun"],
                "url": f"{release_url}/{camilladsp_provenance_path.name}",
                "sha256": sha256(camilladsp_provenance_path),
            },
        }
    )

    for component_name in ("management_ui", "pcm_auto_decoder"):
        _finalize_mirrored_component(
            component_name=component_name,
            component=_mapping(components.get(component_name), f"components.{component_name}"),
            dist_dir=dist_dir,
            release_url=release_url,
        )

    document.pop("candidate_notice", None)
    raw_limitations = document.get("limitations", [])
    if not isinstance(raw_limitations, list):
        raise AssertionError("limitations must be a list")
    document["limitations"] = [
        limitation
        for limitation in raw_limitations
        if not (
            isinstance(limitation, str)
            and "tag-build template is not deployable" in limitation.lower()
        )
    ]
    document["release_id"] = f"open-cinema-{version}"
    document["input_mode"] = "appliance"
    document["status"] = "supported"
    document["promotable"] = True
    document["finalized_by"] = {
        "repository": repository,
        "commit": commit,
        "tag": tag,
        "workflow_run": workflow_run,
    }

    validate_finalized_manifest(document)
    output.write_text(yaml.safe_dump(document, sort_keys=False))
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--release-base-url", required=True)
    parser.add_argument("--pycamilladsp-wheel", type=Path, required=True)
    parser.add_argument("--pycamilladsp-provenance", type=Path, required=True)
    parser.add_argument("--camilladsp-artifact", type=Path, required=True)
    parser.add_argument("--camilladsp-provenance", type=Path, required=True)
    args = parser.parse_args()

    finalize_manifest(
        template=args.template,
        output=args.output,
        dist_dir=args.dist_dir,
        provenance_path=args.provenance,
        repository=args.repository,
        commit=args.commit,
        tag=args.tag,
        workflow_run=args.workflow_run,
        release_base_url=args.release_base_url,
        pycamilladsp_wheel=args.pycamilladsp_wheel,
        pycamilladsp_provenance_path=args.pycamilladsp_provenance,
        camilladsp_artifact=args.camilladsp_artifact,
        camilladsp_provenance_path=args.camilladsp_provenance,
    )
    print(f"wrote immutable coordinated manifest to {args.output}")


if __name__ == "__main__":
    main()
