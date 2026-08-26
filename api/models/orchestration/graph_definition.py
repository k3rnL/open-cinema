from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class GraphDefinitionKind(models.TextChoices):
    GRAPH = "graph", "Graph"
    SUBGRAPH = "subgraph", "Subgraph"


class GraphDefinitionQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_staff or user.is_superuser:
            return self
        return self.filter(owner=user)


class GraphDefinition(models.Model):
    """Stable identity and ownership surrounding immutable graph revisions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=16,
        choices=GraphDefinitionKind.choices,
        default=GraphDefinitionKind.GRAPH,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audio_graph_definitions",
    )
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    objects = GraphDefinitionQuerySet.as_manager()

    class Meta:
        ordering = ("name", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("owner", "name"),
                name="api_graph_definition_owner_name_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="api_graph_definition_name_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("owner", "kind"),
                name="api_graph_owner_kind_idx",
            ),
            models.Index(
                fields=("archived_at",),
                name="api_graph_archived_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.labels, dict):
            raise ValidationError({"labels": "Labels must be an object."})
        invalid = [
            key
            for key, value in self.labels.items()
            if not isinstance(key, str) or not isinstance(value, str)
        ]
        if invalid:
            raise ValidationError(
                {"labels": "Label names and values must all be strings."}
            )

    def can_view(self, user) -> bool:
        return bool(
            getattr(user, "is_authenticated", False)
            and (user.is_staff or user.is_superuser or user.pk == self.owner_id)
        )

    def can_change(self, user) -> bool:
        return self.can_view(user)

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"
