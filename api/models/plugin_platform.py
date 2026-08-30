from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PluginDesiredState(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"


class PluginObservedState(models.TextChoices):
    DISCOVERED = "discovered", "Discovered"
    AVAILABLE = "available", "Available"
    STARTED = "started", "Started"
    STOPPED = "stopped", "Stopped"
    INCOMPATIBLE = "incompatible", "Incompatible"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected"
    RESTART_PENDING = "restart-pending", "Restart pending"
    UNINSTALLED = "uninstalled", "Uninstalled"


class PluginAggregateHealth(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    HEALTHY = "healthy", "Healthy"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"
    INCOMPATIBLE = "incompatible", "Incompatible"
    REJECTED = "rejected", "Rejected"


class PluginOperationKind(models.TextChoices):
    INSTALL = "install", "Install"
    ENABLE = "enable", "Enable"
    DISABLE = "disable", "Disable"
    UPDATE = "update", "Update"
    UNINSTALL = "uninstall", "Uninstall"
    RETRY = "retry", "Retry"
    CLEANUP = "cleanup", "Cleanup"
    ROLLBACK = "rollback", "Rollback"


class PluginOperationStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    RUNNING = "running", "Running"
    RESTART_PENDING = "restart-pending", "Restart pending"
    VERIFYING = "verifying", "Verifying"
    ROLLING_BACK = "rolling-back", "Rolling back"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class PluginInstallation(models.Model):
    plugin_id = models.CharField(max_length=128, primary_key=True)
    distribution_id = models.CharField(max_length=128)
    installed_version = models.CharField(max_length=64)
    manifest_snapshot = models.JSONField(default=dict)
    provenance_snapshot = models.JSONField(default=dict)
    desired_state = models.CharField(
        max_length=16,
        choices=PluginDesiredState.choices,
        default=PluginDesiredState.DISABLED,
    )
    observed_state = models.CharField(
        max_length=24,
        choices=PluginObservedState.choices,
        default=PluginObservedState.DISCOVERED,
    )
    aggregate_health = models.CharField(
        max_length=16,
        choices=PluginAggregateHealth.choices,
        default=PluginAggregateHealth.UNKNOWN,
    )
    lifecycle_impact = models.JSONField(default=dict)
    active_generation = models.CharField(max_length=128, blank=True)
    last_known_good_generation = models.CharField(max_length=128, blank=True)
    retained_data = models.BooleanField(default=False)
    update_version = models.PositiveBigIntegerField(default=1)
    installed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plugin_id",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(plugin_id=""),
                name="api_plugin_install_id_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_plugin_install_version_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("desired_state", "observed_state"),
                name="api_plugin_install_state_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        for field_name in (
            "manifest_snapshot",
            "provenance_snapshot",
            "lifecycle_impact",
        ):
            if not isinstance(getattr(self, field_name), dict):
                raise ValidationError({field_name: "Value must be an object."})


class PluginCapabilityState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    capability_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=32)
    contract_version = models.PositiveIntegerField(default=1)
    declaration_snapshot = models.JSONField(default=dict)
    schema_metadata = models.JSONField(default=dict)
    observed_state = models.CharField(
        max_length=24,
        choices=PluginObservedState.choices,
        default=PluginObservedState.DISCOVERED,
    )
    health = models.CharField(
        max_length=16,
        choices=PluginAggregateHealth.choices,
        default=PluginAggregateHealth.UNKNOWN,
    )
    diagnostics = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plugin_id", "capability_id")
        constraints = (
            models.UniqueConstraint(
                fields=("plugin_id", "capability_id"),
                name="api_plugin_capability_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(contract_version__gte=1),
                name="api_plugin_capability_version_positive",
            ),
        )


class PluginOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=PluginOperationKind.choices)
    status = models.CharField(
        max_length=24,
        choices=PluginOperationStatus.choices,
        default=PluginOperationStatus.REQUESTED,
    )
    stage = models.CharField(max_length=64, default="requested")
    idempotency_key = models.CharField(max_length=256, unique=True)
    concurrency_token = models.UUIDField(default=uuid.uuid4, editable=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="plugin_operations",
        null=True,
        blank=True,
    )
    effective_lifecycle_impact = models.CharField(max_length=24, default="hot")
    progress = models.PositiveSmallIntegerField(default=0)
    diagnostics = models.JSONField(default=list)
    input_generation = models.CharField(max_length=128, blank=True)
    output_generation = models.CharField(max_length=128, blank=True)
    cancellation_requested = models.BooleanField(default=False)
    cancellation_allowed = models.BooleanField(default=True)
    stage_data = models.JSONField(default=dict)
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        indexes = (
            models.Index(
                fields=("status", "requested_at"),
                name="api_plugin_operation_state_idx",
            ),
            models.Index(
                fields=("plugin_id", "requested_at"),
                name="api_plugin_operation_owner_idx",
            ),
        )
        constraints = (
            models.CheckConstraint(
                condition=models.Q(progress__gte=0, progress__lte=100),
                name="api_plugin_operation_progress_range",
            ),
        )


class PluginDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    collection = models.CharField(max_length=128)
    document_id = models.CharField(max_length=128)
    schema_id = models.CharField(max_length=256)
    schema_version = models.PositiveIntegerField(default=1)
    document = models.JSONField(default=dict)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plugin_id", "collection", "document_id")
        constraints = (
            models.UniqueConstraint(
                fields=("plugin_id", "collection", "document_id"),
                name="api_plugin_document_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="api_plugin_document_schema_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_plugin_document_version_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("plugin_id", "collection", "updated_at"),
                name="api_plugin_document_query_idx",
            ),
        )


class PluginInstance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    capability_id = models.CharField(max_length=128)
    instance_id = models.CharField(max_length=128)
    display_name = models.CharField(max_length=160)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="plugin_instances",
        null=True,
        blank=True,
    )
    configuration_version = models.PositiveIntegerField(default=1)
    configuration = models.JSONField(default=dict)
    desired_state = models.CharField(
        max_length=16,
        choices=PluginDesiredState.choices,
        default=PluginDesiredState.DISABLED,
    )
    observed_state = models.CharField(
        max_length=24,
        choices=PluginObservedState.choices,
        default=PluginObservedState.STOPPED,
    )
    runtime_facts = models.JSONField(default=dict)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plugin_id", "capability_id", "display_name", "instance_id")
        constraints = (
            models.UniqueConstraint(
                fields=("plugin_id", "capability_id", "instance_id"),
                name="api_plugin_instance_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(configuration_version__gte=1),
                name="api_plugin_instance_schema_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_plugin_instance_version_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("plugin_id", "capability_id", "desired_state"),
                name="api_plugin_instance_state_idx",
            ),
        )


class PluginSecretReference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    secret_id = models.CharField(max_length=128)
    storage_key = models.CharField(max_length=64, unique=True)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plugin_id", "secret_id")
        constraints = (
            models.UniqueConstraint(
                fields=("plugin_id", "secret_id"),
                name="api_plugin_secret_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_plugin_secret_version_positive",
            ),
        )


class PluginDiagnosticRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plugin_id = models.CharField(max_length=128)
    capability_id = models.CharField(max_length=128, blank=True)
    operation = models.ForeignKey(
        PluginOperation,
        on_delete=models.SET_NULL,
        related_name="diagnostic_records",
        null=True,
        blank=True,
    )
    stage = models.CharField(max_length=64)
    code = models.CharField(max_length=128)
    message = models.CharField(max_length=2048)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(
                fields=("plugin_id", "created_at"),
                name="api_plugin_diag_owner_idx",
            ),
        )
