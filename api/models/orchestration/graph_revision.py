from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.orchestration.graph_documents import graph_content_digest


class GraphRevisionState(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class GraphRevision(models.Model):
    """A CAS-edited draft that becomes immutable when published."""

    IMMUTABLE_FIELDS = (
        "definition_id",
        "schema_version",
        "revision_number",
        "state",
        "author_id",
        "content",
        "content_digest",
        "validation_summary",
        "update_version",
        "created_at",
        "published_at",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(
        "api.GraphDefinition",
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    schema_version = models.PositiveIntegerField(default=1)
    revision_number = models.PositiveIntegerField()
    state = models.CharField(
        max_length=16,
        choices=GraphRevisionState.choices,
        default=GraphRevisionState.DRAFT,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_audio_graph_revisions",
    )
    content = models.JSONField()
    content_digest = models.CharField(max_length=64, editable=False)
    validation_summary = models.JSONField(default=dict)
    update_version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("definition_id", "revision_number")
        constraints = (
            models.UniqueConstraint(
                fields=("definition", "revision_number"),
                name="api_graph_revision_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="api_graph_revision_schema_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(revision_number__gte=1),
                name="api_graph_revision_number_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(update_version__gte=1),
                name="api_graph_revision_update_version_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(content_digest=""),
                name="api_graph_revision_digest_nonempty",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state=GraphRevisionState.DRAFT, published_at__isnull=True)
                    | models.Q(
                        state=GraphRevisionState.PUBLISHED,
                        published_at__isnull=False,
                    )
                ),
                name="api_graph_revision_published_timestamp",
            ),
        )
        indexes = (
            models.Index(
                fields=("definition", "state", "revision_number"),
                name="api_graph_revision_state_idx",
            ),
            models.Index(
                fields=("content_digest",),
                name="api_graph_revision_digest_idx",
            ),
        )

    def _validate_document_fields(self) -> None:
        if not isinstance(self.content, dict):
            raise ValidationError({"content": "Graph content must be an object."})
        if not isinstance(self.validation_summary, dict):
            raise ValidationError(
                {"validation_summary": "Validation summary must be an object."}
            )
        try:
            self.content_digest = graph_content_digest(self.content)
        except (TypeError, ValueError) as error:
            raise ValidationError({"content": str(error)}) from error

    def _refuse_update(self) -> None:
        previous = type(self).objects.filter(pk=self.pk).values(
            *self.IMMUTABLE_FIELDS
        ).first()
        if previous is None:
            raise ValidationError("An immutable graph revision cannot be recreated.")
        changed = [
            field
            for field in self.IMMUTABLE_FIELDS
            if getattr(self, field) != previous[field]
        ]
        if changed:
            raise ValidationError(
                "Graph revisions cannot be edited through save(); use the optimistic "
                "draft service or create a new revision instead of changing: "
                f"{', '.join(changed)}."
            )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            self._refuse_update()
            return super().save(*args, **kwargs)
        self._validate_document_fields()
        if self.state == GraphRevisionState.PUBLISHED:
            self.published_at = self.published_at or timezone.now()
        elif self.published_at is not None:
            raise ValidationError(
                {"published_at": "A draft revision cannot have a publication time."}
            )
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.definition.name} r{self.revision_number} ({self.state})"
