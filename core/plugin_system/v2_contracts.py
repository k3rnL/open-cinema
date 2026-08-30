from __future__ import annotations

import json
import platform
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from typing import ClassVar, Protocol, runtime_checkable
from urllib.parse import urlparse
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from wyreplumber.runtime import FrozenDict, freeze_json

from core.orchestration.node_catalogue import NodeTypeDefinition

PLUGIN_CONTRACT_VERSION_V2 = 2
PLUGIN_ENTRY_POINT = "open_cinema.plugins"
PLUGIN_MANIFEST_FILENAME = "open-cinema-plugin.toml"
PLUGIN_MANIFEST_MAX_BYTES = 256 * 1024
PLUGIN_DOCUMENT_MAX_BYTES = 64 * 1024


def _required_text(value: object, field_name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be a non-empty string of at most {maximum} characters")
    return value


def _positive_int(value: object, field_name: str, *, maximum: int = 65535) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer between 1 and {maximum}")
    return value


def _identifier(value: object, field_name: str) -> str:
    value = _required_text(value, field_name, maximum=128)
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in value):
        raise ValueError(f"{field_name} must use lowercase letters, digits, dots, and hyphens")
    if value[0] in ".-" or value[-1] in ".-" or ".." in value or "--" in value:
        raise ValueError(f"{field_name} has an invalid identifier boundary")
    return value


def _plugin_owned_identifier(plugin_id: str, value: str, field_name: str) -> str:
    value = _identifier(value, field_name)
    if not value.startswith(f"{plugin_id}."):
        raise ValueError(f"{field_name} must use the {plugin_id}. namespace")
    return value


def _relative_contract_path(value: str, field_name: str) -> str:
    value = _required_text(value, field_name, maximum=512)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.endswith("/"):
        raise ValueError(f"{field_name} must be a safe relative file path")
    return value


