from __future__ import annotations

import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api.models import (
    PluginAggregateHealth,
    PluginDesiredState,
    PluginInstallation,
    PluginObservedState,
    PluginOperation,
    PluginOperationKind,
    PluginOperationStatus,
)

from .acquisition import (
    CatalogueWheelAcquirer,
    GitPluginAcquirer,
    InspectedPluginWheel,
    PluginAcquisitionError,
    inspect_plugin_wheel,
    verify_catalogue_wheel,
)
from .catalogue import FirstPartyPluginCatalogue
from .contracts import PluginHealth, PluginLifecycleState
from .overlay import (
    PluginControlHelper,
    PluginGenerationBuilder,
    PluginOverlayManager,
)
from .storage import (
    PluginInstallationRepository,
    PluginOperationRepository,
    PluginUninstallRepository,
    StalePluginStateError,
    redact_plugin_data,
)
from .v2_contracts import (
    CapabilityKind,
    DistributionLifecycleContext,
    LifecycleImpact,
    OpenCinemaPlugin,
    PluginDesiredState as RuntimeDesiredState,
    PluginRuntimeResult,
    RuntimeStatus,
)

ACTIVE_OPERATION_STATUSES = (
    PluginOperationStatus.REQUESTED,
    PluginOperationStatus.RUNNING,
    PluginOperationStatus.RESTART_PENDING,
    PluginOperationStatus.VERIFYING,
    PluginOperationStatus.ROLLING_BACK,
)
TERMINAL_OPERATION_STATUSES = (
    PluginOperationStatus.SUCCEEDED,
    PluginOperationStatus.FAILED,
    PluginOperationStatus.CANCELLED,
)


class PluginOperationError(RuntimeError):
    pass


def plugin_overlay_manager() -> PluginOverlayManager:
    return PluginOverlayManager(
        Path(settings.OPEN_CINEMA_PLUGIN_ROOT),
        retention=settings.OPEN_CINEMA_PLUGIN_GENERATION_RETENTION,
    )


def plugin_generation_builder(manager: PluginOverlayManager) -> PluginGenerationBuilder:
    return PluginGenerationBuilder(
        manager,
        max_generation_bytes=settings.OPEN_CINEMA_PLUGIN_GENERATION_MAX_BYTES,
    )


def operation_document(operation: PluginOperation) -> dict[str, object]:
    diagnostics = list(operation.diagnostics or [])[-32:]
    document = {
        "id": str(operation.pk),
        "pluginId": operation.plugin_id,
        "kind": operation.kind,
        "status": operation.status,
        "stage": operation.stage,
        "progress": operation.progress,
        "effectiveLifecycleImpact": operation.effective_lifecycle_impact,
        "inputGeneration": operation.input_generation or None,
        "outputGeneration": operation.output_generation or None,
        "cancellation": {
            "requested": operation.cancellation_requested,
            "allowed": operation.cancellation_allowed,
        },
        "concurrencyToken": str(operation.concurrency_token),
        "diagnostics": diagnostics,
        "requestedAt": operation.requested_at.isoformat(),
        "startedAt": operation.started_at.isoformat() if operation.started_at else None,
        "updatedAt": operation.updated_at.isoformat(),
        "completedAt": operation.completed_at.isoformat()
        if operation.completed_at
        else None,
        "links": {
            "self": f"/api/plugin-platform/v2/operations/{operation.pk}",
            "cancel": f"/api/plugin-platform/v2/operations/{operation.pk}/cancel",
        },
    }
    if operation.status == PluginOperationStatus.RESTART_PENDING:
        from api.models import SystemControlAction
        from api.system_v1.control import action_document

        action = (
            SystemControlAction.REBOOT_APPLIANCE
            if operation.effective_lifecycle_impact == LifecycleImpact.HOST_REBOOT
            else SystemControlAction.RESTART_OPEN_CINEMA
        )
        document["restartAction"] = action_document(action)
    else:
        document["restartAction"] = None
    return document


