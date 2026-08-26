import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATE_FROM = ("api", "0038_alter_pulseaudiotunnelnodestate_device")
MIGRATE_TO = ("api", "0048_graph_revision_update_version")
REMOVE_LEGACY_AT = ("api", "0051_remove_legacy_audio_models")


def _executor():
    return MigrationExecutor(connection)


def test_orchestration_migrations_are_forward_and_rollback_safe() -> None:
    executor = _executor()
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([MIGRATE_FROM])
        legacy_apps = executor.loader.project_state([MIGRATE_FROM]).apps
        LegacyPipeline = legacy_apps.get_model("api", "AudioPipeline")
        legacy = LegacyPipeline.objects.create(name="Migration-surviving pipeline")

        executor = _executor()
        executor.migrate([MIGRATE_TO])
        forward_apps = executor.loader.project_state([MIGRATE_TO]).apps
        SchemaState = forward_apps.get_model("api", "OrchestrationSchemaState")
        GraphDefinition = forward_apps.get_model("api", "GraphDefinition")
        DiagnosticRecord = forward_apps.get_model("api", "DiagnosticRecord")
        assert SchemaState.objects.get(pk=1).version == 1
        assert GraphDefinition._meta.db_table in connection.introspection.table_names()
        assert DiagnosticRecord._meta.db_table in connection.introspection.table_names()

        executor = _executor()
        executor.migrate([MIGRATE_FROM])
        rolled_back_apps = executor.loader.project_state([MIGRATE_FROM]).apps
        RolledBackPipeline = rolled_back_apps.get_model("api", "AudioPipeline")
        assert RolledBackPipeline.objects.filter(pk=legacy.pk).exists()
        tables = connection.introspection.table_names()
        assert "api_graphdefinition" not in tables
        assert "api_orchestrationevent" not in tables
        assert "api_audiopipeline" in tables
    finally:
        _executor().migrate(latest_targets)


def test_unused_legacy_audio_schema_is_deleted_with_its_data() -> None:
    executor = _executor()
    latest_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([MIGRATE_FROM])
        old_apps = executor.loader.project_state([MIGRATE_FROM]).apps
        OldDevice = old_apps.get_model("api", "KnownAudioDevice")
        OldPipeline = old_apps.get_model("api", "AudioPipeline")
        OldDevice.objects.create(
            backend="pulseaudio",
            name="discarded-device",
            device_type="PLAYBACK",
            format="S16LE",
            sample_rate=48000,
            channels=2,
        )
        OldPipeline.objects.create(name="Discarded pipeline")

        executor = _executor()
        executor.migrate([REMOVE_LEGACY_AT])
        new_apps = executor.loader.project_state([REMOVE_LEGACY_AT]).apps
        with pytest.raises(LookupError):
            new_apps.get_model("api", "KnownAudioDevice")
        with pytest.raises(LookupError):
            new_apps.get_model("api", "AudioPipeline")

        tables = connection.introspection.table_names()
        assert "api_knownaudiodevice" not in tables
        assert "api_audiopipeline" not in tables
        assert "api_camilladsppipeline" not in tables
        assert "api_preferencesaudiobackend" not in tables
        assert "api_pulseaudiocreatedmodule" not in tables
        assert "api_camilladspprofile" in tables
    finally:
        _executor().migrate(latest_targets)