def _json_size(document: object) -> int:
    try:
        return len(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ValueError("document must contain JSON-compatible values") from error


def load_contract_schema(filename: str) -> dict[str, object]:
    _required_text(filename, "filename", maximum=128)
    schema_text = resources.files("contracts").joinpath(filename).read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_contract_document(
    document: Mapping[str, object],
    schema_filename: str,
    *,
    maximum_bytes: int = PLUGIN_DOCUMENT_MAX_BYTES,
) -> None:
    if not isinstance(document, Mapping):
        raise TypeError("contract document must be a mapping")
    size = _json_size(document)
    if size > maximum_bytes:
        raise ValueError(f"contract document exceeds the {maximum_bytes}-byte limit")
    schema = load_contract_schema(schema_filename)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        messages = []
        for error in errors[:16]:
            path = "/" + "/".join(str(part) for part in error.absolute_path)
            messages.append(f"{path or '/'}: {error.message}")
        if len(errors) > 16:
            messages.append(f"{len(errors) - 16} additional validation errors")
        raise ValueError("; ".join(messages))


class CapabilityKind(StrEnum):
    API = "api"
    AUTOMATION = "automation"
    PROCESSING = "processing"
    MANAGED_RESOURCE = "managed-resource"
    MANAGED_AUDIO_SOURCE = "managed-audio-source"
    ADMIN_UI = "admin-ui"


class LifecycleImpact(StrEnum):
    HOT = "hot"
    APPLICATION_RESTART = "application-restart"
    HOST_REBOOT = "host-reboot"

    @property
    def rank(self) -> int:
        return {
            LifecycleImpact.HOT: 0,
            LifecycleImpact.APPLICATION_RESTART: 1,
            LifecycleImpact.HOST_REBOOT: 2,
        }[self]

    @classmethod
    def maximum(cls, *values: LifecycleImpact | str) -> LifecycleImpact:
        if not values:
            return cls.HOT
        impacts = tuple(cls(value) for value in values)
        return max(impacts, key=lambda impact: impact.rank)


class LifecycleOperation(StrEnum):
    INSTALL = "install"
    ENABLE = "enable"
    DISABLE = "disable"
    UPDATE = "update"
    UNINSTALL = "uninstall"


class PluginDesiredState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class RuntimeStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ActionConfirmation(StrEnum):
    NONE = "none"
    CONFIRM = "confirm"
    DESTRUCTIVE = "destructive"
    DISCONNECTING = "disconnecting"


@dataclass(frozen=True, slots=True)
class IntegerCompatibilityRange:
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        _positive_int(self.minimum, "minimum")
        _positive_int(self.maximum, "maximum")
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")

    def supports(self, value: int) -> bool:
        return self.minimum <= value <= self.maximum

    def to_document(self) -> dict[str, int]:
        return {"minimum": self.minimum, "maximum": self.maximum}


@dataclass(frozen=True, slots=True)
class DistributionCompatibility:
    plugin_contract: IntegerCompatibilityRange
    open_cinema: str
    python: str
    operating_systems: tuple[str, ...]
    architectures: tuple[str, ...]
    capability_versions: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_contract, IntegerCompatibilityRange):
            raise TypeError("plugin_contract must be IntegerCompatibilityRange")
        for field_name in ("open_cinema", "python"):
            specifier = _required_text(getattr(self, field_name), field_name, maximum=120)
            try:
                SpecifierSet(specifier)
            except InvalidSpecifier as error:
                raise ValueError(f"{field_name} must be a valid version specifier") from error
        for field_name in ("operating_systems", "architectures"):
            values = tuple(getattr(self, field_name))
            if not values or len(values) > 16:
                raise ValueError(f"{field_name} must contain between 1 and 16 values")
            normalized = tuple(
                _required_text(value, field_name, maximum=64).lower() for value in values
            )
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, normalized)
        versions = FrozenDict(self.capability_versions)
        if len(versions) > 32:
            raise ValueError("capability_versions cannot contain more than 32 entries")
        for capability, value in versions.items():
            _identifier(capability, "capability_versions key")
            if not isinstance(value, FrozenDict):
                value = FrozenDict(value)
            IntegerCompatibilityRange(value["minimum"], value["maximum"])
        object.__setattr__(self, "capability_versions", versions)

    def to_document(self) -> dict[str, object]:
        return {
            "pluginContract": self.plugin_contract.to_document(),
            "openCinema": self.open_cinema,
            "python": self.python,
            "operatingSystems": list(self.operating_systems),
            "architectures": list(self.architectures),
            "capabilityVersions": self.capability_versions.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CompatibilityEvaluation:
    compatible: bool
    reasons: tuple[str, ...] = ()

    def to_document(self) -> dict[str, object]:
        return {"compatible": self.compatible, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class PluginCapabilityDeclaration:
    capability_id: str
    kind: CapabilityKind
    version: int
    required: bool = True
    schema_path: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability_id")
        object.__setattr__(self, "kind", CapabilityKind(self.kind))
        _positive_int(self.version, "version")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a boolean")
        if self.schema_path is not None:
            _relative_contract_path(self.schema_path, "schema_path")
        if self.digest is not None:
            digest = _required_text(self.digest, "digest", maximum=80)
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError("digest must be a sha256 digest")

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "kind": self.kind.value,
            "version": self.version,
            "required": self.required,
            "schema": self.schema_path,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class PluginPermission:
    permission_id: str
    reason: str
    required: bool = True

    def __post_init__(self) -> None:
        _identifier(self.permission_id, "permission_id")
        _required_text(self.reason, "reason", maximum=512)
        if not isinstance(self.required, bool):
            raise TypeError("required must be a boolean")

    def to_document(self) -> dict[str, object]:
        return {"id": self.permission_id, "reason": self.reason, "required": self.required}


@dataclass(frozen=True, slots=True)
class PluginDependency:
    dependency_id: str
    kind: str
    version: str
    required: bool = True

    def __post_init__(self) -> None:
        _identifier(self.dependency_id, "dependency_id")
        if self.kind not in {"python", "plugin", "asset", "host-installer"}:
            raise ValueError("unsupported dependency kind")
        _required_text(self.version, "version", maximum=120)
        if not isinstance(self.required, bool):
            raise TypeError("required must be a boolean")

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.dependency_id,
            "kind": self.kind,
            "version": self.version,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class ExternalRequirement:
    requirement_id: str
    description: str
    probe: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.requirement_id, "requirement_id")
        _required_text(self.description, "description", maximum=512)
        if self.probe is not None:
            _required_text(self.probe, "probe", maximum=128)

    def to_document(self) -> dict[str, object]:
        return {"id": self.requirement_id, "description": self.description, "probe": self.probe}


@dataclass(frozen=True, slots=True)
class PluginConfigurationDeclaration:
    version: int
    schema_path: str
    migrations: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        _positive_int(self.version, "configuration version")
        _relative_contract_path(self.schema_path, "schema_path")
        migrations = tuple(tuple(item) for item in self.migrations)
        if len(migrations) > 128:
            raise ValueError("configuration migrations cannot exceed 128 entries")
        sources = set()
        for source, target in migrations:
            _positive_int(source, "migration from")
            _positive_int(target, "migration to")
            if target != source + 1:
                raise ValueError("configuration migrations must advance exactly one version")
            if source in sources:
                raise ValueError("configuration migration sources must be unique")
            sources.add(source)
        object.__setattr__(self, "migrations", migrations)

    def to_document(self) -> dict[str, object]:
        return {
            "version": self.version,
            "schema": self.schema_path,
            "migrations": [{"from": source, "to": target} for source, target in self.migrations],
        }


@dataclass(frozen=True, slots=True)
class PluginLifecyclePolicy:
    install: LifecycleImpact
    enable: LifecycleImpact
    disable: LifecycleImpact
    update: LifecycleImpact
    uninstall: LifecycleImpact

    def __post_init__(self) -> None:
        for field_name in ("install", "enable", "disable", "update", "uninstall"):
            object.__setattr__(self, field_name, LifecycleImpact(getattr(self, field_name)))

    def impact_for(self, operation: LifecycleOperation | str) -> LifecycleImpact:
        return getattr(self, LifecycleOperation(operation).value.replace("-", "_"))

    def to_document(self) -> dict[str, str]:
        return {
            operation.value: self.impact_for(operation).value for operation in LifecycleOperation
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginDistributionManifest:
    plugin_id: str
    distribution_id: str
    display_name: str
    description: str
    vendor: str
    version: str
    license: str
    source_url: str
    documentation_url: str
    compatibility: DistributionCompatibility
    capabilities: tuple[PluginCapabilityDeclaration, ...]
    permissions: tuple[PluginPermission, ...]
    lifecycle: PluginLifecyclePolicy
    release_url: str | None = None
    dependencies: tuple[PluginDependency, ...] = ()
    external_requirements: tuple[ExternalRequirement, ...] = ()
    configuration: PluginConfigurationDeclaration | None = None
    contribution_digest: str | None = None
    schema_version: int = PLUGIN_CONTRACT_VERSION_V2

    def __post_init__(self) -> None:
        _identifier(self.plugin_id, "plugin_id")
        _identifier(self.distribution_id, "distribution_id")
        _required_text(self.display_name, "display_name", maximum=120)
        _required_text(self.description, "description", maximum=2048)
        _required_text(self.vendor, "vendor", maximum=120)
        _required_text(self.version, "version", maximum=64)
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise ValueError("version must be a valid package version") from error
        _required_text(self.license, "license", maximum=80)
        for field_name in ("source_url", "documentation_url", "release_url"):
            value = getattr(self, field_name)
            if value is None:
                continue
            _required_text(value, field_name, maximum=2048)
            if urlparse(value).scheme not in {"http", "https"}:
                raise ValueError(f"{field_name} must use HTTP or HTTPS")
        if self.schema_version != PLUGIN_CONTRACT_VERSION_V2:
            raise ValueError(f"schema_version must be {PLUGIN_CONTRACT_VERSION_V2}")
        if not isinstance(self.compatibility, DistributionCompatibility):
            raise TypeError("compatibility must be DistributionCompatibility")
        if not isinstance(self.lifecycle, PluginLifecyclePolicy):
            raise TypeError("lifecycle must be PluginLifecyclePolicy")
        for field_name, expected_type, maximum in (
            ("capabilities", PluginCapabilityDeclaration, 128),
            ("permissions", PluginPermission, 64),
            ("dependencies", PluginDependency, 128),
            ("external_requirements", ExternalRequirement, 64),
        ):
            values = tuple(getattr(self, field_name))
            if field_name == "capabilities" and not values:
                raise ValueError("capabilities must not be empty")
            if len(values) > maximum or any(not isinstance(item, expected_type) for item in values):
                raise ValueError(f"{field_name} contains invalid or excessive entries")
            object.__setattr__(self, field_name, values)
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability IDs must be unique within a plugin")
        for capability_id in capability_ids:
            _plugin_owned_identifier(self.plugin_id, capability_id, "capability_id")
        permission_ids = [item.permission_id for item in self.permissions]
        if len(permission_ids) != len(set(permission_ids)):
            raise ValueError("permission IDs must be unique within a plugin")
        if self.configuration is not None and not isinstance(
            self.configuration, PluginConfigurationDeclaration
        ):
            raise TypeError("configuration must be PluginConfigurationDeclaration")
        if self.contribution_digest is not None:
            if (
                not self.contribution_digest.startswith("sha256:")
                or len(self.contribution_digest) != 71
            ):
                raise ValueError("contribution_digest must be a sha256 digest")

    def evaluate_compatibility(
        self,
        *,
        open_cinema_version: str,
        python_version: str | None = None,
        operating_system: str | None = None,
        architecture: str | None = None,
        capability_versions: Mapping[str, int] | None = None,
    ) -> CompatibilityEvaluation:
        python_version = python_version or platform.python_version()
        operating_system = (operating_system or platform.system()).lower()
        architecture = (architecture or platform.machine()).lower()
        capability_versions = capability_versions or {
            capability.value: 1 for capability in CapabilityKind
        }
        reasons = []
        if not self.compatibility.plugin_contract.supports(PLUGIN_CONTRACT_VERSION_V2):
            reasons.append("plugin-contract-incompatible")
        try:
            if Version(open_cinema_version) not in SpecifierSet(self.compatibility.open_cinema):
                reasons.append("open-cinema-version-incompatible")
        except InvalidVersion:
            reasons.append("open-cinema-runtime-version-invalid")
        if Version(python_version) not in SpecifierSet(self.compatibility.python):
            reasons.append("python-version-incompatible")
        if operating_system not in self.compatibility.operating_systems:
            reasons.append("operating-system-incompatible")
        if architecture not in self.compatibility.architectures:
            reasons.append("architecture-incompatible")
        declared_versions = self.compatibility.capability_versions
        for declaration in self.capabilities:
            supported = capability_versions.get(declaration.kind.value)
            required_range = declared_versions.get(declaration.kind.value)
            if supported is None:
                reasons.append(f"capability-unsupported:{declaration.kind.value}")
            elif required_range is not None and not IntegerCompatibilityRange(
                required_range["minimum"], required_range["maximum"]
            ).supports(supported):
                reasons.append(f"capability-version-incompatible:{declaration.kind.value}")
        return CompatibilityEvaluation(not reasons, tuple(reasons))

    def to_document(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "id": self.plugin_id,
            "distribution": self.distribution_id,
            "displayName": self.display_name,
            "description": self.description,
            "vendor": self.vendor,
            "version": self.version,
            "license": self.license,
            "sourceUrl": self.source_url,
            "documentationUrl": self.documentation_url,
            "releaseUrl": self.release_url,
            "compatibility": self.compatibility.to_document(),
            "capabilities": [item.to_document() for item in self.capabilities],
            "permissions": [item.to_document() for item in self.permissions],
            "dependencies": [item.to_document() for item in self.dependencies],
            "externalRequirements": [item.to_document() for item in self.external_requirements],
            "configuration": self.configuration.to_document() if self.configuration else None,
            "lifecycle": self.lifecycle.to_document(),
            "contributionDigest": self.contribution_digest,
        }


@dataclass(frozen=True, slots=True)
class RuntimePluginIdentity:
    plugin_id: str
    distribution_id: str
    version: str

    def __post_init__(self) -> None:
        _identifier(self.plugin_id, "plugin_id")
        _identifier(self.distribution_id, "distribution_id")
        _required_text(self.version, "version", maximum=64)


@dataclass(frozen=True, slots=True)
class PluginRuntimeResult:
    status: RuntimeStatus
    facts: FrozenDict = field(default_factory=FrozenDict)
    details: FrozenDict = field(default_factory=FrozenDict)
    retry_after_ms: int | None = None
    concurrency_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RuntimeStatus(self.status))
        object.__setattr__(self, "facts", FrozenDict(self.facts))
        object.__setattr__(self, "details", FrozenDict(self.details))
        if self.retry_after_ms is not None and (
            isinstance(self.retry_after_ms, bool)
            or not isinstance(self.retry_after_ms, int)
            or not 0 <= self.retry_after_ms <= 3_600_000
        ):
            raise ValueError("retry_after_ms must be between 0 and 3600000")
        if self.concurrency_token is not None:
            _required_text(self.concurrency_token, "concurrency_token", maximum=256)
        validate_contract_document(self.to_document(), "plugin-runtime-result-v1.schema.json")

    def to_document(self) -> dict[str, object]:
        document = {
            "schemaVersion": 1,
            "status": self.status.value,
            "facts": self.facts.to_dict(),
            "details": self.details.to_dict(),
        }
        if self.retry_after_ms is not None:
            document["retryAfterMs"] = self.retry_after_ms
        if self.concurrency_token is not None:
            document["concurrencyToken"] = self.concurrency_token
        return document


@dataclass(frozen=True, slots=True)
class PluginActionDescriptor:
    action_id: str
    label: str
    available: bool
    lifecycle_impact: LifecycleImpact = LifecycleImpact.HOT
    confirmation: ActionConfirmation = ActionConfirmation.NONE
    reason: str | None = None
    concurrency_token: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.action_id, "action_id")
        _required_text(self.label, "label", maximum=80)
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")
        object.__setattr__(self, "lifecycle_impact", LifecycleImpact(self.lifecycle_impact))
        object.__setattr__(self, "confirmation", ActionConfirmation(self.confirmation))
        if self.reason is not None:
            _required_text(self.reason, "reason", maximum=512)
        if self.concurrency_token is not None:
            _required_text(self.concurrency_token, "concurrency_token", maximum=256)
        if not self.available and self.reason is None:
            raise ValueError("unavailable actions must explain why they are unavailable")

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.action_id,
            "label": self.label,
            "available": self.available,
            "reason": self.reason,
            "lifecycleImpact": self.lifecycle_impact.value,
            "confirmation": self.confirmation.value,
            "concurrencyToken": self.concurrency_token,
        }


