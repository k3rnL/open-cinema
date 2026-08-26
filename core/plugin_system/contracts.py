from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from wyreplumber.runtime import FrozenDict, freeze_json, thaw_json

from core.orchestration.node_catalogue import NodePortDefinition, NodeTypeDefinition

PLUGIN_CONTRACT_VERSION = 1
APPLICATION_PLUGIN_ENTRY_POINT = "open_cinema.application_plugins"
PROCESSING_PLUGIN_ENTRY_POINT = "open_cinema.processing_plugins"


def _required_text(value: object, field_name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be a non-empty string of at most {maximum} characters")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


class PluginKind(StrEnum):
    APPLICATION = "application"
    PROCESSING = "processing"


class PluginLifecycleState(StrEnum):
    DISCOVERED = "discovered"
    AVAILABLE = "available"
    STARTED = "started"
    STOPPED = "stopped"
    INCOMPATIBLE = "incompatible"
    FAILED = "failed"
    REJECTED = "rejected"


class PluginHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    INCOMPATIBLE = "incompatible"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    plugin_id: str
    stage: str
    code: str
    message: str
    details: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        for name in ("plugin_id", "stage", "code", "message"):
            _required_text(getattr(self, name), name, maximum=2048)
        object.__setattr__(self, "details", FrozenDict(self.details))

    def to_document(self) -> dict[str, object]:
        return {
            "pluginId": self.plugin_id,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "details": self.details.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PluginCompatibility:
    minimum_contract: int = PLUGIN_CONTRACT_VERSION
    maximum_contract: int = PLUGIN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _positive_int(self.minimum_contract, "minimum_contract")
        _positive_int(self.maximum_contract, "maximum_contract")
        if self.minimum_contract > self.maximum_contract:
            raise ValueError("minimum_contract cannot exceed maximum_contract")

    def supports(self, version: int = PLUGIN_CONTRACT_VERSION) -> bool:
        return self.minimum_contract <= version <= self.maximum_contract

    def to_document(self) -> dict[str, int]:
        return {
            "minimum": self.minimum_contract,
            "maximum": self.maximum_contract,
            "runtime": PLUGIN_CONTRACT_VERSION,
        }


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    display_name: str
    version: str
    description: str
    compatibility: PluginCompatibility = field(default_factory=PluginCompatibility)

    def __post_init__(self) -> None:
        plugin_id = _required_text(self.plugin_id, "plugin_id")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in plugin_id
        ):
            raise ValueError("plugin_id must use lowercase letters, digits, dots, and hyphens")
        for name in ("display_name", "version", "description"):
            _required_text(getattr(self, name), name, maximum=2048)
        if not isinstance(self.compatibility, PluginCompatibility):
            raise TypeError("compatibility must be PluginCompatibility")

    @property
    @abstractmethod
    def kind(self) -> PluginKind:
        raise NotImplementedError

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.plugin_id,
            "kind": self.kind.value,
            "displayName": self.display_name,
            "version": self.version,
            "description": self.description,
            "compatibility": self.compatibility.to_document(),
        }


