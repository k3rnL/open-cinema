from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class LogicalEndpointDirection(models.TextChoices):
    INPUT = "input", "Input"
    OUTPUT = "output", "Output"


class LogicalEndpointQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_staff or user.is_superuser:
            return self
        return self.filter(owner=user)


class LogicalEndpoint(models.Model):
    """Durable user identity for transient WirePlumber endpoint candidates."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logical_audio_endpoints",
    )
    direction = models.CharField(
        max_length=16,
        choices=LogicalEndpointDirection.choices,
    )
    selector = models.JSONField(default=dict)
    tags = models.JSONField(default=list, blank=True)
    groups = models.JSONField(default=list, blank=True)
    policy_metadata = models.JSONField(default=dict, blank=True)
    explicit_binding = models.JSONField(null=True, blank=True)
    last_known_summary = models.JSONField(default=dict, blank=True)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LogicalEndpointQuerySet.as_manager()

    class Meta:
        ordering = ("name", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("owner", "name"),
                name="api_logical_endpoint_owner_name_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_logical_endpoint_version_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="api_logical_endpoint_name_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("owner", "direction"),
                name="api_endpoint_owner_dir_idx",
            ),
            models.Index(
                fields=("update_version",),
                name="api_endpoint_update_ver_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        for field in ("selector", "policy_metadata", "last_known_summary"):
            if not isinstance(getattr(self, field), dict):
                errors[field] = "Value must be an object."
        if self.explicit_binding is not None and not isinstance(
            self.explicit_binding, dict
        ):
            errors["explicit_binding"] = "Explicit binding must be an object or null."
        for field in ("tags", "groups"):
            values = getattr(self, field)
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                errors[field] = "Value must be an ordered list of unique non-empty strings."
        if errors:
            raise ValidationError(errors)

    def can_view(self, user) -> bool:
        return bool(
            getattr(user, "is_authenticated", False)
            and (user.is_staff or user.is_superuser or user.pk == self.owner_id)
        )

    def can_change(self, user) -> bool:
        return self.can_view(user)

    def __str__(self) -> str:
        return f"{self.name} ({self.direction})"
