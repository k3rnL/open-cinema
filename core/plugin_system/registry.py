from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata

from .contracts import (
    APPLICATION_PLUGIN_ENTRY_POINT,
    PLUGIN_CONTRACT_VERSION,
    PROCESSING_PLUGIN_ENTRY_POINT,
    ApplicationLifecycleContext,
    ApplicationPlugin,
    PluginDiagnostic,
    PluginHealth,
    PluginKind,
    PluginLifecycleState,
    ProcessingNodeTypeManifest,
    ProcessingPlugin,
)


class PluginRegistrationError(ValueError):
    pass


class DuplicatePluginIdError(PluginRegistrationError):
    pass


class ProhibitedAudioCapabilityError(PluginRegistrationError):
    def __init__(self, plugin_id: str, capabilities: Sequence[str]) -> None:
        self.plugin_id = plugin_id
        self.capabilities = tuple(capabilities)
        super().__init__(
            f"plugin {plugin_id!r} declares prohibited audio ownership capabilities: "
            + ", ".join(self.capabilities)
        )


PROHIBITED_AUDIO_PLUGIN_CAPABILITIES = frozenset(
    {
        "audio_backend",
        "discover_audio_devices",
        "get_audio_backend",
        "get_registered_audio_backends",
        "observe_audio_session",
        "register_audio_backend",
        "select_audio_backend",
    }
)


@dataclass(slots=True)
class PluginRecord:
    plugin: ApplicationPlugin | ProcessingPlugin
    state: PluginLifecycleState = PluginLifecycleState.DISCOVERED
    health: PluginHealth = PluginHealth.UNKNOWN
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)
    node_types: tuple[ProcessingNodeTypeManifest, ...] = ()

    @property
    def manifest(self):
        return self.plugin.manifest

    def diagnostic(self, stage: str, code: str, message: str, **details: object) -> None:
        self.diagnostics.append(
            PluginDiagnostic(
                self.manifest.plugin_id,
                stage,
                code,
                message,
                details,
            )
        )

    def to_document(self) -> dict[str, object]:
        return {
            **self.manifest.to_document(),
            "available": self.state
            in {PluginLifecycleState.AVAILABLE, PluginLifecycleState.STARTED},
            "state": self.state.value,
            "health": self.health.value,
            "diagnostics": [item.to_document() for item in self.diagnostics],
            "nodeTypes": [item.to_document() for item in self.node_types],
        }


def _declared_prohibited_capabilities(plugin: object) -> tuple[str, ...]:
    capabilities = []
    for capability in PROHIBITED_AUDIO_PLUGIN_CAPABILITIES:
        if any(capability in owner.__dict__ for owner in type(plugin).__mro__[:-1]):
            capabilities.append(capability)
    return tuple(sorted(capabilities))


def _entry_points_for(entry_points: object, group: str) -> tuple[object, ...]:
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))
    if isinstance(entry_points, Mapping):
        return tuple(entry_points.get(group, ()))
    return tuple(item for item in entry_points if getattr(item, "group", None) == group)


def _plugin_instance(loaded: object) -> object:
    if isinstance(loaded, type):
        return loaded()
    if callable(loaded) and not isinstance(loaded, (ApplicationPlugin, ProcessingPlugin)):
        return loaded()
    return loaded


