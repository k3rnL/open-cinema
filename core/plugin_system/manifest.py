from __future__ import annotations

import tomllib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import unquote, urlparse

from wyreplumber.runtime import FrozenDict

from .v2_contracts import (
    PLUGIN_MANIFEST_FILENAME,
    PLUGIN_MANIFEST_MAX_BYTES,
    DistributionCompatibility,
    ExternalRequirement,
    IntegerCompatibilityRange,
    LifecycleImpact,
    PluginCapabilityDeclaration,
    PluginConfigurationDeclaration,
    PluginDependency,
    PluginDistributionManifest,
    PluginLifecyclePolicy,
    PluginPermission,
    validate_contract_document,
)


@dataclass(frozen=True, slots=True)
class PluginManifestIssue:
    code: str
    message: str


class PluginManifestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.issue = PluginManifestIssue(code, message)
        super().__init__(message)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "manifest-field-invalid", f"{field_name} must be an object"
        )
    return value


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise PluginManifestError(
            "manifest-field-invalid", f"{field_name} must be an array"
        )
    return tuple(value)


def _manifest_document(source: str | bytes | Mapping[str, object]) -> dict[str, object]:
    if isinstance(source, Mapping):
        document = dict(source)
    else:
        raw = source.encode("utf-8") if isinstance(source, str) else source
        if len(raw) > PLUGIN_MANIFEST_MAX_BYTES:
            raise PluginManifestError(
                "manifest-too-large",
                f"{PLUGIN_MANIFEST_FILENAME} exceeds {PLUGIN_MANIFEST_MAX_BYTES} bytes",
            )
        try:
            document = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PluginManifestError("manifest-toml-invalid", str(error)) from error
    try:
        validate_contract_document(
            document,
            "open-cinema-plugin-v2.schema.json",
            maximum_bytes=PLUGIN_MANIFEST_MAX_BYTES,
        )
    except (TypeError, ValueError) as error:
        raise PluginManifestError("manifest-schema-invalid", str(error)) from error
    return document


