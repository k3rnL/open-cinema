from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.plugin_system.v2_contracts import ManagedResourceContext


@dataclass(frozen=True, slots=True)
class PluginDocument:
    document_id: str
    schema_version: int
    document: dict[str, object]
    update_version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record) -> PluginDocument:
        return cls(
            record.document_id,
            record.schema_version,
            dict(record.document),
            record.update_version,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.document_id,
            "schemaVersion": self.schema_version,
            "document": self.document,
            "updateVersion": self.update_version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class PluginDocumentStore:
    def __init__(
        self,
        *,
        plugin_id: str,
        collection: str,
        schema_id: str,
        schema_version: int,
        schema: Mapping[str, object],
    ) -> None:
        from core.plugin_system.storage import PLUGIN_STORAGE_SCHEMAS

        self.plugin_id = plugin_id
        self.collection = collection
        self.schema_id = schema_id
        self.schema_version = schema_version
        self.schema = dict(schema)
        PLUGIN_STORAGE_SCHEMAS.register(
            plugin_id=plugin_id,
            schema_id=schema_id,
            schema_version=schema_version,
            schema=self.schema,
        )

    def list(self) -> tuple[PluginDocument, ...]:
        from core.plugin_system.storage import PluginDocumentRepository

        return tuple(
            PluginDocument.from_record(item)
            for item in PluginDocumentRepository.list(
                self.plugin_id,
                self.collection,
                limit=100,
            )
        )

    def get(self, document_id: str) -> PluginDocument:
        from core.plugin_system.storage import PluginDocumentRepository

        return PluginDocument.from_record(
            PluginDocumentRepository.get(self.plugin_id, self.collection, document_id)
        )

    def get_optional(self, document_id: str) -> PluginDocument | None:
        from core.plugin_system.storage import (
            PluginDocumentRepository,
            PluginStorageNotFoundError,
        )

        try:
            record = PluginDocumentRepository.get(
                self.plugin_id,
                self.collection,
                document_id,
            )
        except PluginStorageNotFoundError:
            return None
        return PluginDocument.from_record(record)

    def put(
        self,
        document_id: str,
        document: Mapping[str, object],
        *,
        expected_version: int | None = None,
    ) -> PluginDocument:
        from core.plugin_system.storage import PluginDocumentRepository

        return PluginDocument.from_record(
            PluginDocumentRepository.put(
                plugin_id=self.plugin_id,
                collection=self.collection,
                document_id=document_id,
                schema_id=self.schema_id,
                schema_version=self.schema_version,
                document=document,
                schema=self.schema,
                expected_version=expected_version,
            )
        )

    def delete(self, document_id: str, *, expected_version: int) -> None:
        from core.plugin_system.storage import PluginDocumentRepository

        PluginDocumentRepository.delete(
            self.plugin_id,
            self.collection,
            document_id,
            expected_version=expected_version,
        )


@dataclass(frozen=True, slots=True)
class PluginInstanceDocument:
    instance_id: str
    display_name: str
    owner_id: object | None
    configuration_version: int
    configuration: dict[str, object]
    desired_state: str
    observed_state: str
    runtime_facts: dict[str, object]
    update_version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record) -> "PluginInstanceDocument":
        return cls(
            record.instance_id,
            record.display_name,
            record.owner_id,
            record.configuration_version,
            dict(record.configuration),
            record.desired_state,
            record.observed_state,
            dict(record.runtime_facts),
            record.update_version,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.instance_id,
            "displayName": self.display_name,
            "ownerId": self.owner_id,
            "configurationVersion": self.configuration_version,
            "configuration": self.configuration,
            "desiredState": self.desired_state,
            "observedState": self.observed_state,
            "runtimeFacts": self.runtime_facts,
            "updateVersion": self.update_version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class PluginInstanceStore:
    def __init__(
        self,
        *,
        plugin_id: str,
        capability_id: str,
        schema_id: str,
        schema_version: int,
        schema: Mapping[str, object],
    ) -> None:
        from core.plugin_system.storage import PLUGIN_STORAGE_SCHEMAS

        self.plugin_id = plugin_id
        self.capability_id = capability_id
        self.schema_id = schema_id
        self.schema_version = schema_version
        self.schema = dict(schema)
        PLUGIN_STORAGE_SCHEMAS.register(
            plugin_id=plugin_id,
            schema_id=schema_id,
            schema_version=schema_version,
            schema=self.schema,
        )

    def list(self) -> tuple[PluginInstanceDocument, ...]:
        from core.plugin_system.storage import PluginInstanceRepository

        return tuple(
            PluginInstanceDocument.from_record(item)
            for item in PluginInstanceRepository.list(
                self.plugin_id, self.capability_id, limit=100
            )
        )

    def get(self, instance_id: str) -> PluginInstanceDocument:
        from core.plugin_system.storage import PluginInstanceRepository

        return PluginInstanceDocument.from_record(
            PluginInstanceRepository.get(
                self.plugin_id, self.capability_id, instance_id
            )
        )

    def create(
        self,
        *,
        instance_id: str,
        display_name: str,
        configuration: Mapping[str, object],
        enabled: bool = True,
        owner_id: object | None = None,
    ) -> PluginInstanceDocument:
        from core.plugin_system.storage import PluginInstanceRepository

        return PluginInstanceDocument.from_record(
            PluginInstanceRepository.create(
                plugin_id=self.plugin_id,
                capability_id=self.capability_id,
                instance_id=instance_id,
                display_name=display_name,
                configuration_version=self.schema_version,
                configuration=configuration,
                schema=self.schema,
                desired_state="enabled" if enabled else "disabled",
                owner_id=owner_id,
            )
        )

    def update(
        self,
        instance_id: str,
        *,
        configuration: Mapping[str, object],
        expected_version: int,
    ) -> PluginInstanceDocument:
        from core.plugin_system.storage import PluginInstanceRepository

        return PluginInstanceDocument.from_record(
            PluginInstanceRepository.update_configuration(
                plugin_id=self.plugin_id,
                capability_id=self.capability_id,
                instance_id=instance_id,
                configuration_version=self.schema_version,
                configuration=configuration,
                schema=self.schema,
                expected_version=expected_version,
            )
        )

    def set_enabled(
        self,
        instance_id: str,
        *,
        enabled: bool,
        expected_version: int,
    ) -> PluginInstanceDocument:
        from core.plugin_system.storage import PluginInstanceRepository

        return PluginInstanceDocument.from_record(
            PluginInstanceRepository.update_desired_state(
                self.plugin_id,
                self.capability_id,
                instance_id,
                desired_state="enabled" if enabled else "disabled",
                expected_version=expected_version,
            )
        )

    def record_observation(
        self,
        instance_id: str,
        *,
        observed_state: str,
        runtime_facts: Mapping[str, object],
    ) -> PluginInstanceDocument:
        from core.plugin_system.storage import PluginInstanceRepository

        return PluginInstanceDocument.from_record(
            PluginInstanceRepository.record_observation(
                self.plugin_id,
                self.capability_id,
                instance_id,
                observed_state=observed_state,
                runtime_facts=runtime_facts,
            )
        )

    def delete(self, instance_id: str, *, expected_version: int) -> None:
        from core.plugin_system.storage import PluginInstanceRepository

        PluginInstanceRepository.delete(
            self.plugin_id,
            self.capability_id,
            instance_id,
            expected_version=expected_version,
        )

    def context(
        self, instance_id: str, *, deadline_ms: int = 5000
    ) -> ManagedResourceContext:
        from core.plugin_system.host_services import CorePluginHostServices

        item = self.get(instance_id)
        return ManagedResourceContext(
            self.plugin_id,
            self.capability_id,
            item.instance_id,
            item.configuration,
            item.configuration_version,
            concurrency_token=str(item.update_version),
            deadline_ms=deadline_ms,
            host_services=CorePluginHostServices(self.plugin_id, item.instance_id),
        )


class PluginSecretStore:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id

    def presence(self, secret_id: str) -> dict[str, object]:
        from core.plugin_system.storage import PluginSecretRepository

        return PluginSecretRepository.presence(self.plugin_id, secret_id).to_document()

    def set(
        self,
        secret_id: str,
        value: str | bytes,
        *,
        expected_version: int | None = None,
    ) -> dict[str, object]:
        from core.plugin_system.storage import PluginSecretRepository

        return PluginSecretRepository.set(
            plugin_id=self.plugin_id,
            secret_id=secret_id,
            value=value,
            expected_version=expected_version,
        ).to_document()

    def delete(self, secret_id: str, *, expected_version: int) -> None:
        from core.plugin_system.storage import PluginSecretRepository

        PluginSecretRepository.delete(
            plugin_id=self.plugin_id,
            secret_id=secret_id,
            expected_version=expected_version,
        )
