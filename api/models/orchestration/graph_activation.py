from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .graph_definition import GraphDefinitionKind
from .graph_revision import GraphRevisionState


class GraphActivation(models.Model):
    """The versioned desired revision and bindings selected for one graph."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.OneToOneField(
        "api.GraphDefinition",
        on_delete=models.CASCADE,
        related_name="activation",
    )
    revision = models.ForeignKey(
        "api.GraphRevision",
        on_delete=models.PROTECT,
        related_name="activations",
    )
    enabled = models.BooleanField(default=True)
    parameter_bindings = models.JSONField(default=dict, blank=True)
    scene_bindings = models.JSONField(default=dict, blank=True)
    desired_state_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    activated_at = models.DateTimeField()

    class Meta:
        constraints = (
            models.CheckConstraint(
                condition=models.Q(desired_state_version__gte=1),
                name="api_graph_activation_version_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("revision",),
                name="api_activation_revision_idx",
            ),
            models.Index(
                fields=("desired_state_version",),
                name="api_activation_version_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.definition_id and self.definition.kind != GraphDefinitionKind.GRAPH:
            errors["definition"] = "Only top-level graph definitions can be activated."
        if self.revision_id:
            if self.revision.definition_id != self.definition_id:
                errors["revision"] = "The revision belongs to another graph definition."
            elif self.revision.state != GraphRevisionState.PUBLISHED:
                errors["revision"] = "Only a published graph revision can be activated."
        for field in ("parameter_bindings", "scene_bindings"):
            if not isinstance(getattr(self, field), dict):
                errors[field] = "Bindings must be an object."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        state = "enabled" if self.enabled else "disabled"
        return (
            f"{self.definition.name} → r{self.revision.revision_number} "
            f"({state}, desired v{self.desired_state_version})"
        )