@runtime_checkable
class PluginHostServices(Protocol):
    """Bounded host facilities available to an external managed provider."""

    def private_directory(self, purpose: str) -> str: ...

    def secret_presence(self, secret_id: str) -> bool: ...

    def resolve_secret(self, secret_id: str) -> bytes: ...

    def invoke_automation(self, automation_id: str, payload: Mapping[str, object]) -> object: ...

    def logical_endpoint_references(
        self, logical_endpoint_id: str
    ) -> tuple[Mapping[str, object], ...]: ...


@dataclass(frozen=True, slots=True)
class ManagedResourceContext:
    plugin_id: str
    capability_id: str
    instance_id: str
    configuration: FrozenDict
    configuration_version: int
    concurrency_token: str | None = None
    deadline_ms: int = 5000
    host_services: PluginHostServices | None = None

    def __post_init__(self) -> None:
        _identifier(self.plugin_id, "plugin_id")
        _plugin_owned_identifier(self.plugin_id, self.capability_id, "capability_id")
        _identifier(self.instance_id, "instance_id")
        _positive_int(self.configuration_version, "configuration_version")
        configuration = FrozenDict(self.configuration)
        if _json_size(configuration.to_dict()) > PLUGIN_DOCUMENT_MAX_BYTES:
            raise ValueError("configuration exceeds the document size limit")
        object.__setattr__(self, "configuration", configuration)
        if self.concurrency_token is not None:
            _required_text(self.concurrency_token, "concurrency_token", maximum=256)
        if (
            isinstance(self.deadline_ms, bool)
            or not isinstance(self.deadline_ms, int)
            or not 100 <= self.deadline_ms <= 60_000
        ):
            raise ValueError("deadline_ms must be between 100 and 60000")
        if self.host_services is not None and not isinstance(
            self.host_services, PluginHostServices
        ):
            raise TypeError("host_services must implement PluginHostServices")


