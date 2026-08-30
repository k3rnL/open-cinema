from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from jsonschema import Draft202012Validator
from wyreplumber.runtime import FrozenDict

from api.models import (
    GraphRevision,
    PluginAggregateHealth,
    PluginCapabilityState,
    PluginDesiredState,
    PluginDiagnosticRecord,
    PluginDocument,
    PluginInstallation,
    PluginInstance,
    PluginObservedState,
    PluginOperation,
    PluginOperationKind,
    PluginSecretReference,
)

PLUGIN_STORAGE_DOCUMENT_MAX_BYTES = 256 * 1024
PLUGIN_STORAGE_QUERY_LIMIT = 100
PLUGIN_STORAGE_QUERY_MAX_OFFSET = 10_000
PLUGIN_SECRET_MAX_BYTES = 64 * 1024
_REDACTED = "[redacted]"
_SENSITIVE_KEYS = ("secret", "password", "token", "credential", "authorization")


class PluginStorageError(ValueError):
    pass


class PluginStorageNotFoundError(PluginStorageError):
    pass


class StalePluginStateError(PluginStorageError):
    pass


class PluginStorageOwnershipError(PermissionError):
    pass


class PluginConfigurationMigrationError(PluginStorageError):
    pass


class PluginStorageSchemaRegistry:
    """Process-local validated schema catalogue populated by enabled plugin contracts."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str, int], dict[str, object]] = {}

    def register(
        self,
        *,
        plugin_id: str,
        schema_id: str,
        schema_version: int,
        schema: Mapping[str, object],
    ) -> None:
        plugin_id = _identifier(plugin_id, "plugin_id")
        schema_id = _owned_identifier(plugin_id, schema_id, "schema_id")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < 1
        ):
            raise PluginStorageError("schema_version must be a positive integer")
        normalized = _json_document(schema, "schema")
        Draft202012Validator.check_schema(normalized)
        key = (plugin_id, schema_id, schema_version)
        existing = self._schemas.get(key)
        if existing is not None and existing != normalized:
            raise PluginStorageError("schema identity is already registered with other content")
        self._schemas[key] = normalized

    def require(self, plugin_id: str, schema_id: str, schema_version: int) -> dict[str, object]:
        plugin_id = _identifier(plugin_id, "plugin_id")
        schema_id = _owned_identifier(plugin_id, schema_id, "schema_id")
        try:
            return self._schemas[(plugin_id, schema_id, schema_version)]
        except KeyError as error:
            raise PluginStorageNotFoundError("plugin storage schema is unavailable") from error

    def clear(self) -> None:
        self._schemas.clear()


PLUGIN_STORAGE_SCHEMAS = PluginStorageSchemaRegistry()


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PluginStorageError(f"{field_name} must be a non-empty identifier")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-." for character in value):
        raise PluginStorageError(
            f"{field_name} must use lowercase letters, digits, dots, and hyphens"
        )
    if value[0] in ".-" or value[-1] in ".-" or ".." in value or "--" in value:
        raise PluginStorageError(f"{field_name} has an invalid identifier boundary")
    return value


def _owned_identifier(plugin_id: str, value: object, field_name: str) -> str:
    value = _identifier(value, field_name)
    if not value.startswith(f"{plugin_id}."):
        raise PluginStorageOwnershipError(f"{field_name} must belong to the {plugin_id}. namespace")
    return value


def _json_document(
    value: object,
    field_name: str,
    *,
    expect: type = dict,
    maximum_bytes: int = PLUGIN_STORAGE_DOCUMENT_MAX_BYTES,
) -> object:
    if not isinstance(value, expect):
        raise PluginStorageError(f"{field_name} must be a {expect.__name__}")
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False))
        size = len(
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError) as error:
        raise PluginStorageError(f"{field_name} must contain JSON-compatible values") from error
    if size > maximum_bytes:
        raise PluginStorageError(f"{field_name} exceeds the {maximum_bytes}-byte limit")
    return normalized


def _validate_schema(
    document: Mapping[str, object], schema: Mapping[str, object]
) -> dict[str, object]:
    normalized_schema = _json_document(schema, "schema")
    Draft202012Validator.check_schema(normalized_schema)
    normalized = _json_document(document, "document")
    errors = sorted(
        Draft202012Validator(normalized_schema).iter_errors(normalized),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        messages = []
        for error in errors[:16]:
            path = "/" + "/".join(str(item) for item in error.absolute_path)
            messages.append(f"{path or '/'}: {error.message}")
        raise PluginStorageError("; ".join(messages))
    return normalized


def redact_plugin_data(value: object) -> object:
    """Return JSON-safe diagnostics with conventionally sensitive values removed."""

    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in _SENSITIVE_KEYS):
                redacted[key_text] = _REDACTED
            else:
                redacted[key_text] = redact_plugin_data(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_plugin_data(item) for item in value]
    if isinstance(value, bytes):
        return _REDACTED
    return value


class PluginInstallationRepository:
    @staticmethod
    def save_snapshot(
        *,
        plugin_id: str,
        distribution_id: str,
        installed_version: str,
        manifest: Mapping[str, object],
        provenance: Mapping[str, object],
        lifecycle_impact: Mapping[str, object],
        desired_state: str = PluginDesiredState.DISABLED,
    ) -> PluginInstallation:
        plugin_id = _identifier(plugin_id, "plugin_id")
        distribution_id = _identifier(distribution_id, "distribution_id")
        manifest_document = _json_document(manifest, "manifest")
        provenance_document = _json_document(provenance, "provenance")
        lifecycle_document = _json_document(lifecycle_impact, "lifecycle_impact")
        with transaction.atomic():
            installation, created = PluginInstallation.objects.select_for_update().get_or_create(
                plugin_id=plugin_id,
                defaults={
                    "distribution_id": distribution_id,
                    "installed_version": installed_version,
                    "manifest_snapshot": manifest_document,
                    "provenance_snapshot": provenance_document,
                    "lifecycle_impact": lifecycle_document,
                    "desired_state": desired_state,
                },
            )
            if not created:
                installation.distribution_id = distribution_id
                installation.installed_version = installed_version
                installation.manifest_snapshot = manifest_document
                installation.provenance_snapshot = provenance_document
                installation.lifecycle_impact = lifecycle_document
                installation.update_version = F("update_version") + 1
                installation.save(
                    update_fields=(
                        "distribution_id",
                        "installed_version",
                        "manifest_snapshot",
                        "provenance_snapshot",
                        "lifecycle_impact",
                        "update_version",
                        "updated_at",
                    )
                )
                installation.refresh_from_db()
            return installation

    @staticmethod
    def set_desired_state(
        plugin_id: str,
        desired_state: str,
        *,
        expected_version: int,
    ) -> PluginInstallation:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if desired_state not in PluginDesiredState.values:
            raise PluginStorageError("invalid plugin desired state")
        updated = PluginInstallation.objects.filter(
            plugin_id=plugin_id,
            update_version=expected_version,
        ).update(
            desired_state=desired_state,
            update_version=F("update_version") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            if not PluginInstallation.objects.filter(plugin_id=plugin_id).exists():
                raise PluginStorageNotFoundError(f"plugin {plugin_id!r} is not installed")
            raise StalePluginStateError("plugin installation changed; refresh and retry")
        return PluginInstallation.objects.get(plugin_id=plugin_id)

    @staticmethod
    def set_observed_state(
        plugin_id: str,
        observed_state: str,
        aggregate_health: str,
    ) -> PluginInstallation:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if observed_state not in PluginObservedState.values:
            raise PluginStorageError("invalid plugin observed state")
        if aggregate_health not in PluginAggregateHealth.values:
            raise PluginStorageError("invalid plugin aggregate health")
        updated = PluginInstallation.objects.filter(plugin_id=plugin_id).update(
            observed_state=observed_state,
            aggregate_health=aggregate_health,
            update_version=F("update_version") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise PluginStorageNotFoundError(f"plugin {plugin_id!r} is not installed")
        return PluginInstallation.objects.get(plugin_id=plugin_id)

    @staticmethod
    def synchronize_capabilities(plugin_id: str, capabilities: list[Mapping[str, object]]) -> None:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if len(capabilities) > 128:
            raise PluginStorageError("capabilities cannot exceed 128 entries")
        seen = set()
        with transaction.atomic():
            for item in capabilities:
                capability_id = _owned_identifier(plugin_id, item["id"], "capability_id")
                if capability_id in seen:
                    raise PluginStorageError("capability IDs must be unique")
                seen.add(capability_id)
                PluginCapabilityState.objects.update_or_create(
                    plugin_id=plugin_id,
                    capability_id=capability_id,
                    defaults={
                        "kind": item["kind"],
                        "contract_version": item["version"],
                        "declaration_snapshot": _json_document(item, "capability"),
                        "schema_metadata": _json_document(
                            item.get("schemaMetadata", {}), "schema_metadata"
                        ),
                        "observed_state": item.get("state", PluginObservedState.DISCOVERED),
                        "health": item.get("health", PluginAggregateHealth.UNKNOWN),
                        "diagnostics": _json_document(
                            redact_plugin_data(item.get("diagnostics", [])),
                            "diagnostics",
                            expect=list,
                        ),
                    },
                )
            PluginCapabilityState.objects.filter(plugin_id=plugin_id).exclude(
                capability_id__in=seen
            ).delete()


class PluginDocumentRepository:
    @staticmethod
    def get(plugin_id: str, collection: str, document_id: str) -> PluginDocument:
        plugin_id = _identifier(plugin_id, "plugin_id")
        collection = _owned_identifier(plugin_id, collection, "collection")
        document_id = _identifier(document_id, "document_id")
        try:
            return PluginDocument.objects.get(
                plugin_id=plugin_id,
                collection=collection,
                document_id=document_id,
            )
        except PluginDocument.DoesNotExist as error:
            raise PluginStorageNotFoundError("plugin document does not exist") from error

    @staticmethod
    def list(
        plugin_id: str,
        collection: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PluginDocument, ...]:
        plugin_id = _identifier(plugin_id, "plugin_id")
        collection = _owned_identifier(plugin_id, collection, "collection")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise PluginStorageError("limit must be between 1 and 100")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset <= PLUGIN_STORAGE_QUERY_MAX_OFFSET
        ):
            raise PluginStorageError("offset must be between 0 and 10000")
        return tuple(
            PluginDocument.objects.filter(plugin_id=plugin_id, collection=collection)[
                offset : offset + limit
            ]
        )

    @staticmethod
    def put(
        *,
        plugin_id: str,
        collection: str,
        document_id: str,
        schema_id: str,
        schema_version: int,
        document: Mapping[str, object],
        schema: Mapping[str, object],
        expected_version: int | None = None,
    ) -> PluginDocument:
        plugin_id = _identifier(plugin_id, "plugin_id")
        collection = _owned_identifier(plugin_id, collection, "collection")
        document_id = _identifier(document_id, "document_id")
        schema_id = _owned_identifier(plugin_id, schema_id, "schema_id")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < 1
        ):
            raise PluginStorageError("schema_version must be a positive integer")
        normalized = _validate_schema(document, schema)
        with transaction.atomic():
            current = (
                PluginDocument.objects.select_for_update()
                .filter(
                    plugin_id=plugin_id,
                    collection=collection,
                    document_id=document_id,
                )
                .first()
            )
            if current is None:
                if expected_version not in (None, 0):
                    raise StalePluginStateError("plugin document does not exist at that version")
                try:
                    return PluginDocument.objects.create(
                        plugin_id=plugin_id,
                        collection=collection,
                        document_id=document_id,
                        schema_id=schema_id,
                        schema_version=schema_version,
                        document=normalized,
                    )
                except IntegrityError as error:
                    raise StalePluginStateError(
                        "plugin document was created concurrently"
                    ) from error
            if expected_version is None or current.update_version != expected_version:
                raise StalePluginStateError("plugin document changed; refresh and retry")
            current.schema_id = schema_id
            current.schema_version = schema_version
            current.document = normalized
            current.update_version += 1
            current.save(
                update_fields=(
                    "schema_id",
                    "schema_version",
                    "document",
                    "update_version",
                    "updated_at",
                )
            )
            return current

    @staticmethod
    def delete(
        plugin_id: str,
        collection: str,
        document_id: str,
        *,
        expected_version: int,
    ) -> None:
        document = PluginDocumentRepository.get(plugin_id, collection, document_id)
        deleted, _ = PluginDocument.objects.filter(
            pk=document.pk, update_version=expected_version
        ).delete()
        if deleted != 1:
            raise StalePluginStateError("plugin document changed; refresh and retry")


class PluginConfigurationRepository:
    COLLECTION_SUFFIX = "configuration"
    DOCUMENT_ID = "active"
    SCHEMA_SUFFIX = "configuration"

    @classmethod
    def _names(cls, plugin_id: str) -> tuple[str, str]:
        return f"{plugin_id}.{cls.COLLECTION_SUFFIX}", f"{plugin_id}.{cls.SCHEMA_SUFFIX}"

    @classmethod
    def get(cls, plugin_id: str) -> PluginDocument:
        collection, _ = cls._names(_identifier(plugin_id, "plugin_id"))
        return PluginDocumentRepository.get(plugin_id, collection, cls.DOCUMENT_ID)

    @classmethod
    def put(
        cls,
        *,
        plugin_id: str,
        schema_version: int,
        document: Mapping[str, object],
        schema: Mapping[str, object],
        expected_version: int | None = None,
    ) -> PluginDocument:
        plugin_id = _identifier(plugin_id, "plugin_id")
        collection, schema_id = cls._names(plugin_id)
        return PluginDocumentRepository.put(
            plugin_id=plugin_id,
            collection=collection,
            document_id=cls.DOCUMENT_ID,
            schema_id=schema_id,
            schema_version=schema_version,
            document=document,
            schema=schema,
            expected_version=expected_version,
        )

    @classmethod
    def migrate(
        cls,
        *,
        plugin_id: str,
        target_version: int,
        schemas: Mapping[int, Mapping[str, object]],
        migrations: Mapping[int, Callable[[Mapping[str, object]], Mapping[str, object]]],
    ) -> PluginDocument:
        plugin_id = _identifier(plugin_id, "plugin_id")
        collection, schema_id = cls._names(plugin_id)
        with transaction.atomic():
            try:
                current = PluginDocument.objects.select_for_update().get(
                    plugin_id=plugin_id,
                    collection=collection,
                    document_id=cls.DOCUMENT_ID,
                )
            except PluginDocument.DoesNotExist as error:
                raise PluginStorageNotFoundError("plugin configuration does not exist") from error
            if target_version < current.schema_version:
                raise PluginConfigurationMigrationError("configuration cannot migrate backwards")
            version = current.schema_version
            migrated = _json_document(current.document, "configuration")
            original = _json_document(current.document, "configuration")
            try:
                while version < target_version:
                    migration = migrations.get(version)
                    schema = schemas.get(version + 1)
                    if migration is None or schema is None:
                        raise PluginConfigurationMigrationError(
                            f"missing configuration migration or schema from version {version}"
                        )
                    candidate = migration(FrozenDict(migrated))
                    if not isinstance(candidate, Mapping):
                        raise PluginConfigurationMigrationError(
                            "configuration migration must return a mapping"
                        )
                    migrated = _validate_schema(candidate, schema)
                    version += 1
            except Exception as error:
                if isinstance(error, PluginConfigurationMigrationError):
                    raise
                raise PluginConfigurationMigrationError(str(error)) from error
            if current.document != original:
                raise AssertionError("configuration migration mutated persisted input")
            current.schema_id = schema_id
            current.schema_version = target_version
            current.document = migrated
            current.update_version += 1
            current.save(
                update_fields=(
                    "schema_id",
                    "schema_version",
                    "document",
                    "update_version",
                    "updated_at",
                )
            )
            return current

    @classmethod
    def validate_retained(
        cls,
        plugin_id: str,
        schemas: Mapping[int, Mapping[str, object]],
    ) -> PluginDocument:
        current = cls.get(plugin_id)
        schema = schemas.get(current.schema_version)
        if schema is None:
            raise PluginConfigurationMigrationError(
                f"retained configuration version {current.schema_version} is unsupported"
            )
        _validate_schema(current.document, schema)
        return current


class PluginInstanceRepository:
    @staticmethod
    def get(plugin_id: str, capability_id: str, instance_id: str) -> PluginInstance:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        instance_id = _identifier(instance_id, "instance_id")
        try:
            return PluginInstance.objects.get(
                plugin_id=plugin_id,
                capability_id=capability_id,
                instance_id=instance_id,
            )
        except PluginInstance.DoesNotExist as error:
            raise PluginStorageNotFoundError("plugin instance does not exist") from error

    @staticmethod
    def create(
        *,
        plugin_id: str,
        capability_id: str,
        instance_id: str,
        display_name: str,
        configuration_version: int,
        configuration: Mapping[str, object],
        schema: Mapping[str, object],
        desired_state: str = "disabled",
        owner_id: object | None = None,
    ) -> PluginInstance:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        instance_id = _identifier(instance_id, "instance_id")
        if not isinstance(display_name, str) or not display_name or len(display_name) > 160:
            raise PluginStorageError("display_name must be between 1 and 160 characters")
        if (
            isinstance(configuration_version, bool)
            or not isinstance(configuration_version, int)
            or configuration_version < 1
        ):
            raise PluginStorageError("configuration_version must be a positive integer")
        normalized = _validate_schema(configuration, schema)
        if desired_state not in PluginDesiredState.values:
            raise PluginStorageError("invalid plugin instance desired state")
        try:
            return PluginInstance.objects.create(
                plugin_id=plugin_id,
                capability_id=capability_id,
                instance_id=instance_id,
                display_name=display_name,
                configuration_version=configuration_version,
                configuration=normalized,
                desired_state=desired_state,
                owner_id=owner_id,
            )
        except IntegrityError as error:
            raise PluginStorageError("plugin instance already exists") from error

    @staticmethod
    def list(
        plugin_id: str,
        capability_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PluginInstance, ...]:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= PLUGIN_STORAGE_QUERY_LIMIT
        ):
            raise PluginStorageError("limit must be between 1 and 100")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset <= PLUGIN_STORAGE_QUERY_MAX_OFFSET
        ):
            raise PluginStorageError("offset must be between 0 and 10000")
        return tuple(
            PluginInstance.objects.filter(plugin_id=plugin_id, capability_id=capability_id)[
                offset : offset + limit
            ]
        )

    @staticmethod
    def update_configuration(
        *,
        plugin_id: str,
        capability_id: str,
        instance_id: str,
        configuration_version: int,
        configuration: Mapping[str, object],
        schema: Mapping[str, object],
        expected_version: int,
    ) -> PluginInstance:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        instance_id = _identifier(instance_id, "instance_id")
        normalized = _validate_schema(configuration, schema)
        updated = PluginInstance.objects.filter(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=instance_id,
            update_version=expected_version,
        ).update(
            configuration_version=configuration_version,
            configuration=normalized,
            update_version=F("update_version") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            if not PluginInstance.objects.filter(
                plugin_id=plugin_id,
                capability_id=capability_id,
                instance_id=instance_id,
            ).exists():
                raise PluginStorageNotFoundError("plugin instance does not exist")
            raise StalePluginStateError("plugin instance changed; refresh and retry")
        return PluginInstance.objects.get(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=instance_id,
        )

    @staticmethod
    def delete(
        plugin_id: str,
        capability_id: str,
        instance_id: str,
        *,
        expected_version: int,
    ) -> None:
        instance = PluginInstanceRepository.get(plugin_id, capability_id, instance_id)
        deleted, _ = PluginInstance.objects.filter(
            pk=instance.pk, update_version=expected_version
        ).delete()
        if deleted != 1:
            raise StalePluginStateError("plugin instance changed; refresh and retry")

    @staticmethod
    def update_desired_state(
        plugin_id: str,
        capability_id: str,
        instance_id: str,
        *,
        desired_state: str,
        expected_version: int,
    ) -> PluginInstance:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        instance_id = _identifier(instance_id, "instance_id")
        if desired_state not in PluginDesiredState.values:
            raise PluginStorageError("invalid plugin instance desired state")
        updated = PluginInstance.objects.filter(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=instance_id,
            update_version=expected_version,
        ).update(
            desired_state=desired_state,
            update_version=F("update_version") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            if not PluginInstance.objects.filter(
                plugin_id=plugin_id,
                capability_id=capability_id,
                instance_id=instance_id,
            ).exists():
                raise PluginStorageNotFoundError("plugin instance does not exist")
            raise StalePluginStateError("plugin instance changed; refresh and retry")
        return PluginInstanceRepository.get(plugin_id, capability_id, instance_id)

    @staticmethod
    def record_observation(
        plugin_id: str,
        capability_id: str,
        instance_id: str,
        *,
        observed_state: str,
        runtime_facts: Mapping[str, object],
    ) -> PluginInstance:
        plugin_id = _identifier(plugin_id, "plugin_id")
        capability_id = _owned_identifier(plugin_id, capability_id, "capability_id")
        instance_id = _identifier(instance_id, "instance_id")
        if observed_state not in PluginObservedState.values:
            raise PluginStorageError("invalid plugin instance observed state")
        facts = _json_document(runtime_facts, "runtime_facts")
        updated = PluginInstance.objects.filter(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=instance_id,
        ).update(
            observed_state=observed_state,
            runtime_facts=facts,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise PluginStorageNotFoundError("plugin instance does not exist")
        return PluginInstanceRepository.get(plugin_id, capability_id, instance_id)


@dataclass(frozen=True, slots=True)
class PluginSecretPresence:
    plugin_id: str
    secret_id: str
    configured: bool
    update_version: int | None
    updated_at: str | None

    def to_document(self) -> dict[str, object]:
        return {
            "pluginId": self.plugin_id,
            "secretId": self.secret_id,
            "configured": self.configured,
            "updateVersion": self.update_version,
            "updatedAt": self.updated_at,
        }


class PluginSecretRepository:
    @staticmethod
    def _directory() -> Path:
        directory = Path(settings.OPEN_CINEMA_PLUGIN_SECRET_DIR)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        return directory.resolve()

    @classmethod
    def _path(cls, storage_key: str) -> Path:
        storage_key = _identifier(storage_key, "storage_key")
        directory = cls._directory()
        path = (directory / storage_key).resolve()
        if path.parent != directory:
            raise PluginStorageError("invalid secret storage path")
        return path

    @classmethod
    def _write(cls, storage_key: str, value: str | bytes) -> None:
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if not isinstance(raw, bytes) or not raw or len(raw) > PLUGIN_SECRET_MAX_BYTES:
            raise PluginStorageError("secret must contain between 1 and 65536 bytes")
        target = cls._path(storage_key)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".secret-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def set(
        cls,
        *,
        plugin_id: str,
        secret_id: str,
        value: str | bytes,
        expected_version: int | None = None,
    ) -> PluginSecretPresence:
        plugin_id = _identifier(plugin_id, "plugin_id")
        secret_id = _owned_identifier(plugin_id, secret_id, "secret_id")
        with transaction.atomic():
            reference = (
                PluginSecretReference.objects.select_for_update()
                .filter(plugin_id=plugin_id, secret_id=secret_id)
                .first()
            )
            if reference is None:
                if expected_version not in (None, 0):
                    raise StalePluginStateError("secret does not exist at that version")
                storage_key = f"secret-{uuid.uuid4().hex}"
                cls._write(storage_key, value)
                try:
                    reference = PluginSecretReference.objects.create(
                        plugin_id=plugin_id,
                        secret_id=secret_id,
                        storage_key=storage_key,
                    )
                except Exception:
                    cls._path(storage_key).unlink(missing_ok=True)
                    raise
            else:
                if expected_version is None or reference.update_version != expected_version:
                    raise StalePluginStateError("secret changed; refresh and retry")
                cls._write(reference.storage_key, value)
                reference.update_version += 1
                reference.save(update_fields=("update_version", "updated_at"))
        return cls.presence(plugin_id, secret_id)

    @staticmethod
    def presence(plugin_id: str, secret_id: str) -> PluginSecretPresence:
        plugin_id = _identifier(plugin_id, "plugin_id")
        secret_id = _owned_identifier(plugin_id, secret_id, "secret_id")
        reference = PluginSecretReference.objects.filter(
            plugin_id=plugin_id, secret_id=secret_id
        ).first()
        return PluginSecretPresence(
            plugin_id,
            secret_id,
            reference is not None,
            reference.update_version if reference else None,
            reference.updated_at.isoformat() if reference else None,
        )

    @classmethod
    def resolve_for_owner(
        cls,
        *,
        plugin_id: str,
        secret_id: str,
        owner_plugin_id: str,
    ) -> bytes:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if owner_plugin_id != plugin_id:
            raise PluginStorageOwnershipError("a plugin cannot resolve another plugin's secret")
        try:
            installation = PluginInstallation.objects.get(plugin_id=plugin_id)
        except PluginInstallation.DoesNotExist as error:
            raise PluginStorageOwnershipError("plugin is not installed") from error
        if installation.desired_state != PluginDesiredState.ENABLED:
            raise PluginStorageOwnershipError("plugin must be enabled to resolve secrets")
        secret_id = _owned_identifier(plugin_id, secret_id, "secret_id")
        try:
            reference = PluginSecretReference.objects.get(plugin_id=plugin_id, secret_id=secret_id)
        except PluginSecretReference.DoesNotExist as error:
            raise PluginStorageNotFoundError("secret is not configured") from error
        try:
            return cls._path(reference.storage_key).read_bytes()
        except OSError as error:
            raise PluginStorageNotFoundError("secret storage is unavailable") from error

    @classmethod
    def delete(
        cls,
        *,
        plugin_id: str,
        secret_id: str,
        expected_version: int,
    ) -> None:
        plugin_id = _identifier(plugin_id, "plugin_id")
        secret_id = _owned_identifier(plugin_id, secret_id, "secret_id")
        with transaction.atomic():
            reference = (
                PluginSecretReference.objects.select_for_update()
                .filter(plugin_id=plugin_id, secret_id=secret_id)
                .first()
            )
            if reference is None:
                raise PluginStorageNotFoundError("secret is not configured")
            if reference.update_version != expected_version:
                raise StalePluginStateError("secret changed; refresh and retry")
            path = cls._path(reference.storage_key)
            reference.delete()
            transaction.on_commit(lambda: path.unlink(missing_ok=True))


class PluginOperationRepository:
    @staticmethod
    def request(
        *,
        plugin_id: str,
        kind: str,
        idempotency_key: str,
        requested_by=None,
        effective_lifecycle_impact: str = "hot",
        stage_data: Mapping[str, object] | None = None,
    ) -> tuple[PluginOperation, bool]:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if kind not in PluginOperationKind.values:
            raise PluginStorageError("invalid plugin operation kind")
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > 256
        ):
            raise PluginStorageError("idempotency_key must be between 1 and 256 characters")
        defaults = {
            "plugin_id": plugin_id,
            "kind": kind,
            "requested_by": requested_by,
            "effective_lifecycle_impact": effective_lifecycle_impact,
            "stage_data": _json_document(redact_plugin_data(stage_data or {}), "stage_data"),
        }
        operation, created = PluginOperation.objects.get_or_create(
            idempotency_key=idempotency_key, defaults=defaults
        )
        if not created and (operation.plugin_id != plugin_id or operation.kind != kind):
            raise PluginStorageError("idempotency key belongs to another plugin operation")
        return operation, created

    @staticmethod
    def add_diagnostic(
        *,
        plugin_id: str,
        stage: str,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
        operation: PluginOperation | None = None,
        capability_id: str = "",
    ) -> PluginDiagnosticRecord:
        plugin_id = _identifier(plugin_id, "plugin_id")
        if capability_id:
            _owned_identifier(plugin_id, capability_id, "capability_id")
        if any(not isinstance(value, str) or not value for value in (stage, code, message)):
            raise PluginStorageError("diagnostic stage, code, and message are required")
        safe_details = _json_document(redact_plugin_data(details or {}), "details")
        return PluginDiagnosticRecord.objects.create(
            plugin_id=plugin_id,
            capability_id=capability_id,
            operation=operation,
            stage=stage[:64],
            code=code[:128],
            message=message[:2048],
            details=safe_details,
        )


@dataclass(frozen=True, slots=True)
class PluginGraphReference:
    definition_id: str
    definition_name: str
    revision_id: str
    revision_number: int
    capability_ids: tuple[str, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "definitionId": self.definition_id,
            "definitionName": self.definition_name,
            "revisionId": self.revision_id,
            "revisionNumber": self.revision_number,
            "capabilityIds": list(self.capability_ids),
        }


def _plugin_references(value: object, plugin_id: str) -> set[str]:
    references = set()
    if isinstance(value, Mapping):
        for item in value.values():
            references.update(_plugin_references(item, plugin_id))
    elif isinstance(value, (list, tuple)):
        for item in value:
            references.update(_plugin_references(item, plugin_id))
    elif isinstance(value, str) and value.startswith(f"{plugin_id}."):
        references.add(value)
    return references


def discover_plugin_graph_references(plugin_id: str) -> tuple[PluginGraphReference, ...]:
    plugin_id = _identifier(plugin_id, "plugin_id")
    found = []
    revisions = GraphRevision.objects.select_related("definition").all()
    for revision in revisions:
        capability_ids = tuple(sorted(_plugin_references(revision.content, plugin_id)))
        if capability_ids:
            found.append(
                PluginGraphReference(
                    str(revision.definition_id),
                    revision.definition.name,
                    str(revision.id),
                    revision.revision_number,
                    capability_ids,
                )
            )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class PluginUninstallResult:
    plugin_id: str
    data_deleted: bool
    graph_references: tuple[PluginGraphReference, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "pluginId": self.plugin_id,
            "dataDeleted": self.data_deleted,
            "graphReferences": [item.to_document() for item in self.graph_references],
        }


class PluginUninstallRepository:
    @staticmethod
    def uninstall(plugin_id: str, *, delete_data: bool) -> PluginUninstallResult:
        plugin_id = _identifier(plugin_id, "plugin_id")
        references = discover_plugin_graph_references(plugin_id)
        with transaction.atomic():
            try:
                installation = PluginInstallation.objects.select_for_update().get(
                    plugin_id=plugin_id
                )
            except PluginInstallation.DoesNotExist as error:
                raise PluginStorageNotFoundError("plugin is not installed") from error
            installation.desired_state = PluginDesiredState.DISABLED
            installation.observed_state = PluginObservedState.UNINSTALLED
            installation.aggregate_health = PluginAggregateHealth.UNKNOWN
            installation.active_generation = ""
            installation.retained_data = not delete_data
            installation.update_version += 1
            installation.save(
                update_fields=(
                    "desired_state",
                    "observed_state",
                    "aggregate_health",
                    "active_generation",
                    "retained_data",
                    "update_version",
                    "updated_at",
                )
            )
            PluginCapabilityState.objects.filter(plugin_id=plugin_id).delete()
            if delete_data:
                secret_paths = [
                    PluginSecretRepository._path(item.storage_key)
                    for item in PluginSecretReference.objects.filter(plugin_id=plugin_id)
                ]
                PluginDocument.objects.filter(plugin_id=plugin_id).delete()
                PluginInstance.objects.filter(plugin_id=plugin_id).delete()
                PluginSecretReference.objects.filter(plugin_id=plugin_id).delete()
                PluginDiagnosticRecord.objects.filter(
                    plugin_id=plugin_id, operation__isnull=True
                ).delete()
                transaction.on_commit(
                    lambda: [path.unlink(missing_ok=True) for path in secret_paths]
                )
        return PluginUninstallResult(plugin_id, delete_data, references)
