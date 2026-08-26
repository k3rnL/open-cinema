from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.orchestration.graph_documents import graph_content_digest

from .graph_revision import GraphRevisionState


class ResolvedPlanStatus(models.TextChoices):
    RESOLVED = "resolved", "Resolved"
    WAITING = "waiting", "Waiting"
    DEGRADED = "degraded", "Degraded"
    CONFLICTED = "conflicted", "Conflicted"
    INVALID = "invalid", "Invalid"


class ResolvedPlanMode(models.TextChoices):
    LIVE = "live", "Live candidate"
    SHADOW = "shadow", "Shadow only"


class ResolvedPlan(models.Model):
    """An immutable resolver result correlated to desired and world versions."""

    IMMUTABLE_FIELDS = (
        "schema_version",
        "graph_definition_id",
        "graph_revision_id",
        "desired_state_version",
        "world_generation",
        "world_sequence",
        "resolution_mode",
        "status",
        "document",
        "explanation",
        "plan_digest",
        "correlation_id",
        "created_at",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.PositiveIntegerField(default=1)
    graph_definition = models.ForeignKey(
        "api.GraphDefinition",
        on_delete=models.PROTECT,
        related_name="resolved_plans",
    )
    graph_revision = models.ForeignKey(
        "api.GraphRevision",
        on_delete=models.PROTECT,
        related_name="resolved_plans",
    )
    desired_state_version = models.PositiveBigIntegerField()
    world_generation = models.PositiveBigIntegerField()
    world_sequence = models.PositiveBigIntegerField()
    resolution_mode = models.CharField(
        max_length=16,
        choices=ResolvedPlanMode.choices,
        default=ResolvedPlanMode.LIVE,
    )
    status = models.CharField(max_length=16, choices=ResolvedPlanStatus.choices)
    document = models.JSONField()
    explanation = models.JSONField(default=dict)
    plan_digest = models.CharField(max_length=64, editable=False)
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "id")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="api_resolved_plan_schema_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(desired_state_version__gte=1),
                name="api_resolved_plan_desired_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(world_generation__gte=1),
                name="api_resolved_plan_world_generation_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(plan_digest=""),
                name="api_resolved_plan_digest_nonempty",
            ),
        )
        indexes = (
            models.Index(
                fields=("graph_definition", "created_at"),
                name="api_plan_graph_time_idx",
            ),
            models.Index(
                fields=("status", "created_at"),
                name="api_plan_status_time_idx",
            ),
        )

    def _validate_values(self) -> None:
        errors = {}
        if not isinstance(self.document, dict):
            errors["document"] = "Resolved plan document must be an object."
        if not isinstance(self.explanation, dict):
            errors["explanation"] = "Resolved plan explanation must be an object."
        if self.graph_revision_id:
            if self.graph_revision.definition_id != self.graph_definition_id:
                errors["graph_revision"] = "Revision belongs to another graph."
            elif self.graph_revision.state != GraphRevisionState.PUBLISHED:
                errors["graph_revision"] = "Resolved plans require a published revision."
        if errors:
            raise ValidationError(errors)
        try:
            self.plan_digest = graph_content_digest(
                {
                    "schemaVersion": self.schema_version,
                    "status": self.status,
                    "document": self.document,
                    "explanation": self.explanation,
                }
            )
        except (TypeError, ValueError) as error:
            raise ValidationError({"document": str(error)}) from error

    def _refuse_update(self) -> None:
        previous = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
        if previous is None:
            raise ValidationError("An immutable resolved plan cannot be recreated.")
        changed = [
            field for field in self.IMMUTABLE_FIELDS if getattr(self, field) != previous[field]
        ]
        if changed:
            raise ValidationError(
                "Resolved plans are immutable; create a new plan instead of changing: "
                f"{', '.join(changed)}."
            )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            self._refuse_update()
            return super().save(*args, **kwargs)
        self._validate_values()
        return super().save(*args, **kwargs)