def installation_action_documents(
    installation: PluginInstallation,
) -> list[dict[str, object]]:
    base = f"/api/plugin-platform/v2/plugins/{installation.plugin_id}/actions"
    token = str(installation.update_version)
    actions = []
    if installation.observed_state != PluginObservedState.UNINSTALLED:
        state_action = (
            PluginOperationKind.DISABLE
            if installation.desired_state == PluginDesiredState.ENABLED
            else PluginOperationKind.ENABLE
        )
        actions.append(
            {
                "id": state_action,
                "label": "Disable" if state_action == "disable" else "Enable",
                "available": installation.observed_state
                != PluginObservedState.RESTART_PENDING,
                "reason": (
                    "An application restart is pending."
                    if installation.observed_state
                    == PluginObservedState.RESTART_PENDING
                    else None
                ),
                "method": "POST",
                "href": f"{base}/{state_action}",
                "confirmation": "confirm",
                "concurrencyToken": token,
                "lifecycleImpact": installation.lifecycle_impact.get(
                    state_action,
                    "hot",
                ),
            }
        )
        actions.append(
            {
                "id": PluginOperationKind.UNINSTALL,
                "label": "Uninstall",
                "available": installation.observed_state
                != PluginObservedState.RESTART_PENDING,
                "reason": None,
                "method": "POST",
                "href": f"{base}/uninstall",
                "confirmation": "destructive",
                "concurrencyToken": token,
                "lifecycleImpact": "application-restart",
            }
        )
        provenance = installation.provenance_snapshot
        if provenance.get("sourceUrl"):
            actions.append(
                {
                    "id": PluginOperationKind.UPDATE,
                    "label": "Update",
                    "available": installation.observed_state
                    != PluginObservedState.RESTART_PENDING,
                    "reason": None,
                    "method": "POST",
                    "href": f"{base}/update",
                    "confirmation": "disconnecting",
                    "concurrencyToken": token,
                    "lifecycleImpact": "application-restart",
                }
            )
    if installation.last_known_good_generation:
        actions.append(
            {
                "id": PluginOperationKind.ROLLBACK,
                "label": "Roll back",
                "available": installation.observed_state
                != PluginObservedState.RESTART_PENDING,
                "reason": None,
                "method": "POST",
                "href": f"{base}/rollback",
                "confirmation": "destructive",
                "concurrencyToken": token,
                "lifecycleImpact": "application-restart",
            }
        )
    return actions


def _operation_impact(
    installation: PluginInstallation | None,
    kind: str,
    *,
    requested: str | None = None,
) -> LifecycleImpact:
    declared = LifecycleImpact.HOT
    if installation is not None:
        value = installation.lifecycle_impact.get(kind)
        if value is not None:
            declared = LifecycleImpact(value)
    if requested is not None:
        declared = LifecycleImpact.maximum(declared, requested)
    if kind in {
        PluginOperationKind.INSTALL,
        PluginOperationKind.UPDATE,
        PluginOperationKind.UNINSTALL,
        PluginOperationKind.ROLLBACK,
    }:
        return LifecycleImpact.maximum(
            declared,
            LifecycleImpact.APPLICATION_RESTART,
        )
    return declared


def request_plugin_operation(
    *,
    plugin_id: str,
    kind: str,
    idempotency_key: str,
    requested_by,
    expected_version: int | None,
    stage_data: Mapping[str, object] | None = None,
) -> tuple[PluginOperation, bool]:
    with transaction.atomic():
        active = (
            PluginOperation.objects.select_for_update()
            .filter(status__in=ACTIVE_OPERATION_STATUSES)
            .exclude(idempotency_key=idempotency_key)
            .first()
        )
        if active is not None:
            raise PluginOperationError(
                f"plugin environment operation {active.pk} is already active"
            )
        installation = (
            PluginInstallation.objects.select_for_update()
            .filter(plugin_id=plugin_id)
            .first()
        )
        if kind not in {
            PluginOperationKind.INSTALL,
            PluginOperationKind.CLEANUP,
            PluginOperationKind.RETRY,
        }:
            if installation is None:
                raise PluginOperationError("plugin is not installed")
            if expected_version is None:
                raise PluginOperationError("expectedVersion is required")
            if installation.update_version != expected_version:
                raise StalePluginStateError(
                    "plugin installation changed; refresh and retry"
                )
        impact = _operation_impact(installation, kind)
        operation, created = PluginOperationRepository.request(
            plugin_id=plugin_id,
            kind=kind,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
            effective_lifecycle_impact=impact.value,
            stage_data=stage_data,
        )
        return operation, created