@dataclass(frozen=True, slots=True)
class ManagedResourceObservation:
    result: PluginRuntimeResult
    observed_at: str
    fresh_for_ms: int
    actions: tuple[PluginActionDescriptor, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.result, PluginRuntimeResult):
            raise TypeError("result must be PluginRuntimeResult")
        _required_text(self.observed_at, "observed_at", maximum=64)
        if (
            isinstance(self.fresh_for_ms, bool)
            or not isinstance(self.fresh_for_ms, int)
            or not 0 <= self.fresh_for_ms <= 3_600_000
        ):
            raise ValueError("fresh_for_ms must be between 0 and 3600000")
        actions = tuple(self.actions)
        if len(actions) > 32 or any(
            not isinstance(item, PluginActionDescriptor) for item in actions
        ):
            raise ValueError("actions must contain at most 32 PluginActionDescriptor values")
        if len({item.action_id for item in actions}) != len(actions):
            raise ValueError("action IDs must be unique")
        object.__setattr__(self, "actions", actions)

    def to_document(self) -> dict[str, object]:
        return {
            "result": self.result.to_document(),
            "observedAt": self.observed_at,
            "freshForMs": self.fresh_for_ms,
            "actions": [item.to_document() for item in self.actions],
        }


@dataclass(frozen=True, slots=True)
class PluginCapability(ABC):
    capability_id: str
    version: int = 1

    KIND: ClassVar[CapabilityKind]

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability_id")
        _positive_int(self.version, "version")

    @property
    def kind(self) -> CapabilityKind:
        return self.KIND

    def schema_metadata(self) -> Mapping[str, object]:
        return {}

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "kind": self.kind.value,
            "version": self.version,
            "schemaMetadata": dict(self.schema_metadata()),
        }


