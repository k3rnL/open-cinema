from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from api.models import (
    OrchestrationEvent,
    RuntimeProjection,
    SystemControlAction,
    SystemControlOperation,
    SystemControlStatus,
)

from .probes import boot_id


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    action: str
    target_id: str
    public_id: str
    label: str
    href: str


_ACTIONS = {
    SystemControlAction.RESTART_OPEN_CINEMA: ActionDefinition(
        SystemControlAction.RESTART_OPEN_CINEMA,
        "open-cinema",
        "restart",
        "Restart Open Cinema",
        "/api/system/v1/components/open-cinema/actions/restart",
    ),
    SystemControlAction.RESTART_ORCHESTRATOR: ActionDefinition(
        SystemControlAction.RESTART_ORCHESTRATOR,
        "open-cinema-orchestrator",
        "restart",
        "Restart audio orchestrator",
        "/api/system/v1/components/open-cinema-orchestrator/actions/restart",
    ),
    SystemControlAction.REBOOT_APPLIANCE: ActionDefinition(
        SystemControlAction.REBOOT_APPLIANCE,
        "appliance",
        "reboot",
        "Reboot appliance",
        "/api/system/v1/actions/reboot",
    ),
}
_COMPONENT_ACTIONS = {
    "open-cinema": SystemControlAction.RESTART_OPEN_CINEMA,
    "open-cinema-orchestrator": SystemControlAction.RESTART_ORCHESTRATOR,
}
_IN_PROGRESS = (
    SystemControlStatus.REQUESTED,
    SystemControlStatus.EXECUTING,
    SystemControlStatus.RECONNECTING,
)
_HELPER_CACHE: dict[str, tuple[float, bool, str | None]] = {}
_HELPER_CACHE_SECONDS = 10.0


def helper_path() -> Path:
    return Path(
        getattr(
            settings,
            "OPEN_CINEMA_SYSTEM_CONTROL_HELPER",
            "/usr/local/libexec/open-cinema-system-control",
        )
    )


def _sudo_path() -> Path:
    return Path(getattr(settings, "OPEN_CINEMA_SUDO", "/usr/bin/sudo"))


def service_instance_marker() -> str:
    invocation = os.environ.get("INVOCATION_ID", "").strip()
    if invocation:
        return f"systemd:{invocation[:96]}"
    parent = os.getppid()
    try:
        fields = Path(f"/proc/{parent}/stat").read_text(encoding="utf-8").split()
        start_ticks = fields[21]
    except (OSError, IndexError):
        start_ticks = "unknown"
    return f"parent:{parent}:{start_ticks}"