def request_operation_cancellation(
    operation_id: uuid.UUID,
    *,
    concurrency_token: str,
) -> PluginOperation:
    with transaction.atomic():
        operation = PluginOperation.objects.select_for_update().get(pk=operation_id)
        if str(operation.concurrency_token) != concurrency_token:
            raise StalePluginStateError("plugin operation changed; refresh and retry")
        if operation.status in TERMINAL_OPERATION_STATUSES:
            return operation
        if not operation.cancellation_allowed:
            raise PluginOperationError(
                "this operation can no longer be cancelled safely"
            )
        operation.cancellation_requested = True
        operation.save(update_fields=("cancellation_requested", "updated_at"))
        return operation


def _set_stage(
    operation: PluginOperation,
    stage: str,
    progress: int,
    *,
    status: str = PluginOperationStatus.RUNNING,
    cancellation_allowed: bool = True,
    **fields: object,
) -> None:
    operation.stage = stage
    operation.progress = progress
    operation.status = status
    operation.cancellation_allowed = cancellation_allowed
    if operation.started_at is None:
        operation.started_at = timezone.now()
    update_fields = [
        "stage",
        "progress",
        "status",
        "cancellation_allowed",
        "started_at",
        "updated_at",
    ]
    for name, value in fields.items():
        setattr(operation, name, value)
        update_fields.append(name)
    operation.save(update_fields=tuple(update_fields))


def _cancel_if_requested(operation: PluginOperation) -> None:
    operation.refresh_from_db(fields=("cancellation_requested", "cancellation_allowed"))
    if operation.cancellation_requested and operation.cancellation_allowed:
        operation.status = PluginOperationStatus.CANCELLED
        operation.stage = "cancelled"
        operation.completed_at = timezone.now()
        operation.save(update_fields=("status", "stage", "completed_at", "updated_at"))
        raise PluginOperationError("operation-cancelled")


def _fail(operation: PluginOperation, error: Exception) -> None:
    if str(error) == "operation-cancelled":
        return
    diagnostic = {
        "stage": operation.stage,
        "code": "plugin-operation-failed",
        "message": str(error)[:2048],
        "exception": type(error).__name__,
    }
    operation.status = PluginOperationStatus.FAILED
    operation.progress = min(operation.progress, 99)
    operation.diagnostics = [
        *list(operation.diagnostics or [])[-31:],
        redact_plugin_data(diagnostic),
    ]
    operation.completed_at = timezone.now()
    operation.save(
        update_fields=(
            "status",
            "progress",
            "diagnostics",
            "completed_at",
            "updated_at",
        )
    )
    PluginOperationRepository.add_diagnostic(
        plugin_id=operation.plugin_id,
        stage=operation.stage,
        code="plugin-operation-failed",
        message=str(error),
        details={"exception": type(error).__name__},
        operation=operation,
    )


def _current_wheels(
    manager: PluginOverlayManager,
    *,
    excluding_plugin_id: str | None = None,
) -> tuple[Path, ...]:
    generation_id = manager.pointer("current")
    if generation_id is None:
        return ()
    artifacts = manager.generation_path(generation_id) / "artifacts"
    wheels = []
    for path in sorted(artifacts.glob("*.whl")):
        inspected = inspect_plugin_wheel(path)
        if inspected.manifest.plugin_id != excluding_plugin_id:
            wheels.append(path)
    return tuple(wheels)


def _build_source_wheel(source: Path, output: Path) -> Path:
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(output), str(source)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as error:
        raise PluginOperationError("plugin wheel build timed out") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error))[-4096:]
        raise PluginOperationError(detail) from error
    wheels = tuple(output.glob("*.whl"))
    if len(wheels) != 1:
        raise PluginOperationError("plugin build must produce exactly one wheel")
    return wheels[0]


def _generation_id() -> str:
    return f"gen-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:12]}"


