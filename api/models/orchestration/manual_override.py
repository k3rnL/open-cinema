from __future__ import annotations

import math
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ManualOverrideScope(models.TextChoices):
    ENDPOINT = "endpoint", "Endpoint selection"
    SCENE = "scene", "Scene selection"
    VOLUME = "volume", "Volume"
    MUTE = "mute", "Mute"
    ROUTE = "route", "Route selection"
    GRAPH_PARAMETER = "graph_parameter", "Graph parameter"


class ManualOverrideQuerySet(models.QuerySet):
    def active_at(self, moment=None):
        moment = moment or timezone.now()
        return self.filter(
            starts_at__lte=moment,
            cancelled_at__isnull=True,
        ).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=moment))


class ManualOverride(models.Model):
    """One explicit, scoped, optionally expiring resolver input."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope_type = models.CharField(max_length=32, choices=ManualOverrideScope.choices)
    scope_id = models.CharField(max_length=255)
    value = models.JSONField()
    priority = models.IntegerField(default=100)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_audio_overrides",
    )
    reason = models.TextField()
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_audio_overrides",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ManualOverrideQuerySet.as_manager()

    class Meta:
        ordering = ("-priority", "starts_at", "id")
        constraints = (
            models.CheckConstraint(
                condition=(
                    models.Q(expires_at__isnull=True)
                    | models.Q(expires_at__gt=models.F("starts_at"))
                ),
                name="api_manual_override_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(cancelled_at__isnull=True, cancelled_by__isnull=True)
                    | models.Q(cancelled_at__isnull=False, cancelled_by__isnull=False)
                ),
                name="api_manual_override_cancellation_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(scope_id=""),
                name="api_manual_override_scope_nonempty",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="api_manual_override_reason_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("scope_type", "scope_id", "priority"),
                name="api_override_scope_prio_idx",
            ),
            models.Index(
                fields=("starts_at", "expires_at", "cancelled_at"),
                name="api_override_active_window_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if not self.scope_id:
            errors["scope_id"] = "Scope identity must not be empty."
        if not isinstance(self.reason, str) or not self.reason.strip():
            errors["reason"] = "A reason is required for every manual override."
        if self.expires_at is not None and self.expires_at <= self.starts_at:
            errors["expires_at"] = "Expiry must be after the override start."
        cancellation_is_partial = (self.cancelled_at is None) != (
            self.cancelled_by_id is None
        )
        if cancellation_is_partial:
            errors["cancelled_at"] = "Cancellation time and actor must be set together."

        if self.scope_type == ManualOverrideScope.MUTE:
            if not isinstance(self.value, bool):
                errors["value"] = "Mute override value must be a boolean."
        elif self.scope_type == ManualOverrideScope.VOLUME:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, (int, float))
                or not math.isfinite(self.value)
                or not 0 <= self.value <= 1
            ):
                errors["value"] = "Volume override value must be between 0 and 1."
        elif self.scope_type in {
            ManualOverrideScope.ENDPOINT,
            ManualOverrideScope.SCENE,
            ManualOverrideScope.ROUTE,
        }:
            if not isinstance(self.value, str) or not self.value:
                errors["value"] = "Selection override value must be a non-empty string."
        elif self.scope_type == ManualOverrideScope.GRAPH_PARAMETER:
            if not isinstance(self.value, dict) or "value" not in self.value:
                errors["value"] = (
                    "Graph-parameter override value must be an object containing 'value'."
                )
        if errors:
            raise ValidationError(errors)

    def is_active(self, moment=None) -> bool:
        moment = moment or timezone.now()
        return bool(
            self.starts_at <= moment
            and self.cancelled_at is None
            and (self.expires_at is None or moment < self.expires_at)
        )

    def __str__(self) -> str:
        return f"{self.scope_type}:{self.scope_id} priority={self.priority}"
