from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.orchestration.camilladsp_profiles import (
    CAMILLADSP_PROFILE_SCHEMA_VERSION,
    CamillaDSPProfileError,
    normalize_camilladsp_profile,
)


class CamillaDSPProfileQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_staff or user.is_superuser:
            return self
        return self.filter(owner=user)

    def latest_versions(self):
        latest = (
            self.filter(profile_id=models.OuterRef("profile_id"))
            .order_by("-version")
            .values("version")[:1]
        )
        return self.annotate(_latest_version=models.Subquery(latest)).filter(
            version=models.F("_latest_version")
        )


class CamillaDSPProfile(models.Model):
    """One immutable revision in a stable CamillaDSP profile lineage."""

    IMMUTABLE_FIELDS = (
        "profile_id",
        "version",
        "schema_version",
        "owner_id",
        "name",
        "description",
        "content",
        "content_digest",
        "validation_summary",
        "created_at",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile_id = models.UUIDField(default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField()
    schema_version = models.PositiveIntegerField(default=CAMILLADSP_PROFILE_SCHEMA_VERSION)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="camilladsp_profiles",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    content = models.JSONField()
    content_digest = models.CharField(max_length=64, editable=False)
    validation_summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CamillaDSPProfileQuerySet.as_manager()

    class Meta:
        ordering = ("profile_id", "version")
        constraints = (
            models.UniqueConstraint(
                fields=("profile_id", "version"),
                name="api_camilladsp_profile_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="api_camilladsp_profile_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version=CAMILLADSP_PROFILE_SCHEMA_VERSION),
                name="api_camilladsp_profile_schema_supported",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="api_camilladsp_profile_name_nonempty",
            ),
            models.CheckConstraint(
                condition=~models.Q(content_digest=""),
                name="api_camilladsp_profile_digest_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("owner", "name"),
                name="api_camilladsp_owner_name_idx",
            ),
            models.Index(
                fields=("content_digest",),
                name="api_camilladsp_digest_idx",
            ),
        )

    def _normalize_content(self) -> None:
        if self.schema_version != CAMILLADSP_PROFILE_SCHEMA_VERSION:
            raise ValidationError(
                {
                    "schema_version": (
                        f"Only CamillaDSP profile schema version "
                        f"{CAMILLADSP_PROFILE_SCHEMA_VERSION} is supported."
                    )
                }
            )
        try:
            normalized = normalize_camilladsp_profile(self.content)
        except CamillaDSPProfileError as error:
            raise ValidationError({"content": str(error)}) from error
        self.content = normalized.content
        self.content_digest = normalized.digest
        if not self.validation_summary:
            self.validation_summary = {
                "valid": True,
                "profileDigest": normalized.digest,
            }
        if not isinstance(self.validation_summary, dict):
            raise ValidationError({"validation_summary": "Validation summary must be an object."})

    def _refuse_update(self) -> None:
        previous = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
        if previous is None:
            raise ValidationError("An immutable CamillaDSP profile cannot be recreated.")
        changed = [
            field for field in self.IMMUTABLE_FIELDS if getattr(self, field) != previous[field]
        ]
        if changed:
            raise ValidationError(
                "CamillaDSP profile revisions are immutable; create the next version "
                f"instead of changing: {', '.join(changed)}."
            )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            self._refuse_update()
            return super().save(*args, **kwargs)
        self._normalize_content()
        return super().save(*args, **kwargs)

    def new_version(self, *, content, author=None, **changes):
        """Build, but do not persist, the next immutable lineage version."""

        if author is not None and author.pk != self.owner_id:
            raise ValidationError("A profile version cannot change its owner.")
        return type(self)(
            profile_id=self.profile_id,
            version=self.version + 1,
            schema_version=self.schema_version,
            owner=self.owner,
            name=changes.pop("name", self.name),
            description=changes.pop("description", self.description),
            content=content,
            **changes,
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"