class PluginRegistry:
    def __init__(self) -> None:
        self._records: dict[str, PluginRecord] = {}
        self._discovery_diagnostics: list[PluginDiagnostic] = []
        self._node_owners: dict[tuple[str, int], str] = {}

    @property
    def records(self) -> tuple[PluginRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    @property
    def diagnostics(self) -> tuple[PluginDiagnostic, ...]:
        return tuple(
            [*self._discovery_diagnostics]
            + [diagnostic for record in self.records for diagnostic in record.diagnostics]
        )

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self._records.get(plugin_id)

    def _register(self, plugin: object, expected_kind: PluginKind) -> PluginRecord:
        expected_type = (
            ApplicationPlugin if expected_kind is PluginKind.APPLICATION else ProcessingPlugin
        )
        if not isinstance(plugin, expected_type):
            raise TypeError(f"entry point must provide {expected_type.__name__}")
        manifest = plugin.manifest
        if manifest.kind is not expected_kind:
            raise PluginRegistrationError(
                f"plugin {manifest.plugin_id!r} manifest kind does not match its contract"
            )
        if manifest.plugin_id in self._records:
            raise DuplicatePluginIdError(f"duplicate plugin ID {manifest.plugin_id!r}")
        prohibited = _declared_prohibited_capabilities(plugin)
        if prohibited:
            raise ProhibitedAudioCapabilityError(manifest.plugin_id, prohibited)
        node_types = ()
        if isinstance(plugin, ProcessingPlugin):
            node_types = tuple(plugin.node_types())
            if not node_types:
                raise PluginRegistrationError("processing plugins must register a node type")
            if any(not isinstance(item, ProcessingNodeTypeManifest) for item in node_types):
                raise TypeError("processing node types must use ProcessingNodeTypeManifest")
            expected_prefix = f"plugin.{manifest.plugin_id}."
            for item in node_types:
                if not item.type_id.startswith(expected_prefix):
                    raise PluginRegistrationError(
                        f"processing node type {item.type_id!r} must use prefix {expected_prefix!r}"
                    )
                key = (item.type_id, item.version)
                if (
                    key in self._node_owners
                    or sum(
                        candidate.type_id == item.type_id and candidate.version == item.version
                        for candidate in node_types
                    )
                    > 1
                ):
                    raise PluginRegistrationError(
                        f"duplicate processing node type {item.type_id!r} v{item.version}"
                    )
        record = PluginRecord(plugin=plugin, node_types=node_types)
        self._records[manifest.plugin_id] = record
        for item in node_types:
            self._node_owners[(item.type_id, item.version)] = manifest.plugin_id
        if not manifest.compatibility.supports(PLUGIN_CONTRACT_VERSION):
            record.state = PluginLifecycleState.INCOMPATIBLE
            record.health = PluginHealth.INCOMPATIBLE
            record.diagnostic(
                "compatibility",
                "plugin-contract-incompatible",
                "The plugin contract range does not include this Open Cinema runtime.",
                compatibility=manifest.compatibility.to_document(),
            )
            return record
        record.state = PluginLifecycleState.AVAILABLE
        record.health = PluginHealth.HEALTHY
        return record

    def register_application(self, plugin: ApplicationPlugin) -> PluginRecord:
        return self._register(plugin, PluginKind.APPLICATION)

    def register_processing(self, plugin: ProcessingPlugin) -> PluginRecord:
        return self._register(plugin, PluginKind.PROCESSING)

    def discover(
        self,
        *,
        entry_points_provider: Callable[[], object] = metadata.entry_points,
    ) -> tuple[PluginRecord, ...]:
        try:
            entry_points = entry_points_provider()
        except Exception as error:
            self._discovery_diagnostics.append(
                PluginDiagnostic(
                    "entry-points",
                    "discovery",
                    "entry-point-enumeration-failed",
                    str(error),
                    {"exception": type(error).__name__},
                )
            )
            return self.records
        for group, register in (
            (APPLICATION_PLUGIN_ENTRY_POINT, self.register_application),
            (PROCESSING_PLUGIN_ENTRY_POINT, self.register_processing),
        ):
            for entry_point in _entry_points_for(entry_points, group):
                entry_name = getattr(entry_point, "name", "unknown-entry-point")
                try:
                    register(_plugin_instance(entry_point.load()))
                except Exception as error:
                    code = "plugin-entry-point-load-failed"
                    details = {"group": group, "exception": type(error).__name__}
                    if isinstance(error, ProhibitedAudioCapabilityError):
                        code = "prohibited-audio-capability"
                        details["capabilities"] = list(error.capabilities)
                    elif isinstance(error, DuplicatePluginIdError):
                        code = "duplicate-plugin-id"
                    self._discovery_diagnostics.append(
                        PluginDiagnostic(
                            str(entry_name),
                            "discovery",
                            code,
                            str(error),
                            details,
                        )
                    )
        return self.records

    def start_applications(self, context: ApplicationLifecycleContext) -> None:
        if not isinstance(context, ApplicationLifecycleContext):
            raise TypeError("context must be ApplicationLifecycleContext")
        for record in self.records:
            if not isinstance(record.plugin, ApplicationPlugin):
                continue
            if record.state is not PluginLifecycleState.AVAILABLE:
                continue
            try:
                record.plugin.start(context)
            except Exception as error:
                record.state = PluginLifecycleState.FAILED
                record.health = PluginHealth.FAILED
                record.diagnostic(
                    "start",
                    "application-plugin-start-failed",
                    str(error),
                    exception=type(error).__name__,
                )
            else:
                record.state = PluginLifecycleState.STARTED
                record.health = PluginHealth.HEALTHY

    def stop_applications(self, context: ApplicationLifecycleContext) -> None:
        if not isinstance(context, ApplicationLifecycleContext):
            raise TypeError("context must be ApplicationLifecycleContext")
        for record in reversed(self.records):
            if not isinstance(record.plugin, ApplicationPlugin):
                continue
            if record.state is not PluginLifecycleState.STARTED:
                continue
            try:
                record.plugin.stop(context)
            except Exception as error:
                record.state = PluginLifecycleState.FAILED
                record.health = PluginHealth.FAILED
                record.diagnostic(
                    "stop",
                    "application-plugin-stop-failed",
                    str(error),
                    exception=type(error).__name__,
                )
            else:
                record.state = PluginLifecycleState.STOPPED
                record.health = PluginHealth.HEALTHY

    def application_plugins(self) -> tuple[ApplicationPlugin, ...]:
        return tuple(
            record.plugin
            for record in self.records
            if isinstance(record.plugin, ApplicationPlugin)
            and record.state in {PluginLifecycleState.AVAILABLE, PluginLifecycleState.STARTED}
        )

    def processing_plugins(self) -> tuple[ProcessingPlugin, ...]:
        return tuple(
            record.plugin
            for record in self.records
            if isinstance(record.plugin, ProcessingPlugin)
            and record.state is PluginLifecycleState.AVAILABLE
        )

    def node_type_owner(self, type_id: str, version: int) -> PluginRecord | None:
        plugin_id = self._node_owners.get((type_id, version))
        return self._records.get(plugin_id) if plugin_id is not None else None

    def register_node_types(self, node_registry) -> tuple[PluginDiagnostic, ...]:
        diagnostics = []
        for record in self.records:
            if not isinstance(record.plugin, ProcessingPlugin):
                continue
            if record.state is not PluginLifecycleState.AVAILABLE:
                continue
            for manifest in record.node_types:
                try:
                    node_registry.register(manifest.to_node_type_definition())
                except Exception as error:
                    diagnostic = PluginDiagnostic(
                        record.manifest.plugin_id,
                        "schema",
                        "processing-node-schema-registration-failed",
                        str(error),
                        {
                            "typeId": manifest.type_id,
                            "version": manifest.version,
                            "exception": type(error).__name__,
                        },
                    )
                    record.diagnostics.append(diagnostic)
                    record.health = PluginHealth.DEGRADED
                    diagnostics.append(diagnostic)
        return tuple(diagnostics)

    def catalogue_document(self) -> dict[str, object]:
        failed = [item.to_document() for item in self._discovery_diagnostics]
        return {
            "contractVersion": PLUGIN_CONTRACT_VERSION,
            "entryPointGroups": {
                "application": APPLICATION_PLUGIN_ENTRY_POINT,
                "processing": PROCESSING_PLUGIN_ENTRY_POINT,
            },
            "plugins": [record.to_document() for record in self.records],
            "discoveryDiagnostics": failed,
        }

    def plan_availability_explanation(
        self,
        required_node_types: Iterable[tuple[str, int]],
    ) -> dict[str, object]:
        nodes = []
        for type_id, version in sorted(set(required_node_types)):
            owner = self.node_type_owner(type_id, version)
            if owner is None:
                nodes.append(
                    {
                        "typeId": type_id,
                        "version": version,
                        "available": False,
                        "pluginId": None,
                        "pluginHealth": None,
                        "reason": "processing-plugin-or-node-type-unavailable",
                        "incompatibility": None,
                    }
                )
                continue
            incompatible = next(
                (
                    item.to_document()
                    for item in owner.diagnostics
                    if item.code == "plugin-contract-incompatible"
                ),
                None,
            )
            nodes.append(
                {
                    "typeId": type_id,
                    "version": version,
                    "available": owner.state is PluginLifecycleState.AVAILABLE,
                    "pluginId": owner.manifest.plugin_id,
                    "pluginHealth": owner.health.value,
                    "configurationVersion": next(
                        item.configuration_version
                        for item in owner.node_types
                        if item.type_id == type_id and item.version == version
                    ),
                    "reason": (
                        "available"
                        if owner.state is PluginLifecycleState.AVAILABLE
                        else "plugin-unavailable"
                    ),
                    "incompatibility": incompatible,
                }
            )
        return {
            "kind": "processing-plugin-availability",
            "contractVersion": PLUGIN_CONTRACT_VERSION,
            "nodes": nodes,
        }
