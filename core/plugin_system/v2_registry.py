from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata

from opencinema.version import __version__ as OPEN_CINEMA_VERSION

from .contracts import PluginDiagnostic, PluginHealth, PluginLifecycleState
from .manifest import PluginManifestError, read_distribution_manifest
from .v2_contracts import (
    PLUGIN_ENTRY_POINT,
    CompatibilityEvaluation,
    DistributionLifecycleContext,
    OpenCinemaPlugin,
    PluginCapability,
    PluginCapabilityContribution,
    PluginCapabilityDeclaration,
    PluginDesiredState,
    PluginDistributionManifest,
    PluginRuntimeResult,
    ProcessingCapability,
    RuntimeStatus,
    runtime_environment_document,
    validate_runtime_capability_namespace,
)


class PluginDistributionRegistrationError(ValueError):
    pass


class DuplicatePluginDistributionError(PluginDistributionRegistrationError):
    pass


class PluginIdentityMismatchError(PluginDistributionRegistrationError):
    pass


class ProhibitedPluginCapabilityError(PluginDistributionRegistrationError):
    def __init__(self, plugin_id: str, capabilities: Sequence[str]) -> None:
        self.plugin_id = plugin_id
        self.capabilities = tuple(sorted(set(capabilities)))
        super().__init__(
            f"plugin {plugin_id!r} declares prohibited core ownership: "
            + ", ".join(self.capabilities)
        )


PROHIBITED_PERMISSION_PREFIXES = (
    "core.authentication",
    "core.authorization",
    "core.plugin-installation",
    "core.host-command",
    "audio.backend",
    "audio.device-observation",
    "audio.reconciliation",
    "wireplumber.observation",
)

PROHIBITED_RUNTIME_MEMBERS = frozenset(
    {
        "authenticate",
        "authorize",
        "discover_audio_devices",
        "get_audio_backend",
        "get_registered_audio_backends",
        "install_plugin",
        "observe_audio_session",
        "reconcile_audio_graph",
        "register_audio_backend",
        "run_host_command",
        "select_audio_backend",
    }
)


@dataclass(frozen=True, slots=True)
class PluginProvenance:
    source_type: str
    distribution_name: str
    distribution_version: str
    source_url: str | None = None
    resolved_revision: str | None = None
    artifact_digest: str | None = None
    generation_id: str | None = None

    def to_document(self) -> dict[str, object]:
        return {
            "sourceType": self.source_type,
            "distributionName": self.distribution_name,
            "distributionVersion": self.distribution_version,
            "sourceUrl": self.source_url,
            "resolvedRevision": self.resolved_revision,
            "artifactDigest": self.artifact_digest,
            "generationId": self.generation_id,
        }


@dataclass(slots=True)
class PluginCapabilityRecord:
    declaration: PluginCapabilityDeclaration
    contribution: PluginCapabilityContribution | None = None
    state: PluginLifecycleState = PluginLifecycleState.DISCOVERED
    health: PluginHealth = PluginHealth.UNKNOWN
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)

    def diagnostic(self, plugin_id: str, code: str, message: str, **details: object) -> None:
        self.diagnostics.append(
            PluginDiagnostic(
                plugin_id,
                f"capability:{self.declaration.capability_id}",
                code,
                message,
                details,
            )
        )

    def to_document(self) -> dict[str, object]:
        contribution = self.contribution
        return {
            **self.declaration.to_document(),
            "available": self.state
            in {
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.STARTED,
            },
            "state": self.state.value,
            "health": self.health.value,
            "schemaMetadata": (
                dict(contribution.schema_metadata()) if contribution is not None else {}
            ),
            "diagnostics": [item.to_document() for item in self.diagnostics],
        }


