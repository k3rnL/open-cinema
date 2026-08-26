from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .orchestration_event import OrchestrationEventSeverity


class DiagnosticRecord(models.Model):
    """Bounded, high-frequency diagnostic evidence; never desired state."""

    sequence = models.BigAutoField(primary_key=True)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    category = models.CharField(max_length=128)
    severity = models.CharField(
        max_length=16,
        choices=OrchestrationEventSeverity.choices,
        default=OrchestrationEventSeverity.DEBUG,
    )
    payload = models.JSONField(default=dict)
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("sequence",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(category=""),
                name="api_diagnostic_category_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("category", "captured_at"),
                name="api_diag_category_time_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Diagnostic payload must be an object."})


class RuntimeProjection(models.Model):
    """A persisted UI projection, distinct from an authoritative runtime snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    projection_type = models.CharField(max_length=64)
    subject_key = models.CharField(max_length=256)
    world_generation = models.PositiveBigIntegerField()
    world_sequence = models.PositiveBigIntegerField()
    payload = models.JSONField(default=dict)
    is_current = models.BooleanField(default=True)
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("projection_type", "subject_key", "-created_at")
        constraints = (
            models.UniqueConstraint(
                fields=("projection_type", "subject_key"),
                condition=models.Q(is_current=True),
                name="api_runtime_projection_current_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(world_generation__gte=1),
                name="api_runtime_projection_generation_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(projection_type=""),
                name="api_runtime_projection_type_nonempty",
            ),
            models.CheckConstraint(
                condition=~models.Q(subject_key=""),
                name="api_runtime_projection_subject_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("is_current", "created_at"),
                name="api_runtime_current_time_idx",
            ),
            models.Index(
                fields=("projection_type", "created_at"),
                name="api_runtime_type_time_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Projection payload must be an object."})
