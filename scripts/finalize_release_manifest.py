#!/usr/bin/env python3
"""Finalize the coordinated manifest with the tag-built Open Cinema bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MUTABLE_SOURCE_MARKERS = ("dirty", "editable", "floating", "local-source", "latest")


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


def _immutable_component(name: str, component: dict[str, Any]) -> None:
    path = f"components.{name}"
    if component.get("compatibility_ref"):
        return
    if component.get("immutable") is not True:
        raise AssertionError(f"{path}.immutable must be true")

    source_mode = _text(component, "source_mode", path).lower()
    if any(marker in source_mode for marker in MUTABLE_SOURCE_MARKERS):
        raise AssertionError(f"{path}.source_mode is mutable: {source_mode!r}")
    _text(component, "version", path)

    artifacts = component.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AssertionError(f"{path}.artifacts must be a non-empty list")
    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{path}.artifacts[{index}]"
        artifact = _mapping(raw_artifact, artifact_path)
        _text(artifact, "name", artifact_path)
        url = _text(artifact, "url", artifact_path)
        if not url.startswith("https://") or "/latest" in url.lower():
            raise AssertionError(f"{artifact_path}.url must be an immutable HTTPS URL")
        _digest(artifact, "sha256", artifact_path)
        _mapping(artifact.get("platform"), f"{artifact_path}.platform")
        if artifact.get("provenance_ref") != f"{path}.provenance":
            raise AssertionError(f"{artifact_path}.provenance_ref must reference {path}.provenance")

    provenance = _mapping(component.get("provenance"), f"{path}.provenance")
    _text(provenance, "repository", f"{path}.provenance")
    _text(provenance, "commit", f"{path}.provenance")
    _text(provenance, "tag", f"{path}.provenance")
    _text(provenance, "workflow_run", f"{path}.provenance")
    provenance_url = _text(provenance, "url", f"{path}.provenance")
    if not provenance_url.startswith("https://") or "/latest" in provenance_url.lower():
        raise AssertionError(f"{path}.provenance.url must be an immutable HTTPS URL")
    _digest(provenance, "sha256", f"{path}.provenance")


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
    _mapping(document.get("rollback"), "rollback")

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
    for name, raw_component in components.items():
        _immutable_component(name, _mapping(raw_component, f"components.{name}"))


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
                    "distribution": "any",
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
    )
    print(f"wrote immutable coordinated manifest to {args.output}")


if __name__ == "__main__":
    main()
