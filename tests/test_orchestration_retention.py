import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    DiagnosticRecord,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    OrchestrationEvent,
    ResolvedPlan,
    ResolvedPlanStatus,
    RuntimeProjection,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)
from api.tasks.orchestration_cleanup import cleanup_audio_orchestration_data
from core.orchestration.retention import cleanup_orchestration_data


pytestmark = pytest.mark.django_db

RETENTION = {
    "plan_days": 1,
    "audit_days": 1,
    "diagnostic_hours": 1,
    "runtime_projection_hours": 1,
    "batch_size": 2,
}


def _plan(graph, revision, number):
    return ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=number,
        world_generation=1,
        world_sequence=number,
        status=ResolvedPlanStatus.RESOLVED,
        document={"number": number},
        explanation={},
    )


@override_settings(AUDIO_ORCHESTRATION_RETENTION=RETENTION)
def test_cleanup_preserves_desired_revisions_and_two_applied_plans() -> None:
    now = timezone.now()
    old = now - timedelta(days=2)
    author = get_user_model().objects.create_user(username="retention-owner")
    graph = GraphDefinition.objects.create(name="Retained graph", owner=author)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={"nodes": []},
    )
    current = _plan(graph, revision, 1)
    previous = _plan(graph, revision, 2)
    expired = _plan(graph, revision, 3)
    recent = _plan(graph, revision, 4)
    ResolvedPlan.objects.filter(pk__in=(current.pk, previous.pk, expired.pk)).update(
        created_at=old
    )
    AppliedPlanState.objects.create(
        graph_definition=graph,
        current_plan=current,
        previous_plan=previous,
        status=AppliedPlanStatus.CONVERGED,
    )
    TransitionJournal.objects.create(
        graph_definition=graph,
        plan=expired,
        generation=1,
        correlation_id=expired.correlation_id,
        phase=TransitionPhase.COMPLETED,
        status=TransitionStatus.SUCCEEDED,
        entries=[],
        started_at=old,
        completed_at=old,
    )

    report = cleanup_orchestration_data(now=now)

    assert report.plans == 1
    assert report.transition_journals == 1
    assert set(ResolvedPlan.objects.values_list("pk", flat=True)) == {
        current.pk,
        previous.pk,
        recent.pk,
    }
    assert GraphRevision.objects.filter(pk=revision.pk).exists()
    assert GraphDefinition.objects.filter(pk=graph.pk).exists()


@override_settings(AUDIO_ORCHESTRATION_RETENTION=RETENTION)
def test_cleanup_bounds_audit_diagnostics_and_only_superseded_projections() -> None:
    now = timezone.now()
    old = now - timedelta(hours=2)
    old_audit = now - timedelta(days=2)
    correlation = uuid.uuid4()
    old_event = OrchestrationEvent.objects.create(
        correlation_id=correlation,
        event_type="runtime.raw",
    )
    current_event = OrchestrationEvent.objects.create(
        correlation_id=correlation,
        event_type="runtime.current",
    )
    OrchestrationEvent.objects.filter(pk=old_event.pk).update(occurred_at=old_audit)
    old_diagnostic = DiagnosticRecord.objects.create(
        correlation_id=correlation,
        category="wireplumber.event",
        captured_at=old,
    )
    current_diagnostic = DiagnosticRecord.objects.create(
        correlation_id=correlation,
        category="wireplumber.health",
        captured_at=now,
    )
    historical = RuntimeProjection.objects.create(
        projection_type="endpoint",
        subject_key="speakers",
        world_generation=1,
        world_sequence=1,
        payload={"available": False},
        is_current=False,
        observed_at=old,
        created_at=old,
    )
    current = RuntimeProjection.objects.create(
        projection_type="endpoint",
        subject_key="speakers",
        world_generation=1,
        world_sequence=2,
        payload={"available": True},
        is_current=True,
        observed_at=old,
        created_at=old,
    )

    report = cleanup_orchestration_data(now=now)

    assert report.audit_events == 1
    assert report.diagnostics == 1
    assert report.runtime_projections == 1
    assert OrchestrationEvent.objects.filter(pk=current_event.pk).exists()
    assert not OrchestrationEvent.objects.filter(pk=old_event.pk).exists()
    assert DiagnosticRecord.objects.filter(pk=current_diagnostic.pk).exists()
    assert not DiagnosticRecord.objects.filter(pk=old_diagnostic.pk).exists()
    assert RuntimeProjection.objects.filter(pk=current.pk, is_current=True).exists()
    assert not RuntimeProjection.objects.filter(pk=historical.pk).exists()


@override_settings(AUDIO_ORCHESTRATION_RETENTION=RETENTION)
def test_celery_cleanup_job_returns_serializable_counts() -> None:
    assert cleanup_audio_orchestration_data.run() == {
        "plans": 0,
        "transition_journals": 0,
        "audit_events": 0,
        "diagnostics": 0,
        "runtime_projections": 0,
    }


@override_settings(
    AUDIO_ORCHESTRATION_RETENTION={**RETENTION, "batch_size": 0}
)
def test_cleanup_rejects_an_unbounded_or_disabled_batch() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        cleanup_orchestration_data()
