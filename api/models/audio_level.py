from __future__ import annotations

import math
import uuid

from django.core.exceptions import ValidationError
from django.db import models


def _validate_level(value: float, field: str = "level") -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError({field: "Level must be a number between zero and one."})
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ValidationError({field: "Level must be between zero and one inclusive."})


class MasterAudioLevel(models.Model):
    """The appliance-wide persistent output factor; exactly one row may exist."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    level = models.FloatField(default=1.0)
    muted = models.BooleanField(default=False)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = (
            models.CheckConstraint(condition=models.Q(id=1), name="api_master_audio_singleton"),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_master_audio_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(level__gte=0.0, level__lte=1.0),
                name="api_master_audio_level_range",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if self.pk != 1:
            raise ValidationError({"id": "The master audio singleton identifier is one."})
        _validate_level(self.level)


class EndpointAudioLevel(models.Model):
    """A durable level preference keyed only by logical endpoint identity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.OneToOneField(
        "api.LogicalEndpoint",
        on_delete=models.CASCADE,
        related_name="audio_level",
    )
    level = models.FloatField(default=1.0)
    muted = models.BooleanField(default=False)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = (
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_endpoint_audio_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(level__gte=0.0, level__lte=1.0),
                name="api_endpoint_audio_level_range",
            ),
        )

    def clean(self) -> None:
        super().clean()
        _validate_level(self.level)
