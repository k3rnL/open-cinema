import importlib
import sys

import pytest

from api.models.orchestration_schema_state import OrchestrationSchemaState
from core.orchestration.schema_version import (
    CURRENT_ORCHESTRATION_SCHEMA_VERSION,
    MissingOrchestrationSchemaMarker,
    UnsupportedOrchestrationSchema,
    ensure_persistent_orchestration_schema_compatible,
    validate_orchestration_schema_version,
)


def test_supported_schema_version_is_accepted() -> None:
    validate_orchestration_schema_version(CURRENT_ORCHESTRATION_SCHEMA_VERSION)


def test_future_schema_version_is_rejected() -> None:
    with pytest.raises(UnsupportedOrchestrationSchema, match="compatible newer release"):
        validate_orchestration_schema_version(CURRENT_ORCHESTRATION_SCHEMA_VERSION + 1)


@pytest.mark.django_db
def test_persistent_marker_is_initialized_by_migration() -> None:
    assert (
        ensure_persistent_orchestration_schema_compatible()
        == CURRENT_ORCHESTRATION_SCHEMA_VERSION
    )


@pytest.mark.django_db
def test_future_persistent_marker_is_rejected_without_database_changes() -> None:
    marker = OrchestrationSchemaState.objects.get(pk=1)
    marker.version = CURRENT_ORCHESTRATION_SCHEMA_VERSION + 1
    marker.save(update_fields=["version", "updated_at"])
    before = OrchestrationSchemaState.objects.values("id", "version", "updated_at").get(pk=1)

    with pytest.raises(UnsupportedOrchestrationSchema, match="did not modify the database"):
        ensure_persistent_orchestration_schema_compatible()

    after = OrchestrationSchemaState.objects.values("id", "version", "updated_at").get(pk=1)
    assert after == before


@pytest.mark.django_db
def test_missing_persistent_marker_is_rejected_without_recreation() -> None:
    OrchestrationSchemaState.objects.all().delete()

    with pytest.raises(MissingOrchestrationSchemaMarker, match="marker is missing"):
        ensure_persistent_orchestration_schema_compatible()

    assert not OrchestrationSchemaState.objects.exists()


@pytest.mark.django_db
def test_wsgi_startup_refuses_a_future_schema() -> None:
    marker = OrchestrationSchemaState.objects.get(pk=1)
    marker.version = CURRENT_ORCHESTRATION_SCHEMA_VERSION + 1
    marker.save(update_fields=["version", "updated_at"])
    sys.modules.pop("opencinema.wsgi", None)

    with pytest.raises(UnsupportedOrchestrationSchema, match="compatible newer release"):
        importlib.import_module("opencinema.wsgi")