@dataclass(frozen=True, slots=True)
class ApiCapability(PluginCapability):
    routes: Callable[[], Sequence[object]] = field(default=lambda: ())
    KIND: ClassVar[CapabilityKind] = CapabilityKind.API

    def __post_init__(self) -> None:
        super(ApiCapability, self).__post_init__()
        if not callable(self.routes):
            raise TypeError("routes must be callable")


@dataclass(frozen=True, slots=True)
class AutomationCapability(PluginCapability):
    hooks: Mapping[str, Callable[..., object]] = field(default_factory=dict)
    KIND: ClassVar[CapabilityKind] = CapabilityKind.AUTOMATION

    def __post_init__(self) -> None:
        super(AutomationCapability, self).__post_init__()
        hooks = dict(self.hooks)
        if len(hooks) > 128:
            raise ValueError("automation hooks cannot exceed 128 entries")
        if any(not callable(value) for value in hooks.values()):
            raise TypeError("automation hooks must be callable")
        object.__setattr__(self, "hooks", hooks)


@dataclass(frozen=True, slots=True)
class ProcessingCapability(PluginCapability):
    node_types: tuple[object, ...] = ()
    validate_hook: Callable[[object], Sequence[object]] | None = None
    plan_hook: Callable[[object], object] | None = None
    driver_factory: Callable[[], object] | None = None
    KIND: ClassVar[CapabilityKind] = CapabilityKind.PROCESSING

    def __post_init__(self) -> None:
        super(ProcessingCapability, self).__post_init__()
        node_types = tuple(self.node_types)
        if not node_types or len(node_types) > 128:
            raise ValueError("processing capability must declare between 1 and 128 node types")
        if any(not hasattr(item, "to_node_type_definition") for item in node_types):
            raise TypeError("processing node types must expose to_node_type_definition")
        for callback in (self.validate_hook, self.plan_hook, self.driver_factory):
            if callback is not None and not callable(callback):
                raise TypeError("processing hooks must be callable")
        object.__setattr__(self, "node_types", node_types)

    def schema_metadata(self) -> Mapping[str, object]:
        return {"nodeTypes": [item.to_document() for item in self.node_types]}