def parse_plugin_manifest(
    source: str | bytes | Mapping[str, object],
) -> PluginDistributionManifest:
    document = _manifest_document(source)
    plugin = _mapping(document["plugin"], "plugin")
    compatibility = _mapping(document["compatibility"], "compatibility")
    contract = _mapping(
        compatibility["plugin-contract"], "compatibility.plugin-contract"
    )
    capability_versions = {
        str(kind): FrozenDict(_mapping(version_range, f"capability-versions.{kind}"))
        for kind, version_range in _mapping(
            compatibility.get("capability-versions", {}),
            "compatibility.capability-versions",
        ).items()
    }
    capabilities = []
    for item in _sequence(document["capabilities"], "capabilities"):
        item = _mapping(item, "capability")
        capabilities.append(
            PluginCapabilityDeclaration(
                capability_id=str(item["id"]),
                kind=str(item["kind"]),
                version=int(item["version"]),
                required=bool(item.get("required", True)),
                schema_path=str(item["schema"])
                if item.get("schema") is not None
                else None,
                digest=str(item["digest"]) if item.get("digest") is not None else None,
            )
        )
    permissions = []
    for item in _sequence(document["permissions"], "permissions"):
        item = _mapping(item, "permission")
        permissions.append(
            PluginPermission(
                permission_id=str(item["id"]),
                reason=str(item["reason"]),
                required=bool(item.get("required", True)),
            )
        )
    dependencies = []
    for item in _sequence(document.get("dependencies", ()), "dependencies"):
        item = _mapping(item, "dependency")
        dependencies.append(
            PluginDependency(
                dependency_id=str(item["id"]),
                kind=str(item["kind"]),
                version=str(item["version"]),
                required=bool(item.get("required", True)),
            )
        )
    external_requirements = []
    for item in _sequence(
        document.get("external-requirements", ()), "external-requirements"
    ):
        item = _mapping(item, "external requirement")
        external_requirements.append(
            ExternalRequirement(
                requirement_id=str(item["id"]),
                description=str(item["description"]),
                probe=str(item["probe"]) if item.get("probe") is not None else None,
            )
        )
    configuration = None
    if document.get("configuration") is not None:
        raw_configuration = _mapping(document["configuration"], "configuration")
        migrations = []
        for item in _sequence(raw_configuration.get("migrations", ()), "migrations"):
            migration = _mapping(item, "migration")
            migrations.append((int(migration["from"]), int(migration["to"])))
        configuration = PluginConfigurationDeclaration(
            version=int(raw_configuration["version"]),
            schema_path=str(raw_configuration["schema"]),
            migrations=tuple(migrations),
        )
    lifecycle = _mapping(document["lifecycle"], "lifecycle")
    try:
        return PluginDistributionManifest(
            plugin_id=str(plugin["id"]),
            distribution_id=str(plugin["distribution"]),
            display_name=str(plugin["display-name"]),
            description=str(plugin["description"]),
            vendor=str(plugin["vendor"]),
            version=str(plugin["version"]),
            license=str(plugin["license"]),
            source_url=str(plugin["source-url"]),
            documentation_url=str(plugin["documentation-url"]),
            release_url=(
                str(plugin["release-url"])
                if plugin.get("release-url") is not None
                else None
            ),
            compatibility=DistributionCompatibility(
                plugin_contract=IntegerCompatibilityRange(
                    int(contract["minimum"]), int(contract["maximum"])
                ),
                open_cinema=str(compatibility["open-cinema"]),
                python=str(compatibility["python"]),
                operating_systems=tuple(
                    str(item) for item in compatibility["operating-systems"]
                ),
                architectures=tuple(
                    str(item) for item in compatibility["architectures"]
                ),
                capability_versions=FrozenDict(capability_versions),
            ),
            capabilities=tuple(capabilities),
            permissions=tuple(permissions),
            lifecycle=PluginLifecyclePolicy(
                install=LifecycleImpact(str(lifecycle["install"])),
                enable=LifecycleImpact(str(lifecycle["enable"])),
                disable=LifecycleImpact(str(lifecycle["disable"])),
                update=LifecycleImpact(str(lifecycle["update"])),
                uninstall=LifecycleImpact(str(lifecycle["uninstall"])),
            ),
            dependencies=tuple(dependencies),
            external_requirements=tuple(external_requirements),
            configuration=configuration,
            contribution_digest=(
                str(document["contribution-digest"])
                if document.get("contribution-digest") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PluginManifestError("manifest-semantic-invalid", str(error)) from error


class DistributionLike(Protocol):
    files: object

    def locate_file(self, path: object) -> Path: ...

    def read_text(self, filename: str) -> str | None: ...


def read_distribution_manifest(
    distribution: DistributionLike,
) -> PluginDistributionManifest:
    """Read the static manifest without importing the plugin entry point."""

    direct = distribution.read_text(PLUGIN_MANIFEST_FILENAME)
    if direct is not None:
        return parse_plugin_manifest(direct)
    candidates = []
    for item in distribution.files or ():
        item_path = PurePosixPath(str(item))
        if item_path.name == PLUGIN_MANIFEST_FILENAME:
            candidates.append(item)
    if not candidates:
        # PEP 660 editable installs intentionally omit package data from RECORD.
        # Use the explicit editable source URL and declared top-level packages;
        # never scan an arbitrary parent directory.
        direct_url = distribution.read_text("direct_url.json")
        top_level = distribution.read_text("top_level.txt")
        if direct_url is not None and top_level is not None:
            try:
                source = json.loads(direct_url)
                parsed = urlparse(str(source.get("url", "")))
                editable = source.get("dir_info", {}).get("editable") is True
                root = Path(unquote(parsed.path)).resolve()
            except (
                AttributeError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                editable = False
                root = Path()
            if editable and parsed.scheme == "file" and root.is_dir():
                local = []
                for package_name in top_level.splitlines():
                    if not package_name or not package_name.replace("_", "").isalnum():
                        continue
                    candidate = (
                        root / package_name / PLUGIN_MANIFEST_FILENAME
                    ).resolve()
                    if root in candidate.parents and candidate.is_file():
                        local.append(candidate)
                if len(local) == 1:
                    try:
                        return parse_plugin_manifest(local[0].read_bytes())
                    except OSError as error:
                        raise PluginManifestError(
                            "manifest-file-unreadable", str(error)
                        ) from error
    if len(candidates) != 1:
        raise PluginManifestError(
            "manifest-file-missing",
            f"distribution must contain exactly one {PLUGIN_MANIFEST_FILENAME}",
        )
    path = distribution.locate_file(candidates[0])
    try:
        return parse_plugin_manifest(path.read_bytes())
    except OSError as error:
        raise PluginManifestError("manifest-file-unreadable", str(error)) from error
