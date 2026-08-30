from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core.plugin_system.manifest import parse_plugin_manifest
from core.plugin_system.v2_contracts import (
    PLUGIN_ENTRY_POINT,
    PLUGIN_MANIFEST_FILENAME,
    OpenCinemaPlugin,
    PluginDistributionManifest,
    validate_runtime_capability_namespace,
)


@dataclass(frozen=True, slots=True)
class PluginContractReport:
    plugin_id: str
    distribution: str
    version: str
    capability_ids: tuple[str, ...]
    source_validated: bool
    wheel_validated: bool
    runtime_validated: bool


def _source_manifest(root: Path) -> tuple[Path, PluginDistributionManifest]:
    candidates = [
        item
        for item in root.rglob(PLUGIN_MANIFEST_FILENAME)
        if ".git" not in item.parts
        and "build" not in item.parts
        and "dist" not in item.parts
    ]
    if len(candidates) != 1:
        raise AssertionError(
            f"source must contain exactly one {PLUGIN_MANIFEST_FILENAME}"
        )
    return candidates[0], parse_plugin_manifest(candidates[0].read_bytes())


def validate_source_checkout(root: str | Path) -> PluginDistributionManifest:
    root = Path(root).resolve()
    if not root.is_dir():
        raise AssertionError("plugin source checkout does not exist")
    manifest_path, manifest = _source_manifest(root)
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise AssertionError("plugin source must contain pyproject.toml")
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project_name = str(project.get("project", {}).get("name", ""))
    if project_name.lower().replace("_", "-") != manifest.distribution_id:
        raise AssertionError("pyproject distribution name and static manifest disagree")
    entry_points = (
        project.get("project", {}).get("entry-points", {}).get(PLUGIN_ENTRY_POINT)
    )
    if not isinstance(entry_points, Mapping) or len(entry_points) != 1:
        raise AssertionError(
            f"pyproject must declare exactly one {PLUGIN_ENTRY_POINT} entry point"
        )
    for declaration in manifest.capabilities:
        if declaration.schema_path is not None:
            schema = manifest_path.parent / declaration.schema_path
            package_root = manifest_path.parent.resolve()
            if not schema.is_file() or package_root not in schema.resolve().parents:
                raise AssertionError(
                    f"capability schema is missing or escapes the package: {schema}"
                )
    if manifest.configuration is not None:
        schema = manifest_path.parent / manifest.configuration.schema_path
        package_root = manifest_path.parent.resolve()
        if not schema.is_file() or package_root not in schema.resolve().parents:
            raise AssertionError(
                f"configuration schema is missing or escapes the package: {schema}"
            )
    return manifest


def validate_built_wheel(path: str | Path) -> PluginDistributionManifest:
    from core.plugin_system.acquisition import inspect_plugin_wheel

    return inspect_plugin_wheel(Path(path).resolve()).manifest


def validate_runtime_plugin(
    manifest: PluginDistributionManifest,
    plugin: OpenCinemaPlugin,
) -> tuple[str, ...]:
    identity = plugin.identity
    if (
        identity.plugin_id != manifest.plugin_id
        or identity.distribution_id != manifest.distribution_id
        or identity.version != manifest.version
    ):
        raise AssertionError("runtime plugin identity and static manifest disagree")
    contributions = tuple(plugin.capabilities())
    identifiers = tuple(item.capability_id for item in contributions)
    if len(set(identifiers)) != len(identifiers):
        raise AssertionError("runtime capability IDs must be unique")
    declared = {item.capability_id: item for item in manifest.capabilities}
    for contribution in contributions:
        declaration = declared.get(contribution.capability_id)
        if declaration is None:
            raise AssertionError(
                f"runtime capability is not declared: {contribution.capability_id}"
            )
        if (
            declaration.kind != contribution.KIND
            or declaration.version != contribution.version
        ):
            raise AssertionError(
                f"runtime capability does not match its declaration: {contribution.capability_id}"
            )
        validate_runtime_capability_namespace(manifest.plugin_id, contribution)
    missing = [
        item.capability_id
        for item in manifest.capabilities
        if item.required and item.capability_id not in identifiers
    ]
    if missing:
        raise AssertionError(
            f"required runtime capabilities are missing: {', '.join(missing)}"
        )
    return identifiers


def assert_plugin_contract(
    source_root: str | Path,
    *,
    wheel: str | Path | None = None,
    plugin: OpenCinemaPlugin | None = None,
) -> PluginContractReport:
    source_manifest = validate_source_checkout(source_root)
    wheel_validated = wheel is not None
    if wheel is not None:
        wheel_manifest = validate_built_wheel(wheel)
        if wheel_manifest != source_manifest:
            raise AssertionError(
                "built wheel manifest differs from the source checkout"
            )
    capability_ids: tuple[str, ...] = ()
    if plugin is not None:
        capability_ids = validate_runtime_plugin(source_manifest, plugin)
    return PluginContractReport(
        plugin_id=source_manifest.plugin_id,
        distribution=source_manifest.distribution_id,
        version=source_manifest.version,
        capability_ids=capability_ids,
        source_validated=True,
        wheel_validated=wheel_validated,
        runtime_validated=plugin is not None,
    )