def _activate_plugin_wheel(
    operation: PluginOperation,
    inspected: InspectedPluginWheel,
    *,
    provenance: Mapping[str, object],
) -> None:
    _cancel_if_requested(operation)
    _set_stage(operation, "resolving", 50)
    manager = plugin_overlay_manager()
    previous = manager.pointer("current")
    wheels = (
        *_current_wheels(manager, excluding_plugin_id=operation.plugin_id),
        inspected.path,
    )
    generation_id = _generation_id()
    plugin_generation_builder(manager).build(
        generation_id=generation_id,
        wheels=tuple(wheels),
        created_at=timezone.now().isoformat(),
        previous_generation=previous,
    )
    _cancel_if_requested(operation)
    _set_stage(
        operation,
        "activating",
        75,
        cancellation_allowed=False,
        input_generation=previous or "",
        output_generation=generation_id,
    )
    PluginControlHelper(manager).execute("activate", generation_id)
    existing = PluginInstallation.objects.filter(plugin_id=operation.plugin_id).first()
    desired_state = (
        existing.desired_state if existing is not None else PluginDesiredState.DISABLED
    )
    installation = PluginInstallationRepository.save_snapshot(
        plugin_id=inspected.manifest.plugin_id,
        distribution_id=inspected.manifest.distribution_id,
        installed_version=inspected.manifest.version,
        manifest=inspected.manifest.to_document(),
        provenance={**provenance, "artifactDigest": inspected.digest},
        lifecycle_impact=inspected.manifest.lifecycle.to_document(),
        desired_state=desired_state,
    )
    installation.active_generation = generation_id
    installation.last_known_good_generation = previous or ""
    installation.observed_state = PluginObservedState.RESTART_PENDING
    installation.save(
        update_fields=(
            "active_generation",
            "last_known_good_generation",
            "observed_state",
            "updated_at",
        )
    )
    _set_stage(
        operation,
        "restart-pending",
        85,
        status=PluginOperationStatus.RESTART_PENDING,
        cancellation_allowed=False,
    )


def _install_catalogue_wheel(operation: PluginOperation) -> None:
    data = operation.stage_data
    version_name = str(data.get("version", ""))
    entry = FirstPartyPluginCatalogue.load().get(operation.plugin_id)
    if entry is None:
        raise PluginOperationError("plugin is absent from the first-party catalogue")
    version = next(
        (item for item in entry.versions if item.version == version_name), None
    )
    if version is None or not version.published or not version.compatible:
        raise PluginOperationError("catalogue version is not currently installable")
    artifact = version.artifact_for()
    if artifact is None:
        raise PluginOperationError("catalogue has no plugin artifact for this platform")
    _set_stage(operation, "downloading", 10)
    manager = plugin_overlay_manager()
    with CatalogueWheelAcquirer(staging_root=manager.root / "acquisition").acquire(
        artifact,
        cancelled=lambda: PluginOperation.objects.filter(
            pk=operation.pk,
            cancellation_requested=True,
        ).exists(),
    ) as candidate:
        if candidate.inspected.manifest.plugin_id != operation.plugin_id:
            raise PluginOperationError(
                "downloaded manifest identity differs from the requested plugin"
            )
        _set_stage(operation, "verifying-artifact", 30)
        verify_catalogue_wheel(
            candidate.inspected,
            entry,
            expected_version=version_name,
            expected_artifact=artifact,
        )
        _activate_plugin_wheel(
            operation,
            candidate.inspected,
            provenance={
                **candidate.provenance_document(),
                "requestedRevision": version.revision,
                "resolvedRevision": version.resolved_commit,
                "version": version.version,
            },
        )


def _install_git_source(operation: PluginOperation) -> None:
    data = operation.stage_data
    repository = data.get("repository")
    revision = data.get("revision")
    if not isinstance(repository, str):
        raise PluginOperationError("repository is required")
    _set_stage(operation, "acquiring", 10)
    manager = plugin_overlay_manager()
    with GitPluginAcquirer(staging_root=manager.root / "acquisition").acquire(
        repository_url=repository,
        revision=revision if isinstance(revision, str) else None,
        trusted_code_acknowledged=data.get("trustedCodeAcknowledged") is True,
        cancelled=lambda: PluginOperation.objects.filter(
            pk=operation.pk,
            cancellation_requested=True,
        ).exists(),
    ) as candidate:
        if candidate.manifest.plugin_id != operation.plugin_id:
            raise PluginOperationError(
                "downloaded manifest identity differs from the requested plugin"
            )
        _cancel_if_requested(operation)
        _set_stage(operation, "building", 30)
        wheel = _build_source_wheel(
            candidate.checkout_path,
            candidate._temporary_root / "wheel",
        )
        inspected = inspect_plugin_wheel(wheel)
        if (
            inspected.manifest.plugin_id != candidate.manifest.plugin_id
            or inspected.manifest.distribution_id != candidate.manifest.distribution_id
            or inspected.manifest.version != candidate.manifest.version
        ):
            raise PluginAcquisitionError(
                "built wheel manifest differs from the inspected source manifest"
            )
        _activate_plugin_wheel(
            operation,
            inspected,
            provenance=candidate.provenance_document(),
        )


