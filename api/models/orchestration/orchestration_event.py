from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class OrchestrationEventSeverity(models.TextChoices):
    DEBUG = "debug", "Debug"
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


class OrchestrationEvent(models.Model):
    sequence = models.BigAutoField(primary_key=True)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    correlation_id = models.UUIDField(db_index=True)
    graph_definition = models.ForeignKey(
        "api.GraphDefinition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orchestration_events",
    )
    event_type = models.CharField(max_length=128)
    severity = models.CharField(
        max_length=16,
        choices=OrchestrationEventSeverity.choices,
        default=OrchestrationEventSeverity.INFO,
    )
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(event_type=""),
                name="api_orchestration_event_type_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("event_type", "occurred_at"),
                name="api_orch_event_type_time_idx",
            ),
            models.Index(
                fields=("graph_definition", "sequence"),
                name="api_orch_event_graph_seq_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Audit payload must be an object."})