@runtime_checkable
class ManagedResourceProvider(Protocol):
    def observe(self, context: ManagedResourceContext) -> ManagedResourceObservation: ...

    def actions(self, context: ManagedResourceContext) -> Sequence[PluginActionDescriptor]: ...

    def execute(self, action_id: str, context: ManagedResourceContext) -> PluginRuntimeResult: ...


@dataclass(frozen=True, slots=True)
class ManagedResourceCapability(PluginCapability):
    resource_type: str = ""
    provider: ManagedResourceProvider | None = None
    instance_schema: Mapping[str, object] = field(default_factory=dict)
    KIND: ClassVar[CapabilityKind] = CapabilityKind.MANAGED_RESOURCE

    def __post_init__(self) -> None:
        super(ManagedResourceCapability, self).__post_init__()
        _identifier(self.resource_type, "resource_type")
        if self.provider is None or not isinstance(self.provider, ManagedResourceProvider):
            raise TypeError("provider must implement ManagedResourceProvider")
        schema = freeze_json(self.instance_schema)
        if not isinstance(schema, FrozenDict):
            raise TypeError("instance_schema must be an object")
        Draft202012Validator.check_schema(schema.to_dict())
        object.__setattr__(self, "instance_schema", schema)

    def schema_metadata(self) -> Mapping[str, object]:
        return {
            "resourceType": self.resource_type,
            "instanceSchema": self.instance_schema.to_dict(),
        }


