from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from django.db import OperationalError, ProgrammingError
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from api.models import PluginInstallation
from opencinema.version import __version__ as OPEN_CINEMA_VERSION

from .v2_contracts import PLUGIN_CONTRACT_VERSION_V2, validate_contract_document
from .v2_registry import PluginDistributionRegistry


@dataclass(frozen=True, slots=True)
class CatalogueVersion:
    version: str
    revision: str
    resolved_commit: str | None
    artifact_digest: str | None
    mutable: bool
    published: bool
    contract_minimum: int
    contract_maximum: int
    open_cinema: str
    capabilities: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return (
            self.contract_minimum <= PLUGIN_CONTRACT_VERSION_V2 <= self.contract_maximum
            and Version(OPEN_CINEMA_VERSION) in SpecifierSet(self.open_cinema)
        )

    def to_document(self) -> dict[str, object]:
        return {
            "version": self.version,
            "revision": self.revision,
            "resolvedCommit": self.resolved_commit,
            "artifactDigest": self.artifact_digest,
            "mutable": self.mutable,
            "published": self.published,
            "pluginContract": {
                "minimum": self.contract_minimum,
                "maximum": self.contract_maximum,
            },
            "openCinema": self.open_cinema,
            "capabilities": list(self.capabilities),
            "compatible": self.compatible,
            "installable": self.compatible and self.published,
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
                    artifact_digest=item.get("artifactDigest"),
                    mutable=item["mutable"],
                    published=item["published"],
                    contract_minimum=item["pluginContract"]["minimum"],
                    contract_maximum=item["pluginContract"]["maximum"],
                    open_cinema=item["openCinema"],
                    capabilities=tuple(item["capabilities"]),
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
        return next((item for item in self.entries if item.plugin_id == plugin_id), None)

    def joined_document(self, registry: PluginDistributionRegistry) -> dict[str, object]:
        try:
            installed = {item.plugin_id: item for item in PluginInstallation.objects.all()}
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
                    "installable": latest.compatible and latest.published,
                    "installed": installation is not None
                    and installation.observed_state != "uninstalled",
                    "installedVersion": (
                        installation.installed_version if installation is not None else None
                    ),
                    "desiredState": (
                        installation.desired_state if installation is not None else None
                    ),
                    "observedState": (
                        installation.observed_state if installation is not None else None
                    ),
                    "health": (installation.aggregate_health if installation is not None else None),
                    "runtime": runtime.to_document() if runtime is not None else None,
                    "updateAvailable": bool(
                        installation is not None
                        and Version(installation.installed_version) < Version(latest.version)
                    ),
                }
            )
            items.append(document)
        return {"schemaVersion": 1, "items": items}