def _install_or_update(operation: PluginOperation) -> None:
    if operation.stage_data.get("sourceType") == "catalogue":
        _install_catalogue_wheel(operation)
    else:
        _install_git_source(operation)


def _runtime_record(plugin_id: str):
    from api.apps import PLUGIN_REGISTRY

    return PLUGIN_REGISTRY.get(plugin_id)


def _hot_lifecycle(operation: PluginOperation, *, enable: bool) -> None:
    installation = PluginInstallation.objects.get(plugin_id=operation.plugin_id)
    record = _runtime_record(operation.plugin_id)
    if record is None or record.plugin is None:
        raise PluginOperationError("plugin runtime is unavailable")
    impact = LifecycleImpact(operation.effective_lifecycle_impact)
    stateful = any(
        item.declaration.kind
        in {
            CapabilityKind.PROCESSING,
            CapabilityKind.MANAGED_RESOURCE,
            CapabilityKind.MANAGED_AUDIO_SOURCE,
        }
        for item in record.capabilities
    )
    lifecycle_method = "start" if enable else "stop"
    implements_hook = getattr(type(record.plugin), lifecycle_method) is not getattr(
        OpenCinemaPlugin, lifecycle_method
    )
    if stateful and not implements_hook:
        impact = LifecycleImpact.maximum(
            impact,
            LifecycleImpact.APPLICATION_RESTART,
        )
    operation.effective_lifecycle_impact = impact.value
    installation.desired_state = (
        PluginDesiredState.ENABLED if enable else PluginDesiredState.DISABLED
    )
    installation.update_version += 1
    if impact is not LifecycleImpact.HOT:
        installation.observed_state = PluginObservedState.RESTART_PENDING
        installation.save(
            update_fields=(
                "desired_state",
                "observed_state",
                "update_version",
                "updated_at",
            )
        )
        _set_stage(
            operation,
            "restart-pending",
            85,
            status=PluginOperationStatus.RESTART_PENDING,
            cancellation_allowed=False,
            effective_lifecycle_impact=impact.value,
        )
        return
    _set_stage(operation, "activating" if enable else "deactivating", 60)
    context = DistributionLifecycleContext(operation.plugin_id)
    result = record.plugin.start(context) if enable else record.plugin.stop(context)
    if (
        not isinstance(result, PluginRuntimeResult)
        or result.status is RuntimeStatus.FAILED
    ):
        raise PluginOperationError(f"plugin {lifecycle_method} hook failed")
    record.desired_state = (
        RuntimeDesiredState.ENABLED if enable else RuntimeDesiredState.DISABLED
    )
    record.state = (
        PluginLifecycleState.STARTED if enable else PluginLifecycleState.STOPPED
    )
    record.health = (
        PluginHealth.HEALTHY
        if result.status is RuntimeStatus.READY
        else PluginHealth.DEGRADED
    )
    installation.observed_state = (
        PluginObservedState.STARTED if enable else PluginObservedState.STOPPED
    )
    installation.aggregate_health = (
        PluginAggregateHealth.HEALTHY
        if result.status is RuntimeStatus.READY
        else PluginAggregateHealth.DEGRADED
    )
    installation.save(
        update_fields=(
            "desired_state",
            "observed_state",
            "aggregate_health",
            "update_version",
            "updated_at",
        )
    )
    _succeed(operation)


def _succeed(operation: PluginOperation) -> None:
    operation.status = PluginOperationStatus.SUCCEEDED
    operation.stage = "complete"
    operation.progress = 100
    operation.cancellation_allowed = False
    operation.completed_at = timezone.now()
    operation.save(
        update_fields=(
            "status",
            "stage",
            "progress",
            "cancellation_allowed",
            "completed_at",
            "updated_at",
        )
    )


def _uninstall(operation: PluginOperation) -> None:
    manager = plugin_overlay_manager()
    previous = manager.pointer("current")
    _set_stage(operation, "resolving", 35)
    wheels = _current_wheels(manager, excluding_plugin_id=operation.plugin_id)
    generation_id = _generation_id()
    plugin_generation_builder(manager).build(
        generation_id=generation_id,
        wheels=wheels,
        created_at=timezone.now().isoformat(),
        previous_generation=previous,
    )
    _set_stage(
        operation,
        "activating",
        70,
        cancellation_allowed=False,
        input_generation=previous or "",
        output_generation=generation_id,
    )
    PluginControlHelper(manager).execute("activate", generation_id)
    PluginUninstallRepository.uninstall(
        operation.plugin_id,
        delete_data=operation.stage_data.get("deleteData") is True,
    )
    _set_stage(
        operation,
        "restart-pending",
        85,
        status=PluginOperationStatus.RESTART_PENDING,
        cancellation_allowed=False,
    )