@dataclass(slots=True)
class PluginDistributionRecord:
    manifest: PluginDistributionManifest
    provenance: PluginProvenance
    plugin: OpenCinemaPlugin | None = None
    desired_state: PluginDesiredState = PluginDesiredState.ENABLED
    state: PluginLifecycleState = PluginLifecycleState.DISCOVERED
    health: PluginHealth = PluginHealth.UNKNOWN
    compatibility: CompatibilityEvaluation | None = None
    capabilities: list[PluginCapabilityRecord] = field(default_factory=list)
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)

    def diagnostic(self, stage: str, code: str, message: str, **details: object) -> None:
        self.diagnostics.append(
            PluginDiagnostic(self.manifest.plugin_id, stage, code, message, details)
        )

    def refresh_aggregate_health(self) -> None:
        if self.state is PluginLifecycleState.INCOMPATIBLE:
            self.health = PluginHealth.INCOMPATIBLE
            return
        if self.state is PluginLifecycleState.REJECTED:
            self.health = PluginHealth.REJECTED
            return
        capability_health = [item.health for item in self.capabilities]
        if not capability_health or all(item is PluginHealth.FAILED for item in capability_health):
            self.health = PluginHealth.FAILED
            if self.state not in {PluginLifecycleState.STOPPED, PluginLifecycleState.FAILED}:
                self.state = PluginLifecycleState.FAILED
        elif any(
            item in {PluginHealth.FAILED, PluginHealth.DEGRADED} for item in capability_health
        ):
            self.health = PluginHealth.DEGRADED
        elif all(item is PluginHealth.HEALTHY for item in capability_health):
            self.health = PluginHealth.HEALTHY
        else:
            self.health = PluginHealth.UNKNOWN

    def to_document(self) -> dict[str, object]:
        return {
            **self.manifest.to_document(),
            "desiredState": self.desired_state.value,
            "observedState": self.state.value,
            "available": self.state
            in {
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.STARTED,
            },
            "health": self.health.value,
            "aggregateHealth": self.health.value,
            "compatibilityEvaluation": (
                self.compatibility.to_document() if self.compatibility is not None else None
            ),
            "provenance": self.provenance.to_document(),
            "lifecycleImpact": self.manifest.lifecycle.to_document(),
            "capabilities": [item.to_document() for item in self.capabilities],
            "diagnostics": [
                item.to_document()
                for item in (
                    *self.diagnostics,
                    *(diagnostic for cap in self.capabilities for diagnostic in cap.diagnostics),
                )
            ],
        }


def _plugin_instance(loaded: object) -> object:
    if isinstance(loaded, type):
        return loaded()
    if callable(loaded) and not isinstance(loaded, OpenCinemaPlugin):
        return loaded()
    return loaded


def _prohibited_runtime_members(plugin: object) -> tuple[str, ...]:
    return tuple(
        sorted(
            member
            for member in PROHIBITED_RUNTIME_MEMBERS
            if any(member in owner.__dict__ for owner in type(plugin).__mro__[:-1])
        )
    )


def _prohibited_permissions(manifest: PluginDistributionManifest) -> tuple[str, ...]:
    return tuple(
        sorted(
            permission.permission_id
            for permission in manifest.permissions
            if any(
                permission.permission_id == prefix
                or permission.permission_id.startswith(f"{prefix}.")
                for prefix in PROHIBITED_PERMISSION_PREFIXES
            )
        )
    )


