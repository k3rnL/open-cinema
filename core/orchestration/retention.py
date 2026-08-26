from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api.models.orchestration import (
    AppliedPlanState,
    DiagnosticRecord,
    OrchestrationEvent,
    ResolvedPlan,
    RuntimeProjection,
    TransitionJournal,
    TransitionStatus,
)


@dataclass(frozen=True, slots=True)
class RetentionReport:
    plans: int = 0
    transition_journals: int = 0
    audit_events: int = 0
    diagnostics: int = 0
    runtime_projections: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _retention_settings() -> dict[str, int]:
    values = settings.AUDIO_ORCHESTRATION_RETENTION
    expected = {
        "plan_days",
        "audit_days",
        "diagnostic_hours",
        "runtime_projection_hours",
        "batch_size",
    }
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError(
            "AUDIO_ORCHESTRATION_RETENTION must define exactly " f"{', '.join(sorted(expected))}"
        )
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"Retention setting {name} must be a positive integer")
    return values


def _delete_batches(queryset, *, batch_size: int) -> int:
    deleted = 0
    while True:
        primary_keys = list(
            queryset.order_by(queryset.model._meta.pk.name).values_list(
                queryset.model._meta.pk.name,
                flat=True,
            )[:batch_size]
        )
        if not primary_keys:
            return deleted
        count, _ = queryset.model.objects.filter(pk__in=primary_keys).delete()
        deleted += count


def _cleanup_plans(*, cutoff, batch_size: int) -> tuple[int, int]:
    protected_plan_ids = set(
        AppliedPlanState.objects.exclude(current_plan=None).values_list(
            "current_plan_id", flat=True
        )
    )
    protected_plan_ids.update(
        AppliedPlanState.objects.exclude(previous_plan=None).values_list(
            "previous_plan_id", flat=True
        )
    )
    nonterminal_statuses = (TransitionStatus.PENDING, TransitionStatus.RUNNING)
    plans_deleted = 0
    journals_deleted = 0

    while True:
        candidates = (
            ResolvedPlan.objects.filter(created_at__lt=cutoff)
            .exclude(pk__in=protected_plan_ids)
            .exclude(transition_journals__status__in=nonterminal_statuses)
        )
        plan_ids = list(
            candidates.order_by("created_at", "id").values_list("id", flat=True)[:batch_size]
        )
        if not plan_ids:
            return plans_deleted, journals_deleted
        with transaction.atomic():
            journal_count, _ = TransitionJournal.objects.filter(plan_id__in=plan_ids).delete()
            plan_count, _ = ResolvedPlan.objects.filter(pk__in=plan_ids).delete()
        journals_deleted += journal_count
        plans_deleted += plan_count


def cleanup_orchestration_data(*, now=None) -> RetentionReport:
    """Prune operational history while preserving intent and rollback state."""

    values = _retention_settings()
    reference_time = now or timezone.now()
    plans, journals = _cleanup_plans(
        cutoff=reference_time - timedelta(days=values["plan_days"]),
        batch_size=values["batch_size"],
    )
    audit_events = _delete_batches(
        OrchestrationEvent.objects.filter(
            occurred_at__lt=reference_time - timedelta(days=values["audit_days"])
        ),
        batch_size=values["batch_size"],
    )
    diagnostics = _delete_batches(
        DiagnosticRecord.objects.filter(
            captured_at__lt=(reference_time - timedelta(hours=values["diagnostic_hours"]))
        ),
        batch_size=values["batch_size"],
    )
    runtime_projections = _delete_batches(
        RuntimeProjection.objects.filter(is_current=False).filter(
            created_at__lt=(reference_time - timedelta(hours=values["runtime_projection_hours"]))
        ),
        batch_size=values["batch_size"],
    )
    return RetentionReport(
        plans=plans,
        transition_journals=journals,
        audit_events=audit_events,
        diagnostics=diagnostics,
        runtime_projections=runtime_projections,
    )