def execute_plugin_operation(operation_id: str) -> None:
    operation = PluginOperation.objects.get(pk=operation_id)
    if operation.status in TERMINAL_OPERATION_STATUSES:
        return
    try:
        _cancel_if_requested(operation)
        effective_kind = operation.kind
        if operation.kind == PluginOperationKind.RETRY:
            previous_id = operation.stage_data.get("retryOperationId")
            previous = PluginOperation.objects.get(pk=previous_id)
            if previous.status not in {
                PluginOperationStatus.FAILED,
                PluginOperationStatus.CANCELLED,
            }:
                raise PluginOperationError(
                    "only failed or cancelled operations can be retried"
                )
            effective_kind = previous.kind
            operation.stage_data = previous.stage_data
            operation.save(update_fields=("stage_data", "updated_at"))
        if effective_kind in {PluginOperationKind.INSTALL, PluginOperationKind.UPDATE}:
            _install_or_update(operation)
        elif effective_kind == PluginOperationKind.ENABLE:
            _hot_lifecycle(operation, enable=True)
        elif effective_kind == PluginOperationKind.DISABLE:
            _hot_lifecycle(operation, enable=False)
        elif effective_kind == PluginOperationKind.UNINSTALL:
            _uninstall(operation)
        elif effective_kind == PluginOperationKind.CLEANUP:
            _set_stage(operation, "cleanup", 50)
            PluginControlHelper(plugin_overlay_manager()).execute("cleanup")
            _succeed(operation)
        elif effective_kind == PluginOperationKind.ROLLBACK:
            _set_stage(operation, "rolling-back", 50, cancellation_allowed=False)
            current, previous = PluginControlHelper(plugin_overlay_manager()).execute(
                "rollback"
            )
            _set_stage(
                operation,
                "restart-pending",
                85,
                status=PluginOperationStatus.RESTART_PENDING,
                cancellation_allowed=False,
                input_generation=current,
                output_generation=previous,
            )
        else:
            raise PluginOperationError("unsupported plugin operation")
    except Exception as error:
        _fail(operation, error)


def finalize_startup_operations(registry) -> None:
    manager = plugin_overlay_manager()
    try:
        current = manager.pointer("current")
    except Exception:
        current = None
    operations = PluginOperation.objects.filter(
        status__in=(
            PluginOperationStatus.RESTART_PENDING,
            PluginOperationStatus.VERIFYING,
        )
    ).order_by("requested_at")
    for operation in operations:
        operation.status = PluginOperationStatus.VERIFYING
        operation.stage = "verifying"
        operation.progress = 92
        operation.save(update_fields=("status", "stage", "progress", "updated_at"))
        record = registry.get(operation.plugin_id)
        expects_absent = operation.kind == PluginOperationKind.UNINSTALL
        healthy = current == operation.output_generation and (
            (expects_absent and record is None)
            or (
                not expects_absent
                and record is not None
                and record.health.value in {"healthy", "degraded"}
            )
        )
        if healthy:
            installation = PluginInstallation.objects.filter(
                plugin_id=operation.plugin_id
            ).first()
            if installation is not None and not expects_absent:
                installation.observed_state = (
                    PluginObservedState.STARTED
                    if installation.desired_state == PluginDesiredState.ENABLED
                    else PluginObservedState.STOPPED
                )
                installation.aggregate_health = (
                    PluginAggregateHealth.HEALTHY
                    if record.health.value == "healthy"
                    else PluginAggregateHealth.DEGRADED
                )
                installation.save(
                    update_fields=(
                        "observed_state",
                        "aggregate_health",
                        "updated_at",
                    )
                )
            _succeed(operation)
            continue
        try:
            if operation.input_generation and current == operation.output_generation:
                PluginControlHelper(manager).execute("rollback")
        except Exception as rollback_error:
            _fail(
                operation,
                PluginOperationError(
                    f"health verification and rollback failed: {rollback_error}"
                ),
            )
        else:
            _fail(
                operation,
                PluginOperationError(
                    "candidate generation failed startup health verification; "
                    "the last-known-good pointer was restored"
                ),
            )
