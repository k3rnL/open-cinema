from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from importlib import resources

from django.db import OperationalError, ProgrammingError
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from api.models import PluginInstallation
from opencinema.version import __version__ as OPEN_CINEMA_VERSION

from .v2_contracts import PLUGIN_CONTRACT_VERSION_V2, validate_contract_document
from .v2_registry import PluginDistributionRegistry


def current_platform() -> tuple[str, str]:
    operating_system = platform.system().lower()
    architecture = {
        "amd64": "x86_64",
        "arm64": "aarch64",
    }.get(platform.machine().lower(), platform.machine().lower())
    return operating_system, architecture


@dataclass(frozen=True, slots=True)
class CatalogueArtifact:
    operating_system: str
    architecture: str
    url: str
    digest: str

    def matches(self, operating_system: str, architecture: str) -> bool:
        normalized_architecture = {
            "amd64": "x86_64",
            "arm64": "aarch64",
        }.get(architecture.lower(), architecture.lower())
        return (
            self.operating_system == operating_system.lower()
            and self.architecture == normalized_architecture
        )

    def to_document(self) -> dict[str, str]:
        return {
            "operatingSystem": self.operating_system,
            "architecture": self.architecture,
            "url": self.url,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class CataloguePermission:
    permission_id: str
    reason: str

    def to_document(self) -> dict[str, str]:
        return {"id": self.permission_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class CatalogueVersion:
    version: str
    revision: str
    resolved_commit: str | None
    mutable: bool
    published: bool
    contract_minimum: int
    contract_maximum: int
    open_cinema: str
    capabilities: tuple[str, ...]
    permissions: tuple[CataloguePermission, ...]
    artifacts: tuple[CatalogueArtifact, ...]

    @property
    def compatible(self) -> bool:
        return (
            self.contract_minimum <= PLUGIN_CONTRACT_VERSION_V2 <= self.contract_maximum
            and Version(OPEN_CINEMA_VERSION) in SpecifierSet(self.open_cinema)
        )

    def artifact_for(
        self,
        operating_system: str | None = None,
        architecture: str | None = None,
    ) -> CatalogueArtifact | None:
        current_operating_system, current_architecture = current_platform()
        operating_system = operating_system or current_operating_system
        architecture = architecture or current_architecture
        return next(
            (
                artifact
                for artifact in self.artifacts
                if artifact.matches(operating_system, architecture)
            ),
            None,
        )

    @property
    def installable(self) -> bool:
        return self.compatible and self.published and self.artifact_for() is not None

    def to_document(self) -> dict[str, object]:
        operating_system, architecture = current_platform()
        artifact = self.artifact_for(operating_system, architecture)
        return {
            "version": self.version,
            "revision": self.revision,
            "resolvedCommit": self.resolved_commit,
            "artifactDigest": artifact.digest if artifact is not None else None,
            "mutable": self.mutable,
            "published": self.published,
            "pluginContract": {
                "minimum": self.contract_minimum,
                "maximum": self.contract_maximum,
            },
            "openCinema": self.open_cinema,
            "capabilities": list(self.capabilities),
            "permissions": [item.to_document() for item in self.permissions],
            "artifacts": [item.to_document() for item in self.artifacts],
            "currentPlatform": {
                "operatingSystem": operating_system,
                "architecture": architecture,
                "artifactAvailable": artifact is not None,
            },
            "compatible": self.compatible,
            "installable": self.installable,
        }


@dataclass(frozen=True, slots=True)
class FirstPartyPlugin:
    plugin_id: str
    display_name: str
    summary: str
    publisher: str
    verified_publisher: bool
    repository: str
    documentation_url: str
    icon: str
    versions: tuple[CatalogueVersion, ...]

    def latest(self) -> CatalogueVersion:
        return max(self.versions, key=lambda item: Version(item.version))

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.plugin_id,
            "displayName": self.display_name,
            "summary": self.summary,
            "publisher": self.publisher,
            "verifiedPublisher": self.verified_publisher,
            "repository": self.repository,
            "documentationUrl": self.documentation_url,
            "icon": self.icon,
            "versions": [item.to_document() for item in self.versions],
        }


class FirstPartyPluginCatalogue:
    def __init__(self, entries: tuple[FirstPartyPlugin, ...]) -> None:
        if len({item.plugin_id for item in entries}) != len(entries):
            raise ValueError("first-party catalogue plugin IDs must be unique")
        self.entries = entries

    @classmethod
    def load(cls) -> FirstPartyPluginCatalogue:
        document = json.loads(
            resources.files("core.plugin_system")
            .joinpath("first_party_plugins.json")
            .read_text(encoding="utf-8")
        )
        validate_contract_document(
            document,
            "plugin-catalogue-v1.schema.json",
            maximum_bytes=256 * 1024,
        )
        entries = []
        for raw in document["plugins"]:
            versions = tuple(
                CatalogueVersion(
                    version=item["version"],
                    revision=item["revision"],
                    resolved_commit=item.get("resolvedCommit"),
                    mutable=item["mutable"],
                    published=item["published"],
                    contract_minimum=item["pluginContract"]["minimum"],
                    contract_maximum=item["pluginContract"]["maximum"],
                    open_cinema=item["openCinema"],
                    capabilities=tuple(item["capabilities"]),
                    permissions=tuple(
                        CataloguePermission(
                            permission_id=permission["id"],
                            reason=permission["reason"],
                        )
                        for permission in item["permissions"]
                    ),
                    artifacts=tuple(
                        CatalogueArtifact(
                            operating_system=artifact["operatingSystem"],
                            architecture=artifact["architecture"],
                            url=artifact["url"],
                            digest=artifact["digest"],
                        )
                        for artifact in item["artifacts"]
                    ),
                )
                for item in raw["versions"]
            )
            entries.append(
                FirstPartyPlugin(
                    plugin_id=raw["id"],
                    display_name=raw["displayName"],
                    summary=raw["summary"],
                    publisher=raw["publisher"],
                    verified_publisher=raw["verifiedPublisher"],
                    repository=raw["repository"],
                    documentation_url=raw["documentationUrl"],
                    icon=raw["icon"],
                    versions=versions,
                )
            )
        return cls(tuple(entries))

    def get(self, plugin_id: str) -> FirstPartyPlugin | None:
        return next(
            (item for item in self.entries if item.plugin_id == plugin_id), None
        )

    def joined_document(
        self, registry: PluginDistributionRegistry
    ) -> dict[str, object]:
        try:
            installed = {
                item.plugin_id: item for item in PluginInstallation.objects.all()
            }
        except (OperationalError, ProgrammingError):
            installed = {}
        items = []
        for entry in self.entries:
            document = entry.to_document()
            installation = installed.get(entry.plugin_id)
            runtime = registry.get(entry.plugin_id)
            latest = entry.latest()
            document.update(
                {
                    "latestVersion": latest.version,
                    "compatible": latest.compatible,
                    "installable": latest.installable,
                    "installed": installation is not None
                    and installation.observed_state != "uninstalled",
                    "installedVersion": (
                        installation.installed_version
                        if installation is not None
                        else None
                    ),
                    "desiredState": (
                        installation.desired_state if installation is not None else None
                    ),
                    "observedState": (
                        installation.observed_state
                        if installation is not None
                        else None
                    ),
                    "health": (
                        installation.aggregate_health
                        if installation is not None
                        else None
                    ),
                    "runtime": runtime.to_document() if runtime is not None else None,
                    "updateAvailable": bool(
                        installation is not None
                        and Version(installation.installed_version)
                        < Version(latest.version)
                    ),
                }
            )
            items.append(document)
        return {"schemaVersion": 1, "items": items}