@runtime_checkable
class ManagedAudioSourceProvider(Protocol):
    def prepare(self, context: ManagedResourceContext) -> PluginRuntimeResult: ...

    def observe(self, context: ManagedResourceContext) -> ManagedResourceObservation: ...

    def activate(self, context: ManagedResourceContext) -> PluginRuntimeResult: ...

    def reconfigure(self, context: ManagedResourceContext) -> PluginRuntimeResult: ...

    def deactivate(self, context: ManagedResourceContext) -> PluginRuntimeResult: ...

    def cleanup(self, context: ManagedResourceContext) -> PluginRuntimeResult: ...


@dataclass(frozen=True, slots=True)
class ManagedAudioSourceCapability(PluginCapability):
    source_type: str = ""
    provider: ManagedAudioSourceProvider | None = None
    instance_schema: Mapping[str, object] = field(default_factory=dict)
    signal_contract: Mapping[str, object] = field(default_factory=dict)
    correlation_keys: tuple[str, ...] = ()
    KIND: ClassVar[CapabilityKind] = CapabilityKind.MANAGED_AUDIO_SOURCE

    def __post_init__(self) -> None:
        super(ManagedAudioSourceCapability, self).__post_init__()
        _identifier(self.source_type, "source_type")
        if self.provider is None or not isinstance(self.provider, ManagedAudioSourceProvider):
            raise TypeError("provider must implement ManagedAudioSourceProvider")
        schema = freeze_json(self.instance_schema)
        signal = freeze_json(self.signal_contract)
        if not isinstance(schema, FrozenDict) or not isinstance(signal, FrozenDict):
            raise TypeError("source schemas must be objects")
        Draft202012Validator.check_schema(schema.to_dict())
        keys = tuple(
            _required_text(item, "correlation key", maximum=128) for item in self.correlation_keys
        )
        if not keys or len(keys) > 32 or len(keys) != len(set(keys)):
            raise ValueError("correlation_keys must contain between 1 and 32 unique values")
        object.__setattr__(self, "instance_schema", schema)
        object.__setattr__(self, "signal_contract", signal)
        object.__setattr__(self, "correlation_keys", keys)

    def schema_metadata(self) -> Mapping[str, object]:
        return {
            "sourceType": self.source_type,
            "instanceSchema": self.instance_schema.to_dict(),
            "signalContract": self.signal_contract.to_dict(),
            "correlationKeys": list(self.correlation_keys),
        }


@dataclass(frozen=True, slots=True)
class AdminUICapability(PluginCapability):
    descriptor: Mapping[str, object] = field(default_factory=dict)
    KIND: ClassVar[CapabilityKind] = CapabilityKind.ADMIN_UI

    def __post_init__(self) -> None:
        super(AdminUICapability, self).__post_init__()
        validate_contract_document(self.descriptor, "plugin-admin-ui-v1.schema.json")
        object.__setattr__(self, "descriptor", FrozenDict(self.descriptor))

    def schema_metadata(self) -> Mapping[str, object]:
        return {"descriptor": self.descriptor.to_dict()}


