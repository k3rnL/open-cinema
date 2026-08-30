from __future__ import annotations

import os

import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    PluginDesiredState,
    PluginAggregateHealth,
    PluginDocument,
    PluginInstallation,
    PluginInstance,
    PluginSecretReference,
    PluginObservedState,
)
from core.plugin_system.storage import (
    PluginConfigurationMigrationError,
    PluginConfigurationRepository,
    PluginDocumentRepository,
    PluginInstallationRepository,
    PluginInstanceRepository,
    PluginOperationRepository,
    PluginSecretRepository,
    PluginStorageError,
    PluginStorageOwnershipError,
    PluginUninstallRepository,
    StalePluginStateError,
)

pytestmark = pytest.mark.django_db

PLUGIN_ID = "test.storage"
CONFIGURATION_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string"}},
    "additionalProperties": False,
}


def _installation(*, desired_state=PluginDesiredState.DISABLED):
    return PluginInstallationRepository.save_snapshot(
        plugin_id=PLUGIN_ID,
        distribution_id="open-cinema-test-storage",
        installed_version="1.0.0",
        manifest={"id": PLUGIN_ID, "version": "1.0.0"},
        provenance={"sourceType": "test", "resolvedRevision": "abc123"},
        lifecycle_impact={"enable": "hot", "disable": "hot"},
        desired_state=desired_state,
    )


