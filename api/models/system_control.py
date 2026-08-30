from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SystemControlAction(models.TextChoices):
    RESTART_OPEN_CINEMA = "restart-open-cinema", "Restart Open Cinema"
    RESTART_ORCHESTRATOR = "restart-orchestrator", "Restart audio orchestrator"
    REBOOT_APPLIANCE = "reboot-appliance", "Reboot appliance"


class SystemControlStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    EXECUTING = "executing", "Executing"
    RECONNECTING = "reconnecting", "Reconnecting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class SystemControlOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    action = models.CharField(max_length=32, choices=SystemControlAction.choices)
    target_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=SystemControlStatus.choices,
        default=SystemControlStatus.REQUESTED,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="system_control_operations",
    )
    initial_boot_id = models.CharField(max_length=64, blank=True)
    initial_service_instance = models.CharField(max_length=128, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_detail = models.CharField(max_length=512, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        indexes = (
            models.Index(
                fields=("action", "status", "requested_at"),
                name="api_sysctl_action_state_idx",
            ),
        )
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(target_id=""),
                name="api_system_control_target_nonempty",
            ),
        )

    def clean(self) -> None:
        super().clean()
        expected = {
            SystemControlAction.RESTART_OPEN_CINEMA: "open-cinema",
            SystemControlAction.RESTART_ORCHESTRATOR: "open-cinema-orchestrator",
            SystemControlAction.REBOOT_APPLIANCE: "appliance",
        }.get(self.action)
        if expected is not None and self.target_id != expected:
            raise ValidationError({"target_id": "Target does not match the allowlisted action."})