PluginCapabilityContribution = (
    ApiCapability
    | AutomationCapability
    | ProcessingCapability
    | ManagedResourceCapability
    | ManagedAudioSourceCapability
    | AdminUICapability
)


@dataclass(frozen=True, slots=True)
class DistributionLifecycleContext:
    plugin_id: str
    settings: FrozenDict = field(default_factory=FrozenDict)
    deadline_ms: int = 5000

    def __post_init__(self) -> None:
        _identifier(self.plugin_id, "plugin_id")
        object.__setattr__(self, "settings", FrozenDict(self.settings))
        if (
            isinstance(self.deadline_ms, bool)
            or not isinstance(self.deadline_ms, int)
            or not 100 <= self.deadline_ms <= 60_000
        ):
            raise ValueError("deadline_ms must be between 100 and 60000")
        if _json_size(self.settings.to_dict()) > PLUGIN_DOCUMENT_MAX_BYTES:
            raise ValueError("lifecycle settings exceed the document size limit")


class OpenCinemaPlugin(ABC):
    @property
    @abstractmethod
    def identity(self) -> RuntimePluginIdentity:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> Sequence[PluginCapabilityContribution]:
        raise NotImplementedError

    def start(self, context: DistributionLifecycleContext) -> PluginRuntimeResult:
        return PluginRuntimeResult(RuntimeStatus.READY)

    def stop(self, context: DistributionLifecycleContext) -> PluginRuntimeResult:
        return PluginRuntimeResult(RuntimeStatus.READY)


def validate_runtime_capability_namespace(
    plugin_id: str, capability: PluginCapabilityContribution
) -> None:
    _plugin_owned_identifier(plugin_id, capability.capability_id, "capability_id")
    if isinstance(capability, AutomationCapability):
        for automation_id in capability.hooks:
            _plugin_owned_identifier(plugin_id, automation_id, "automation_id")
    if isinstance(capability, ProcessingCapability):
        for node_type in capability.node_types:
            definition: NodeTypeDefinition = node_type.to_node_type_definition()
            type_id = _identifier(definition.type_id, "processing type_id")
            if not type_id.startswith((f"{plugin_id}.", f"plugin.{plugin_id}.")):
                raise ValueError(
                    "processing type_id must use the "
                    f"{plugin_id}. or plugin.{plugin_id}. namespace"
                )
    if isinstance(capability, ManagedResourceCapability):
        _plugin_owned_identifier(plugin_id, capability.resource_type, "resource_type")
    if isinstance(capability, ManagedAudioSourceCapability):
        _plugin_owned_identifier(plugin_id, capability.source_type, "source_type")
    if isinstance(capability, AdminUICapability):
        api_prefix = f"/api/plugins/{plugin_id}/"
        descriptor = capability.descriptor
        for navigation in descriptor["navigation"]:
            _plugin_owned_identifier(plugin_id, navigation["id"], "navigation id")
            _plugin_owned_identifier(plugin_id, navigation["pageId"], "navigation pageId")
        for page in descriptor["pages"]:
            _plugin_owned_identifier(plugin_id, page["id"], "page id")
            binding = page["binding"]
            for key in ("read", "write", "operationStatus"):
                endpoint = binding.get(key)
                if endpoint is not None and not endpoint.startswith(api_prefix):
                    raise ValueError(f"UI binding {key} must use the {api_prefix} namespace")
            for section in page["sections"]:
                _plugin_owned_identifier(plugin_id, section["id"], "section id")
                for field_descriptor in section["fields"]:
                    _plugin_owned_identifier(plugin_id, field_descriptor["id"], "field id")
            for action in page.get("actions", ()):
                _plugin_owned_identifier(plugin_id, action["id"], "action id")
                if not action["endpoint"].startswith(api_prefix):
                    raise ValueError(f"UI action endpoint must use the {api_prefix} namespace")


def runtime_environment_document() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "operatingSystem": platform.system().lower(),
        "architecture": platform.machine().lower(),
        "implementation": sys.implementation.name,
    }