def _helper_check(action: str) -> tuple[bool, str | None]:
    now = time.monotonic()
    result: tuple[bool, str | None]
    cached = _HELPER_CACHE.get(action)
    if cached and now - cached[0] < _HELPER_CACHE_SECONDS:
        return cached[1], cached[2]
    path = helper_path()
    sudo = _sudo_path()
    try:
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            result = (False, "control helper ownership or permissions are unsafe")
        elif not os.access(path, os.X_OK) or not sudo.is_file():
            result = (False, "control helper or sudo is unavailable")
        else:
            check = subprocess.run(
                [str(sudo), "-n", str(path), "--check", action],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
            result = (
                (True, None)
                if check.returncode == 0
                else (False, "host authorization is not installed")
            )
    except (OSError, subprocess.SubprocessError):
        result = (False, "control helper is unavailable")
    _HELPER_CACHE[action] = (now, result[0], result[1])
    return result


def _token(definition: ActionDefinition) -> str:
    try:
        current_boot = boot_id()
    except (OSError, ValueError):
        current_boot = "unknown"
    return signing.dumps(
        {"action": definition.action, "bootId": current_boot},
        salt="open-cinema-system-control-v1",
        compress=True,
    )


def action_document(action: str) -> dict[str, object]:
    definition = _ACTIONS[action]
    available, reason = _helper_check(action)
    return {
        "id": definition.public_id,
        "label": definition.label,
        "available": available,
        "reason": reason,
        "actionToken": _token(definition) if available else None,
        "method": "POST",
        "href": definition.href,
    }


def component_action_documents(component_id: str) -> list[dict[str, object]]:
    action = _COMPONENT_ACTIONS.get(component_id)
    return [action_document(action)] if action is not None else []


def appliance_action_documents() -> list[dict[str, object]]:
    return [action_document(SystemControlAction.REBOOT_APPLIANCE)]


def _validate_token(definition: ActionDefinition, token: object) -> None:
    if not isinstance(token, str) or not token:
        raise ValueError("actionToken is required")
    try:
        payload = signing.loads(
            token,
            salt="open-cinema-system-control-v1",
            max_age=600,
        )
    except signing.BadSignature as error:
        raise ValueError("actionToken is invalid or expired") from error
    try:
        current_boot = boot_id()
    except (OSError, ValueError):
        current_boot = "unknown"
    if payload != {"action": definition.action, "bootId": current_boot}:
        raise ValueError("actionToken is stale")


def _audit(operation: SystemControlOperation, event_type: str) -> None:
    OrchestrationEvent.objects.create(
        correlation_id=operation.correlation_id,
        event_type=event_type,
        payload={
            "operationId": str(operation.pk),
            "action": operation.action,
            "targetId": operation.target_id,
            "status": operation.status,
            "actorId": str(operation.requested_by_id),
            **({"errorCode": operation.error_code} if operation.error_code else {}),
        },
    )


def _initial_boot_id() -> str:
    try:
        return boot_id()
    except (OSError, ValueError):
        return ""


def request_action(*, action: str, action_token: object, user) -> SystemControlOperation:
    if not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Only staff administrators may control the appliance.")
    definition = _ACTIONS.get(action)
    if definition is None:
        raise ValueError("The requested appliance action is not allowlisted.")
    available, reason = _helper_check(action)
    if not available:
        raise PermissionDenied(reason or "This appliance action is unavailable.")
    _validate_token(definition, action_token)

    with transaction.atomic():
        existing = (
            SystemControlOperation.objects.select_for_update()
            .filter(action=action, status__in=_IN_PROGRESS)
            .first()
        )
        if existing is not None:
            return existing
        operation = SystemControlOperation(
            action=action,
            target_id=definition.target_id,
            status=SystemControlStatus.REQUESTED,
            requested_by=user,
            initial_boot_id=_initial_boot_id(),
            initial_service_instance=service_instance_marker(),
        )
        operation.full_clean()
        operation.save()
        _audit(operation, "system-control.requested")

    try:
        result = subprocess.run(
            [str(_sudo_path()), "-n", str(helper_path()), action],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr.strip() or result.stdout.strip() or "control helper failed")[:512]
            )
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        operation.status = SystemControlStatus.FAILED
        operation.error_code = "helper-invocation-failed"
        operation.error_detail = str(error)[:512]
        operation.completed_at = timezone.now()
        operation.save(
            update_fields=[
                "status",
                "error_code",
                "error_detail",
                "completed_at",
                "updated_at",
            ]
        )
        _audit(operation, "system-control.failed")
        return operation

    operation.status = (
        SystemControlStatus.EXECUTING
        if action == SystemControlAction.RESTART_ORCHESTRATOR
        else SystemControlStatus.RECONNECTING
    )
    operation.save(update_fields=["status", "updated_at"])
    _audit(operation, "system-control.accepted")
    return operation


def refresh_operation(operation: SystemControlOperation) -> SystemControlOperation:
    if operation.status not in _IN_PROGRESS:
        return operation
    succeeded = False
    if operation.action == SystemControlAction.REBOOT_APPLIANCE:
        succeeded = bool(
            operation.initial_boot_id and _initial_boot_id() != operation.initial_boot_id
        )
    elif operation.action == SystemControlAction.RESTART_OPEN_CINEMA:
        succeeded = service_instance_marker() != operation.initial_service_instance
    elif operation.action == SystemControlAction.RESTART_ORCHESTRATOR:
        succeeded = RuntimeProjection.objects.filter(
            is_current=True,
            projection_type__in=("health", "orchestration-health"),
            observed_at__gt=operation.requested_at,
            payload__ready=True,
        ).exists()

    if succeeded:
        operation.status = SystemControlStatus.SUCCEEDED
        operation.completed_at = timezone.now()
        operation.save(update_fields=["status", "completed_at", "updated_at"])
        _audit(operation, "system-control.succeeded")
    elif timezone.now() - operation.requested_at > timedelta(seconds=90):
        operation.status = SystemControlStatus.FAILED
        operation.error_code = "confirmation-timeout"
        operation.error_detail = "Fresh healthy state was not observed within 90 seconds."
        operation.completed_at = timezone.now()
        operation.save(
            update_fields=[
                "status",
                "error_code",
                "error_detail",
                "completed_at",
                "updated_at",
            ]
        )
        _audit(operation, "system-control.failed")
    return operation


def operation_document(operation: SystemControlOperation) -> dict[str, object]:
    operation = refresh_operation(operation)
    return {
        "id": str(operation.pk),
        "correlationId": str(operation.correlation_id),
        "action": operation.action,
        "targetId": operation.target_id,
        "status": operation.status,
        "error": (
            {"code": operation.error_code, "detail": operation.error_detail}
            if operation.error_code
            else None
        ),
        "requestedAt": operation.requested_at.isoformat().replace("+00:00", "Z"),
        "updatedAt": operation.updated_at.isoformat().replace("+00:00", "Z"),
        "completedAt": (
            operation.completed_at.isoformat().replace("+00:00", "Z")
            if operation.completed_at
            else None
        ),
        "links": {"self": f"/api/system/v1/operations/{operation.pk}"},
    }