class PluginDistributionRegistry:
    """Registry for the unified version-2 plugin distribution contract."""

    def __init__(self) -> None:
        self._records: dict[str, PluginDistributionRecord] = {}
        self._capability_owners: dict[str, str] = {}
        self._discovery_diagnostics: list[PluginDiagnostic] = []

    @property
    def records(self) -> tuple[PluginDistributionRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    @property
    def diagnostics(self) -> tuple[PluginDiagnostic, ...]:
        return tuple(
            [*self._discovery_diagnostics]
            + [
                diagnostic
                for record in self.records
                for diagnostic in (
                    *record.diagnostics,
                    *(item for cap in record.capabilities for item in cap.diagnostics),
                )
            ]
        )

    def get(self, plugin_id: str) -> PluginDistributionRecord | None:
        return self._records.get(plugin_id)

    def _base_record(
        self,
        manifest: PluginDistributionManifest,
        provenance: PluginProvenance | None,
    ) -> PluginDistributionRecord:
        if manifest.plugin_id in self._records:
            raise DuplicatePluginDistributionError(f"duplicate plugin ID {manifest.plugin_id!r}")
        provenance = provenance or PluginProvenance(
            "runtime",
            manifest.distribution_id,
            manifest.version,
            source_url=manifest.source_url,
        )
        record = PluginDistributionRecord(manifest=manifest, provenance=provenance)
        record.capabilities = [
            PluginCapabilityRecord(declaration) for declaration in manifest.capabilities
        ]
        self._records[manifest.plugin_id] = record
        return record

    def register_failed_import(
        self,
        manifest: PluginDistributionManifest,
        provenance: PluginProvenance,
        error: Exception,
    ) -> PluginDistributionRecord:
        record = self._base_record(manifest, provenance)
        record.state = PluginLifecycleState.FAILED
        record.health = PluginHealth.FAILED
        record.diagnostic(
            "import",
            "plugin-entry-point-import-failed",
            str(error),
            exception=type(error).__name__,
        )
        for capability in record.capabilities:
            capability.state = PluginLifecycleState.FAILED
            capability.health = PluginHealth.FAILED
            capability.diagnostic(
                manifest.plugin_id,
                "plugin-import-failed",
                "The plugin distribution could not be imported.",
            )
        return record

    def register(
        self,
        manifest: PluginDistributionManifest,
        plugin: OpenCinemaPlugin,
        *,
        provenance: PluginProvenance | None = None,
    ) -> PluginDistributionRecord:
        if not isinstance(manifest, PluginDistributionManifest):
            raise TypeError("manifest must be PluginDistributionManifest")
        if not isinstance(plugin, OpenCinemaPlugin):
            raise TypeError("entry point must provide OpenCinemaPlugin")
        identity = plugin.identity
        expected_identity = (
            manifest.plugin_id,
            manifest.distribution_id,
            manifest.version,
        )
        actual_identity = (identity.plugin_id, identity.distribution_id, identity.version)
        if actual_identity != expected_identity:
            raise PluginIdentityMismatchError(
                "runtime identity does not match the static manifest: "
                f"expected {expected_identity!r}, got {actual_identity!r}"
            )
        prohibited = (*_prohibited_permissions(manifest), *_prohibited_runtime_members(plugin))
        if prohibited:
            raise ProhibitedPluginCapabilityError(manifest.plugin_id, prohibited)

        record = self._base_record(manifest, provenance)
        record.plugin = plugin
        compatibility = manifest.evaluate_compatibility(open_cinema_version=OPEN_CINEMA_VERSION)
        record.compatibility = compatibility
        if not compatibility.compatible:
            record.state = PluginLifecycleState.INCOMPATIBLE
            record.health = PluginHealth.INCOMPATIBLE
            record.diagnostic(
                "compatibility",
                "plugin-incompatible",
                "The plugin is not compatible with this Open Cinema runtime.",
                reasons=list(compatibility.reasons),
                runtime=runtime_environment_document(),
                openCinemaVersion=OPEN_CINEMA_VERSION,
            )
            for capability in record.capabilities:
                capability.state = PluginLifecycleState.INCOMPATIBLE
                capability.health = PluginHealth.INCOMPATIBLE
            return record

        try:
            contributions = tuple(plugin.capabilities())
        except Exception as error:
            record.state = PluginLifecycleState.FAILED
            record.health = PluginHealth.FAILED
            record.diagnostic(
                "capabilities",
                "plugin-capability-enumeration-failed",
                str(error),
                exception=type(error).__name__,
            )
            for capability in record.capabilities:
                capability.state = PluginLifecycleState.FAILED
                capability.health = PluginHealth.FAILED
            return record

        runtime_by_id: dict[str, PluginCapabilityContribution] = {}
        duplicate_runtime_ids: set[str] = set()
        invalid_runtime: list[tuple[object, Exception]] = []
        for contribution in contributions:
            try:
                if not isinstance(contribution, PluginCapability):
                    raise TypeError("runtime capability must use a typed capability descriptor")
                validate_runtime_capability_namespace(manifest.plugin_id, contribution)
            except Exception as error:
                invalid_runtime.append((contribution, error))
                continue
            if contribution.capability_id in runtime_by_id:
                duplicate_runtime_ids.add(contribution.capability_id)
            else:
                runtime_by_id[contribution.capability_id] = contribution

        declared_ids = {item.declaration.capability_id for item in record.capabilities}
        for capability_record in record.capabilities:
            declaration = capability_record.declaration
            contribution = runtime_by_id.get(declaration.capability_id)
            if declaration.capability_id in duplicate_runtime_ids:
                capability_record.state = PluginLifecycleState.REJECTED
                capability_record.health = PluginHealth.REJECTED
                capability_record.diagnostic(
                    manifest.plugin_id,
                    "duplicate-runtime-capability",
                    "The runtime returned the capability more than once.",
                )
                continue
            owner = self._capability_owners.get(declaration.capability_id)
            if owner is not None:
                capability_record.state = PluginLifecycleState.REJECTED
                capability_record.health = PluginHealth.REJECTED
                capability_record.diagnostic(
                    manifest.plugin_id,
                    "duplicate-capability-id",
                    "Another plugin already owns this capability ID.",
                    ownerPluginId=owner,
                )
                continue
            if contribution is None:
                capability_record.state = PluginLifecycleState.FAILED
                capability_record.health = PluginHealth.FAILED
                capability_record.diagnostic(
                    manifest.plugin_id,
                    "declared-capability-missing",
                    "The static manifest capability was not returned at runtime.",
                )
                continue
            if (
                contribution.kind is not declaration.kind
                or contribution.version != declaration.version
            ):
                capability_record.state = PluginLifecycleState.REJECTED
                capability_record.health = PluginHealth.REJECTED
                capability_record.diagnostic(
                    manifest.plugin_id,
                    "capability-contract-mismatch",
                    "Runtime capability kind or version does not match the static manifest.",
                    declaredKind=declaration.kind.value,
                    runtimeKind=contribution.kind.value,
                    declaredVersion=declaration.version,
                    runtimeVersion=contribution.version,
                )
                continue
            capability_record.contribution = contribution
            capability_record.state = PluginLifecycleState.AVAILABLE
            capability_record.health = PluginHealth.HEALTHY
            self._capability_owners[declaration.capability_id] = manifest.plugin_id

        for contribution, error in invalid_runtime:
            record.diagnostic(
                "capabilities",
                "invalid-runtime-capability",
                str(error),
                returnedType=type(contribution).__name__,
            )
        for capability_id in sorted(set(runtime_by_id) - declared_ids):
            record.diagnostic(
                "capabilities",
                "undeclared-runtime-capability",
                "A runtime capability was omitted from the static manifest and was rejected.",
                capabilityId=capability_id,
            )
        record.state = PluginLifecycleState.AVAILABLE
        record.refresh_aggregate_health()
        return record

    def discover(
        self,
        *,
        entry_points_provider: Callable[[], object] = metadata.entry_points,
    ) -> tuple[PluginDistributionRecord, ...]:
        try:
            entry_points = entry_points_provider()
            if hasattr(entry_points, "select"):
                candidates = tuple(entry_points.select(group=PLUGIN_ENTRY_POINT))
            elif isinstance(entry_points, Mapping):
                candidates = tuple(entry_points.get(PLUGIN_ENTRY_POINT, ()))
            else:
                candidates = tuple(
                    item
                    for item in entry_points
                    if getattr(item, "group", None) == PLUGIN_ENTRY_POINT
                )
        except Exception as error:
            self._discovery_diagnostics.append(
                PluginDiagnostic(
                    "entry-points",
                    "discovery",
                    "entry-point-enumeration-failed",
                    str(error),
                    {"exception": type(error).__name__, "group": PLUGIN_ENTRY_POINT},
                )
            )
            return self.records
        for entry_point in candidates:
            entry_name = str(getattr(entry_point, "name", "unknown-entry-point"))
            distribution = getattr(entry_point, "dist", None)
            if distribution is None:
                self._discovery_diagnostics.append(
                    PluginDiagnostic(
                        entry_name,
                        "manifest",
                        "entry-point-distribution-missing",
                        "The entry point does not expose its distribution metadata.",
                        {"group": PLUGIN_ENTRY_POINT},
                    )
                )
                continue
            try:
                manifest = read_distribution_manifest(distribution)
            except PluginManifestError as error:
                self._discovery_diagnostics.append(
                    PluginDiagnostic(
                        entry_name,
                        "manifest",
                        error.issue.code,
                        error.issue.message,
                        {"group": PLUGIN_ENTRY_POINT},
                    )
                )
                continue
            provenance = PluginProvenance(
                "installed-distribution",
                str(getattr(distribution, "name", manifest.distribution_id)),
                str(getattr(distribution, "version", manifest.version)),
                source_url=manifest.source_url,
            )
            if entry_name != manifest.plugin_id:
                self._discovery_diagnostics.append(
                    PluginDiagnostic(
                        manifest.plugin_id,
                        "identity",
                        "entry-point-name-mismatch",
                        "The entry-point name must match the static plugin ID.",
                        {"entryPointName": entry_name, "group": PLUGIN_ENTRY_POINT},
                    )
                )
                continue
            try:
                loaded = _plugin_instance(entry_point.load())
            except Exception as error:
                try:
                    self.register_failed_import(manifest, provenance, error)
                except DuplicatePluginDistributionError as duplicate:
                    self._discovery_diagnostics.append(
                        PluginDiagnostic(
                            manifest.plugin_id,
                            "discovery",
                            "duplicate-plugin-id",
                            str(duplicate),
                            {"group": PLUGIN_ENTRY_POINT},
                        )
                    )
                continue
            try:
                self.register(manifest, loaded, provenance=provenance)
            except Exception as error:
                code = "plugin-registration-failed"
                details: dict[str, object] = {
                    "group": PLUGIN_ENTRY_POINT,
                    "exception": type(error).__name__,
                }
                if isinstance(error, DuplicatePluginDistributionError):
                    code = "duplicate-plugin-id"
                elif isinstance(error, PluginIdentityMismatchError):
                    code = "plugin-identity-mismatch"
                elif isinstance(error, ProhibitedPluginCapabilityError):
                    code = "prohibited-plugin-capability"
                    details["capabilities"] = list(error.capabilities)
                self._discovery_diagnostics.append(
                    PluginDiagnostic(
                        manifest.plugin_id,
                        "discovery",
                        code,
                        str(error),
                        details,
                    )
                )
        return self.records

    def start_enabled(self, settings: Mapping[str, object] | None = None) -> None:
        for record in self.records:
            if (
                record.plugin is None
                or record.desired_state is not PluginDesiredState.ENABLED
                or record.state is not PluginLifecycleState.AVAILABLE
            ):
                continue
            try:
                result = record.plugin.start(
                    DistributionLifecycleContext(record.manifest.plugin_id, settings or {})
                )
                if not isinstance(result, PluginRuntimeResult):
                    raise TypeError("start must return PluginRuntimeResult")
            except Exception as error:
                record.state = PluginLifecycleState.FAILED
                record.health = PluginHealth.FAILED
                record.diagnostic(
                    "start",
                    "plugin-start-failed",
                    str(error),
                    exception=type(error).__name__,
                )
                continue
            record.state = PluginLifecycleState.STARTED
            record.health = {
                RuntimeStatus.READY: PluginHealth.HEALTHY,
                RuntimeStatus.DEGRADED: PluginHealth.DEGRADED,
                RuntimeStatus.FAILED: PluginHealth.FAILED,
                RuntimeStatus.UNAVAILABLE: PluginHealth.FAILED,
            }[result.status]

    def stop_enabled(self, settings: Mapping[str, object] | None = None) -> None:
        for record in reversed(self.records):
            if record.plugin is None or record.state is not PluginLifecycleState.STARTED:
                continue
            try:
                result = record.plugin.stop(
                    DistributionLifecycleContext(record.manifest.plugin_id, settings or {})
                )
                if not isinstance(result, PluginRuntimeResult):
                    raise TypeError("stop must return PluginRuntimeResult")
            except Exception as error:
                record.state = PluginLifecycleState.FAILED
                record.health = PluginHealth.FAILED
                record.diagnostic(
                    "stop", "plugin-stop-failed", str(error), exception=type(error).__name__
                )
            else:
                record.state = PluginLifecycleState.STOPPED
                record.health = (
                    PluginHealth.HEALTHY
                    if result.status is RuntimeStatus.READY
                    else PluginHealth.DEGRADED
                )

    def enabled_capabilities(
        self, capability_type: type[PluginCapabilityContribution] | None = None
    ) -> tuple[PluginCapabilityContribution, ...]:
        contributions = []
        for record in self.records:
            if record.desired_state is not PluginDesiredState.ENABLED or record.state not in {
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.STARTED,
            }:
                continue
            for capability in record.capabilities:
                contribution = capability.contribution
                if (
                    contribution is not None
                    and capability.state
                    in {PluginLifecycleState.AVAILABLE, PluginLifecycleState.STARTED}
                    and (capability_type is None or isinstance(contribution, capability_type))
                ):
                    contributions.append(contribution)
        return tuple(contributions)

    def capability_records(
        self, capability_type: type[PluginCapabilityContribution] | None = None
    ) -> tuple[tuple[PluginDistributionRecord, PluginCapabilityRecord], ...]:
        values = []
        for record in self.records:
            if record.desired_state is not PluginDesiredState.ENABLED or record.state not in {
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.STARTED,
            }:
                continue
            for capability in record.capabilities:
                contribution = capability.contribution
                if (
                    contribution is not None
                    and capability.state
                    in {PluginLifecycleState.AVAILABLE, PluginLifecycleState.STARTED}
                    and (capability_type is None or isinstance(contribution, capability_type))
                ):
                    values.append((record, capability))
        return tuple(values)

    def processing_node_owner(self, type_id: str, version: int) -> PluginDistributionRecord | None:
        for record, capability_record in self.capability_records(ProcessingCapability):
            contribution = capability_record.contribution
            if not isinstance(contribution, ProcessingCapability):
                continue
            if any(
                item.type_id == type_id and item.version == version
                for item in contribution.node_types
            ):
                return record
        return None

    def node_type_owner(self, type_id: str, version: int) -> PluginDistributionRecord | None:
        return self.processing_node_owner(type_id, version)

    def processing_node_manifests(
        self,
    ) -> tuple[tuple[PluginDistributionRecord, PluginCapabilityRecord, object], ...]:
        values = []
        for record in self.records:
            for capability_record in record.capabilities:
                contribution = capability_record.contribution
                if not isinstance(contribution, ProcessingCapability):
                    continue
                for manifest in contribution.node_types:
                    values.append((record, capability_record, manifest))
        return tuple(values)

    def register_node_types(self, node_registry) -> tuple[PluginDiagnostic, ...]:
        diagnostics = []
        for record, capability_record in self.capability_records(ProcessingCapability):
            contribution = capability_record.contribution
            if not isinstance(contribution, ProcessingCapability):
                continue
            for manifest in contribution.node_types:
                try:
                    node_registry.register(manifest.to_node_type_definition())
                except Exception as error:
                    diagnostic = PluginDiagnostic(
                        record.manifest.plugin_id,
                        f"capability:{capability_record.declaration.capability_id}",
                        "processing-node-schema-registration-failed",
                        str(error),
                        {
                            "typeId": manifest.type_id,
                            "version": manifest.version,
                            "exception": type(error).__name__,
                        },
                    )
                    capability_record.diagnostics.append(diagnostic)
                    capability_record.health = PluginHealth.DEGRADED
                    diagnostics.append(diagnostic)
            record.refresh_aggregate_health()
        return tuple(diagnostics)

    def catalogue_document(self) -> dict[str, object]:
        return {
            "contractVersion": 2,
            "entryPoint": PLUGIN_ENTRY_POINT,
            "plugins": [record.to_document() for record in self.records],
            "discoveryDiagnostics": [
                diagnostic.to_document() for diagnostic in self._discovery_diagnostics
            ],
        }
