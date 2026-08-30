from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from wyreplumber.runtime import FrozenDict, freeze_json, thaw_json

from core.orchestration.node_catalogue import NodePortDefinition, NodeTypeDefinition

PLUGIN_CONTEXT_MAX_BYTES = 64 * 1024


def _required_text(value: object, field_name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be a non-empty string of at most {maximum} characters")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _bounded_frozen_mapping(value: object, field_name: str) -> FrozenDict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    frozen = FrozenDict(value)
    try:
        size = len(
            json.dumps(
                thaw_json(frozen),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain JSON-compatible values") from error
    if size > PLUGIN_CONTEXT_MAX_BYTES:
        raise ValueError(f"{field_name} exceeds the {PLUGIN_CONTEXT_MAX_BYTES}-byte limit")
    return frozen


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
        object.__setattr__(self, "details", _bounded_frozen_mapping(self.details, "details"))

    def to_document(self) -> dict[str, object]:
        return {
            "pluginId": self.plugin_id,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "details": self.details.to_dict(),
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
            object.__setattr__(
                self,
                name,
                _bounded_frozen_mapping(getattr(self, name), name),
            )


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
        if len(self.resource_requests) > 128:
            raise ValueError("resource_requests cannot exceed 128 entries")
        object.__setattr__(
            self,
            "resource_requests",
            tuple(
                _bounded_frozen_mapping(item, "resource_request") for item in self.resource_requests
            ),
        )
        object.__setattr__(
            self,
            "driver_intent",
            _bounded_frozen_mapping(self.driver_intent, "driver_intent"),
        )
        object.__setattr__(
            self,
            "explanation",
            _bounded_frozen_mapping(self.explanation, "explanation"),
        )

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
        object.__setattr__(
            self,
            "configuration",
            _bounded_frozen_mapping(self.configuration, "configuration"),
        )
        object.__setattr__(self, "plan", _bounded_frozen_mapping(self.plan, "plan"))


@dataclass(frozen=True, slots=True)
class ProcessingDriverResult:
    status: str
    facts: FrozenDict = field(default_factory=FrozenDict)
    details: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _required_text(self.status, "status")
        object.__setattr__(self, "facts", _bounded_frozen_mapping(self.facts, "facts"))
        object.__setattr__(self, "details", _bounded_frozen_mapping(self.details, "details"))


@runtime_checkable
class ProcessingDriver(Protocol):
    def prepare(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def observe(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def activate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def reconfigure(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def deactivate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...

    def cleanup(self, request: ProcessingDriverRequest) -> ProcessingDriverResult: ...