@dataclass(frozen=True, slots=True)
class ApplicationPluginManifest(PluginManifest):
    route_namespace: str | None = None
    model_packages: tuple[str, ...] = ()
    automation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super(ApplicationPluginManifest, self).__post_init__()
        if self.route_namespace is not None:
            _required_text(self.route_namespace, "route_namespace")
        for collection_name in ("model_packages", "automation_ids"):
            values = tuple(getattr(self, collection_name))
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{collection_name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{collection_name} must not contain duplicates")
            object.__setattr__(self, collection_name, values)

    @property
    def kind(self) -> PluginKind:
        return PluginKind.APPLICATION

    def to_document(self) -> dict[str, object]:
        return {
            **super(ApplicationPluginManifest, self).to_document(),
            "routeNamespace": self.route_namespace,
            "modelPackages": list(self.model_packages),
            "automationIds": list(self.automation_ids),
        }


@dataclass(frozen=True, slots=True)
class ProcessingPluginManifest(PluginManifest):
    driver_contract_version: int = 1

    def __post_init__(self) -> None:
        super(ProcessingPluginManifest, self).__post_init__()
        _positive_int(self.driver_contract_version, "driver_contract_version")

    @property
    def kind(self) -> PluginKind:
        return PluginKind.PROCESSING

    def to_document(self) -> dict[str, object]:
        return {
            **super(ProcessingPluginManifest, self).to_document(),
            "driverContractVersion": self.driver_contract_version,
        }


@dataclass(frozen=True, slots=True)
class ConfigurationMigration:
    from_version: int
    to_version: int
    migrate: Callable[[Mapping[str, object]], Mapping[str, object]]

    def __post_init__(self) -> None:
        _positive_int(self.from_version, "from_version")
        _positive_int(self.to_version, "to_version")
        if self.to_version != self.from_version + 1:
            raise ValueError("configuration migrations must advance exactly one version")
        if not callable(self.migrate):
            raise TypeError("configuration migration must be callable")


@dataclass(frozen=True, slots=True)
class ProcessingNodeTypeManifest:
    type_id: str
    version: int
    configuration_version: int
    display_name: str
    category: str
    description: str
    ports: tuple[NodePortDefinition, ...]
    configuration_schema: Mapping[str, object]
    editable_fields: tuple[str, ...]
    migrations: tuple[ConfigurationMigration, ...] = ()

    def __post_init__(self) -> None:
        _positive_int(self.configuration_version, "configuration_version")
        definition = self.to_node_type_definition()
        object.__setattr__(self, "ports", definition.ports)
        object.__setattr__(self, "configuration_schema", definition.configuration_schema)
        editable_fields = tuple(self.editable_fields)
        if any(not isinstance(path, str) or not path.startswith("/") for path in editable_fields):
            raise ValueError("editable_fields must contain JSON pointer paths")
        if len(editable_fields) != len(set(editable_fields)):
            raise ValueError("editable_fields must not contain duplicates")
        object.__setattr__(self, "editable_fields", editable_fields)
        migrations = tuple(self.migrations)
        if any(not isinstance(item, ConfigurationMigration) for item in migrations):
            raise TypeError("migrations must contain ConfigurationMigration values")
        by_source = {item.from_version: item for item in migrations}
        if len(by_source) != len(migrations):
            raise ValueError("configuration migration sources must be unique")
        object.__setattr__(self, "migrations", migrations)

    def to_node_type_definition(self) -> NodeTypeDefinition:
        return NodeTypeDefinition(
            type_id=self.type_id,
            version=self.version,
            display_name=self.display_name,
            category=self.category,
            description=self.description,
            ports=tuple(self.ports),
            configuration_schema=dict(self.configuration_schema),
        )

    def migrate_configuration(
        self,
        configuration: Mapping[str, object],
        *,
        from_version: int,
    ) -> FrozenDict:
        _positive_int(from_version, "from_version")
        if from_version > self.configuration_version:
            raise ValueError("configuration version is newer than the installed node type")
        current = dict(configuration)
        migrations = {item.from_version: item for item in self.migrations}
        version = from_version
        while version < self.configuration_version:
            migration = migrations.get(version)
            if migration is None:
                raise ValueError(f"missing configuration migration from version {version}")
            migrated = migration.migrate(FrozenDict(current))
            if not isinstance(migrated, Mapping):
                raise TypeError("configuration migration must return a mapping")
            current = dict(migrated)
            version = migration.to_version
        errors = tuple(Draft202012Validator(dict(self.configuration_schema)).iter_errors(current))
        if errors:
            raise ValueError(
                "migrated configuration is invalid: " + "; ".join(error.message for error in errors)
            )
        frozen = freeze_json(current)
        if not isinstance(frozen, FrozenDict):
            raise TypeError("migrated configuration must remain an object")
        return frozen

    def to_document(self) -> dict[str, object]:
        return {
            **self.to_node_type_definition().to_document(),
            "configurationVersion": self.configuration_version,
            "editableFields": list(self.editable_fields),
            "migrations": [
                {"from": item.from_version, "to": item.to_version}
                for item in sorted(self.migrations, key=lambda migration: migration.from_version)
            ],
        }


@dataclass(frozen=True, slots=True)
class ApplicationLifecycleContext:
    settings: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", FrozenDict(self.settings))


class ApplicationPlugin(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ApplicationPluginManifest:
        raise NotImplementedError

    def get_urls(self) -> Sequence[object]:
        return ()

    def automation_hooks(self) -> Mapping[str, Callable[..., object]]:
        return {}

    def start(self, context: ApplicationLifecycleContext) -> None:
        return None

    def stop(self, context: ApplicationLifecycleContext) -> None:
        return None

    @property
    def plugin_name(self) -> str:
        return self.manifest.route_namespace or self.manifest.plugin_id


@dataclass(frozen=True, slots=True)
class ProcessingHookContext:
    node_instance_id: str
    configuration: FrozenDict
    configuration_version: int
    resolved_inputs: FrozenDict = field(default_factory=FrozenDict)
    observed_facts: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _required_text(self.node_instance_id, "node_instance_id")
        _positive_int(self.configuration_version, "configuration_version")
        for name in ("configuration", "resolved_inputs", "observed_facts"):
            object.__setattr__(self, name, FrozenDict(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class ProcessingValidationIssue:
    path: str
    code: str
    message: str

    def __post_init__(self) -> None:
        for name in ("path", "code", "message"):
            _required_text(getattr(self, name), name, maximum=2048)

    def to_document(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class ProcessingPlan:
    node_instance_id: str
    resource_requests: tuple[FrozenDict, ...] = ()
    driver_intent: FrozenDict = field(default_factory=FrozenDict)
    explanation: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _required_text(self.node_instance_id, "node_instance_id")
        object.__setattr__(
            self,
            "resource_requests",
            tuple(FrozenDict(item) for item in self.resource_requests),
        )
        object.__setattr__(self, "driver_intent", FrozenDict(self.driver_intent))
        object.__setattr__(self, "explanation", FrozenDict(self.explanation))

    def to_document(self) -> dict[str, object]:
        return {
            "nodeInstanceId": self.node_instance_id,
            "resourceRequests": [item.to_dict() for item in self.resource_requests],
            "driverIntent": self.driver_intent.to_dict(),
            "explanation": self.explanation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProcessingDriverRequest:
    node_instance_id: str
    idempotency_key: str
    configuration: FrozenDict
    plan: FrozenDict

    def __post_init__(self) -> None:
        _required_text(self.node_instance_id, "node_instance_id")
        _required_text(self.idempotency_key, "idempotency_key")
        object.__setattr__(self, "configuration", FrozenDict(self.configuration))
        object.__setattr__(self, "plan", FrozenDict(self.plan))


@dataclass(frozen=True, slots=True)
class ProcessingDriverResult:
    status: str
    facts: FrozenDict = field(default_factory=FrozenDict)
    details: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _required_text(self.status, "status")
        object.__setattr__(self, "facts", FrozenDict(self.facts))
        object.__setattr__(self, "details", FrozenDict(self.details))


@runtime_checkable
class ProcessingDriver(Protocol):
    def prepare(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def observe(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def activate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def reconfigure(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def deactivate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def cleanup(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...


class ProcessingPlugin(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ProcessingPluginManifest:
        raise NotImplementedError

    @abstractmethod
    def node_types(self) -> Sequence[ProcessingNodeTypeManifest]:
        raise NotImplementedError

    def validate(self, context: ProcessingHookContext) -> Sequence[ProcessingValidationIssue]:
        return ()

    @abstractmethod
    def plan(self, context: ProcessingHookContext) -> ProcessingPlan:
        raise NotImplementedError

    @abstractmethod
    def driver(self) -> ProcessingDriver:
        raise NotImplementedError
