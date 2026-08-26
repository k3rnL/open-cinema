"""Read-only compatibility guard for persisted orchestration state."""

from __future__ import annotations

CURRENT_ORCHESTRATION_SCHEMA_VERSION = 1
MINIMUM_ORCHESTRATION_SCHEMA_VERSION = 1


class OrchestrationSchemaCompatibilityError(RuntimeError):
    """Base error raised before a process uses incompatible persistent state."""


class MissingOrchestrationSchemaMarker(OrchestrationSchemaCompatibilityError):
    pass


class UnsupportedOrchestrationSchema(OrchestrationSchemaCompatibilityError):
    pass


def validate_orchestration_schema_version(version: int) -> None:
    if version > CURRENT_ORCHESTRATION_SCHEMA_VERSION:
        raise UnsupportedOrchestrationSchema(
            "The database uses orchestration schema "
            f"{version}, but this Open Cinema release supports at most "
            f"{CURRENT_ORCHESTRATION_SCHEMA_VERSION}. Deploy a compatible newer "
            "release; this process did not modify the database."
        )
    if version < MINIMUM_ORCHESTRATION_SCHEMA_VERSION:
        raise UnsupportedOrchestrationSchema(
            "The database uses orchestration schema "
            f"{version}, but this release requires at least "
            f"{MINIMUM_ORCHESTRATION_SCHEMA_VERSION}. Run the coordinated "
            "database migrations before starting services."
        )


def ensure_persistent_orchestration_schema_compatible() -> int:
    """Read and validate the singleton marker without creating or updating it."""
    from api.models.orchestration_schema_state import OrchestrationSchemaState

    try:
        version = OrchestrationSchemaState.objects.values_list("version", flat=True).get(pk=1)
    except OrchestrationSchemaState.DoesNotExist as error:
        raise MissingOrchestrationSchemaMarker(
            "The orchestration schema marker is missing. Run the coordinated "
            "database migrations before starting services."
        ) from error

    validate_orchestration_schema_version(version)
    return version