def test_namespaced_documents_validate_and_use_optimistic_concurrency() -> None:
    _installation()
    created = PluginDocumentRepository.put(
        plugin_id=PLUGIN_ID,
        collection="test.storage.presets",
        document_id="living-room",
        schema_id="test.storage.preset",
        schema_version=1,
        document={"name": "Living room"},
        schema=CONFIGURATION_SCHEMA,
    )

    updated = PluginDocumentRepository.put(
        plugin_id=PLUGIN_ID,
        collection="test.storage.presets",
        document_id="living-room",
        schema_id="test.storage.preset",
        schema_version=1,
        document={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
        expected_version=created.update_version,
    )

    assert updated.document == {"name": "Cinema"}
    assert updated.update_version == 2
    assert PluginDocumentRepository.list(PLUGIN_ID, "test.storage.presets") == (updated,)
    with pytest.raises(StalePluginStateError):
        PluginDocumentRepository.put(
            plugin_id=PLUGIN_ID,
            collection="test.storage.presets",
            document_id="living-room",
            schema_id="test.storage.preset",
            schema_version=1,
            document={"name": "Stale"},
            schema=CONFIGURATION_SCHEMA,
            expected_version=1,
        )
    with pytest.raises(PluginStorageOwnershipError):
        PluginDocumentRepository.list(PLUGIN_ID, "another.plugin.presets")
    with pytest.raises(PluginStorageError, match="required property"):
        PluginDocumentRepository.put(
            plugin_id=PLUGIN_ID,
            collection="test.storage.presets",
            document_id="invalid",
            schema_id="test.storage.preset",
            schema_version=1,
            document={},
            schema=CONFIGURATION_SCHEMA,
        )


def test_configuration_migrates_version_by_version_and_failure_preserves_active_document() -> None:
    _installation()
    original = PluginConfigurationRepository.put(
        plugin_id=PLUGIN_ID,
        schema_version=1,
        document={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
    )
    version_two_schema = {
        "type": "object",
        "required": ["name", "enabled"],
        "properties": {
            "name": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        "additionalProperties": False,
    }

    migrated = PluginConfigurationRepository.migrate(
        plugin_id=PLUGIN_ID,
        target_version=2,
        schemas={2: version_two_schema},
        migrations={1: lambda document: {**document.to_dict(), "enabled": True}},
    )

    assert migrated.schema_version == 2
    assert migrated.document == {"name": "Cinema", "enabled": True}
    assert migrated.update_version == original.update_version + 1

    with pytest.raises(PluginConfigurationMigrationError, match="missing"):
        PluginConfigurationRepository.migrate(
            plugin_id=PLUGIN_ID,
            target_version=3,
            schemas={},
            migrations={},
        )

    preserved = PluginConfigurationRepository.get(PLUGIN_ID)
    assert preserved.schema_version == 2
    assert preserved.document == {"name": "Cinema", "enabled": True}
    assert preserved.update_version == migrated.update_version


def test_disable_reenable_and_incompatible_upgrade_preserve_configuration() -> None:
    installation = _installation(desired_state=PluginDesiredState.ENABLED)
    configuration = PluginConfigurationRepository.put(
        plugin_id=PLUGIN_ID,
        schema_version=1,
        document={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
    )
    disabled = PluginInstallationRepository.set_desired_state(
        PLUGIN_ID,
        PluginDesiredState.DISABLED,
        expected_version=installation.update_version,
    )
    PluginInstallationRepository.set_desired_state(
        PLUGIN_ID,
        PluginDesiredState.ENABLED,
        expected_version=disabled.update_version,
    )
    PluginInstallationRepository.save_snapshot(
        plugin_id=PLUGIN_ID,
        distribution_id="open-cinema-test-storage",
        installed_version="2.0.0",
        manifest={"id": PLUGIN_ID, "version": "2.0.0"},
        provenance={"sourceType": "test", "resolvedRevision": "def456"},
        lifecycle_impact={"enable": "hot", "disable": "hot"},
    )
    PluginInstallationRepository.set_observed_state(
        PLUGIN_ID,
        PluginObservedState.INCOMPATIBLE,
        PluginAggregateHealth.INCOMPATIBLE,
    )

    assert PluginConfigurationRepository.get(PLUGIN_ID).pk == configuration.pk
    assert PluginConfigurationRepository.get(PLUGIN_ID).document == {"name": "Cinema"}
    assert PluginInstallation.objects.get(plugin_id=PLUGIN_ID).installed_version == "2.0.0"


def test_repeatable_instances_have_stable_ids_validation_and_concurrency() -> None:
    _installation()
    created = PluginInstanceRepository.create(
        plugin_id=PLUGIN_ID,
        capability_id="test.storage.source",
        instance_id="living-room",
        display_name="Living room",
        configuration_version=1,
        configuration={"name": "Living room"},
        schema=CONFIGURATION_SCHEMA,
    )

    updated = PluginInstanceRepository.update_configuration(
        plugin_id=PLUGIN_ID,
        capability_id="test.storage.source",
        instance_id="living-room",
        configuration_version=1,
        configuration={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
        expected_version=created.update_version,
    )

    assert updated.id == created.id
    assert updated.update_version == 2
    assert PluginInstanceRepository.list(PLUGIN_ID, "test.storage.source") == (updated,)
    with pytest.raises(StalePluginStateError):
        PluginInstanceRepository.update_configuration(
            plugin_id=PLUGIN_ID,
            capability_id="test.storage.source",
            instance_id="living-room",
            configuration_version=1,
            configuration={"name": "Stale"},
            schema=CONFIGURATION_SCHEMA,
            expected_version=1,
        )


def test_secrets_are_write_only_owner_scoped_and_redacted(tmp_path, settings) -> None:
    settings.OPEN_CINEMA_PLUGIN_SECRET_DIR = tmp_path / "secrets"
    installation = _installation()
    secret_value = "this-value-must-never-be-serialized"

    presence = PluginSecretRepository.set(
        plugin_id=PLUGIN_ID,
        secret_id="test.storage.access-token",
        value=secret_value,
    )
    reference = PluginSecretReference.objects.get(plugin_id=PLUGIN_ID)
    operation, _ = PluginOperationRepository.request(
        plugin_id=PLUGIN_ID,
        kind="enable",
        idempotency_key="test-secret-redaction",
        stage_data={"accessToken": secret_value, "ordinary": "visible"},
    )
    diagnostic = PluginOperationRepository.add_diagnostic(
        plugin_id=PLUGIN_ID,
        stage="test",
        code="redaction-test",
        message="A safe diagnostic",
        details={"password": secret_value, "ordinary": "visible"},
        operation=operation,
    )

    assert presence.to_document() == {
        "pluginId": PLUGIN_ID,
        "secretId": "test.storage.access-token",
        "configured": True,
        "updateVersion": 1,
        "updatedAt": presence.updated_at,
    }
    assert secret_value not in str(presence.to_document())
    assert secret_value not in reference.storage_key
    assert not hasattr(reference, "ciphertext")
    assert operation.stage_data == {"accessToken": "[redacted]", "ordinary": "visible"}
    assert diagnostic.details == {"password": "[redacted]", "ordinary": "visible"}
    secret_path = settings.OPEN_CINEMA_PLUGIN_SECRET_DIR / reference.storage_key
    assert (os.stat(secret_path).st_mode & 0o777) == 0o600

    with pytest.raises(PluginStorageOwnershipError):
        PluginSecretRepository.resolve_for_owner(
            plugin_id=PLUGIN_ID,
            secret_id="test.storage.access-token",
            owner_plugin_id="test.attacker",
        )
    with pytest.raises(PluginStorageOwnershipError, match="enabled"):
        PluginSecretRepository.resolve_for_owner(
            plugin_id=PLUGIN_ID,
            secret_id="test.storage.access-token",
            owner_plugin_id=PLUGIN_ID,
        )

    PluginInstallationRepository.set_desired_state(
        PLUGIN_ID,
        PluginDesiredState.ENABLED,
        expected_version=installation.update_version,
    )
    assert (
        PluginSecretRepository.resolve_for_owner(
            plugin_id=PLUGIN_ID,
            secret_id="test.storage.access-token",
            owner_plugin_id=PLUGIN_ID,
        )
        == secret_value.encode()
    )
    replaced = PluginSecretRepository.set(
        plugin_id=PLUGIN_ID,
        secret_id="test.storage.access-token",
        value="replacement",
        expected_version=presence.update_version,
    )
    assert replaced.update_version == 2
    PluginSecretRepository.delete(
        plugin_id=PLUGIN_ID,
        secret_id="test.storage.access-token",
        expected_version=replaced.update_version,
    )
    assert not PluginSecretRepository.presence(PLUGIN_ID, "test.storage.access-token").configured


def test_uninstall_retains_or_deletes_plugin_data_without_deleting_graphs(
    tmp_path, settings
) -> None:
    settings.OPEN_CINEMA_PLUGIN_SECRET_DIR = tmp_path / "secrets"
    _installation()
    PluginConfigurationRepository.put(
        plugin_id=PLUGIN_ID,
        schema_version=1,
        document={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
    )
    PluginInstanceRepository.create(
        plugin_id=PLUGIN_ID,
        capability_id="test.storage.source",
        instance_id="main",
        display_name="Main",
        configuration_version=1,
        configuration={"name": "Cinema"},
        schema=CONFIGURATION_SCHEMA,
    )
    PluginSecretRepository.set(
        plugin_id=PLUGIN_ID,
        secret_id="test.storage.token",
        value="secret",
    )
    owner = get_user_model().objects.create_user(username="plugin-storage-graph")
    definition = GraphDefinition.objects.create(name="Plugin reference", owner=owner)
    revision = GraphRevision.objects.create(
        definition=definition,
        revision_number=1,
        state=GraphRevisionState.DRAFT,
        author=owner,
        content={
            "nodes": [
                {
                    "id": "source",
                    "type": "test.storage.source",
                    "configuration": {},
                }
            ],
            "edges": [],
        },
    )

    retained = PluginUninstallRepository.uninstall(PLUGIN_ID, delete_data=False)

    assert not retained.data_deleted
    assert retained.graph_references[0].capability_ids == ("test.storage.source",)
    assert PluginDocument.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert PluginInstance.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert PluginSecretReference.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert GraphRevision.objects.filter(pk=revision.pk).exists()
    PluginInstallationRepository.save_snapshot(
        plugin_id=PLUGIN_ID,
        distribution_id="open-cinema-test-storage",
        installed_version="1.1.0",
        manifest={"id": PLUGIN_ID, "version": "1.1.0"},
        provenance={"sourceType": "test", "resolvedRevision": "reinstalled"},
        lifecycle_impact={"enable": "hot", "disable": "hot"},
    )
    assert PluginConfigurationRepository.validate_retained(
        PLUGIN_ID, {1: CONFIGURATION_SCHEMA}
    ).document == {"name": "Cinema"}
    with pytest.raises(PluginConfigurationMigrationError, match="unsupported"):
        PluginConfigurationRepository.validate_retained(PLUGIN_ID, {2: CONFIGURATION_SCHEMA})

    deleted = PluginUninstallRepository.uninstall(PLUGIN_ID, delete_data=True)

    assert deleted.data_deleted
    assert not PluginDocument.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert not PluginInstance.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert not PluginSecretReference.objects.filter(plugin_id=PLUGIN_ID).exists()
    assert GraphRevision.objects.filter(pk=revision.pk).exists()
    installation = PluginInstallation.objects.get(plugin_id=PLUGIN_ID)
    assert installation.observed_state == "uninstalled"
