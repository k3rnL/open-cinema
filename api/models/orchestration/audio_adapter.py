from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ManagedAudioAdapterQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_staff or user.is_superuser:
            return self
        return self.filter(owner=user)


class ManagedAudioAdapter(models.Model):
    """Persistent desired state for one endpoint-producing runtime resource."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_audio_adapters",
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=64)
    schema_version = models.PositiveIntegerField(default=1)
    configuration = models.JSONField(default=dict)
    enabled = models.BooleanField(default=False)
    restart_generation = models.PositiveBigIntegerField(default=0)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ManagedAudioAdapterQuerySet.as_manager()

    class Meta:
        ordering = ("name", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("owner", "name"),
                name="api_adapter_owner_name_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="api_adapter_name_nonempty",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind=""),
                name="api_adapter_kind_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version=1),
                name="api_adapter_schema_supported",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_adapter_version_positive",
            ),
        )
        indexes = (
            models.Index(fields=("owner", "kind"), name="api_adapter_owner_kind_idx"),
            models.Index(fields=("enabled",), name="api_adapter_enabled_idx"),
        )

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.configuration, dict):
            raise ValidationError({"configuration": "Configuration must be an object."})

    def can_view(self, user) -> bool:
        return bool(
            getattr(user, "is_authenticated", False)
            and (user.is_staff or user.is_superuser or user.pk == self.owner_id)
        )

    def can_change(self, user) -> bool:
        return self.can_view(user)


class AudioAdapterLifecycle(models.TextChoices):
    STOPPED = "stopped", "Stopped"
    STARTING = "starting", "Starting"
    READY = "ready", "Ready"
    STOPPING = "stopping", "Stopping"
    BACKOFF = "backoff", "Backoff"
    ERROR = "error", "Error"


class AudioAdapterHealth(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    HEALTHY = "healthy", "Healthy"
    UNHEALTHY = "unhealthy", "Unhealthy"


class ManagedAudioAdapterRuntimeState(models.Model):
    """Observed adapter state written only by the active orchestrator."""

    adapter = models.OneToOneField(
        ManagedAudioAdapter,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="runtime_state",
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=AudioAdapterLifecycle.choices,
        default=AudioAdapterLifecycle.STOPPED,
    )
    health = models.CharField(
        max_length=16,
        choices=AudioAdapterHealth.choices,
        default=AudioAdapterHealth.UNKNOWN,
    )
    process_id = models.PositiveIntegerField(null=True, blank=True)
    runtime_generation = models.PositiveBigIntegerField(default=0)
    configuration_digest = models.CharField(max_length=64, blank=True)
    expected_node_name = models.CharField(max_length=255, blank=True)
    runtime_key = models.CharField(max_length=256, null=True, blank=True)
    progress = models.JSONField(default=dict, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("adapter_id",)
        indexes = (
            models.Index(fields=("lifecycle", "retry_at"), name="api_adapter_lifecycle_idx"),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if not isinstance(self.progress, dict):
            errors["progress"] = "Progress must be an object."
        if not isinstance(self.last_error, dict):
            errors["last_error"] = "Last error must be an object."
        if errors:
            raise ValidationError(errors)