class ShadowResolutionComparison(models.Model):
    """Persisted evidence comparing a shadow result with an optional baseline."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shadow_plan = models.OneToOneField(
        "api.ResolvedPlan",
        on_delete=models.CASCADE,
        related_name="shadow_comparison",
    )
    baseline_plan = models.ForeignKey(
        "api.ResolvedPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shadow_baseline_comparisons",
    )
    equivalent = models.BooleanField(default=False)
    differences = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "id")
        indexes = (
            models.Index(
                fields=("equivalent", "created_at"),
                name="api_shadow_compare_result_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if not isinstance(self.differences, dict):
            errors["differences"] = "Shadow comparison differences must be an object."
        if self.shadow_plan_id:
            if self.shadow_plan.resolution_mode != ResolvedPlanMode.SHADOW:
                errors["shadow_plan"] = "Shadow comparison requires a shadow plan."
            if (
                self.baseline_plan_id
                and self.baseline_plan.graph_definition_id != self.shadow_plan.graph_definition_id
            ):
                errors["baseline_plan"] = "Baseline and shadow plans belong to different graphs."
        if errors:
            raise ValidationError(errors)


class AppliedPlanStatus(models.TextChoices):
    IDLE = "idle", "Idle"
    APPLYING = "applying", "Applying"
    CONVERGED = "converged", "Converged"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"


class AppliedPlanState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    graph_definition = models.OneToOneField(
        "api.GraphDefinition",
        on_delete=models.CASCADE,
        related_name="applied_plan_state",
    )
    current_plan = models.ForeignKey(
        "api.ResolvedPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_applied_states",
    )
    previous_plan = models.ForeignKey(
        "api.ResolvedPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="previous_applied_states",
    )
    transition_generation = models.PositiveBigIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=AppliedPlanStatus.choices,
        default=AppliedPlanStatus.IDLE,
    )
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    last_error = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = (
            models.CheckConstraint(
                condition=(
                    models.Q(current_plan__isnull=True)
                    | models.Q(previous_plan__isnull=True)
                    | ~models.Q(current_plan=models.F("previous_plan"))
                ),
                name="api_applied_plan_distinct_rollback",
            ),
        )
        indexes = (
            models.Index(
                fields=("status", "updated_at"),
                name="api_applied_plan_status_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        for field in ("current_plan", "previous_plan"):
            plan = getattr(self, field)
            if plan is not None:
                if plan.graph_definition_id != self.graph_definition_id:
                    errors[field] = "Applied plan belongs to another graph."
                elif plan.resolution_mode == ResolvedPlanMode.SHADOW:
                    errors[field] = "A shadow plan cannot become an applied plan."
        if self.last_error is not None and not isinstance(self.last_error, dict):
            errors["last_error"] = "Last error must be an object or null."
        if self.status == AppliedPlanStatus.CONVERGED and self.current_plan_id is None:
            errors["current_plan"] = "A converged state requires a current plan."
        if errors:
            raise ValidationError(errors)


class TransitionPhase(models.TextChoices):
    PREPARE = "prepare", "Prepare"
    SUPPRESS = "suppress", "Suppress"
    CONFIGURE = "configure", "Configure"
    ROUTE = "route", "Route"
    VERIFY = "verify", "Verify"
    UNSUPPRESS = "unsuppress", "Unsuppress"
    CLEANUP = "cleanup", "Cleanup"
    COMPLETED = "completed", "Completed"


class TransitionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    ROLLED_BACK = "rolled_back", "Rolled back"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_TRANSITION_STATUSES = {
    TransitionStatus.SUCCEEDED,
    TransitionStatus.FAILED,
    TransitionStatus.ROLLED_BACK,
    TransitionStatus.CANCELLED,
}


class TransitionJournal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    graph_definition = models.ForeignKey(
        "api.GraphDefinition",
        on_delete=models.PROTECT,
        related_name="transition_journals",
    )
    plan = models.ForeignKey(
        "api.ResolvedPlan",
        on_delete=models.PROTECT,
        related_name="transition_journals",
    )
    generation = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField(db_index=True)
    phase = models.CharField(
        max_length=16,
        choices=TransitionPhase.choices,
        default=TransitionPhase.PREPARE,
    )
    status = models.CharField(
        max_length=16,
        choices=TransitionStatus.choices,
        default=TransitionStatus.PENDING,
    )
    entries = models.JSONField(default=list)
    started_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("graph_definition_id", "generation")
        constraints = (
            models.UniqueConstraint(
                fields=("graph_definition", "generation"),
                name="api_transition_graph_generation_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gte=1),
                name="api_transition_generation_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("status", "updated_at"),
                name="api_transition_status_time_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.plan_id:
            if self.plan.graph_definition_id != self.graph_definition_id:
                errors["plan"] = "Transition plan belongs to another graph."
            elif self.plan.resolution_mode == ResolvedPlanMode.SHADOW:
                errors["plan"] = "A shadow plan cannot create a transition journal."
        if not isinstance(self.entries, list):
            errors["entries"] = "Transition entries must be a list."
        terminal = self.status in TERMINAL_TRANSITION_STATUSES
        if terminal != (self.completed_at is not None):
            errors["completed_at"] = (
                "Completion time must be present exactly for terminal transitions."
            )
        if errors:
            raise ValidationError(errors)
