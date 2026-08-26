import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    OrchestrationEvent,
    ResolvedPlan,
    ResolvedPlanStatus,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)
from core.orchestration.audit import record_orchestration_event


pytestmark = pytest.mark.django_db


@pytest.fixture
def resolved_plan():
    author = get_user_model().objects.create_user(username="plan-author")
    graph = GraphDefinition.objects.create(name="Plan graph", owner=author)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={"nodes": []},
    )
    plan = ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=3,
        world_generation=2,
        world_sequence=17,
        status=ResolvedPlanStatus.RESOLVED,
        document={"selected": ["main-speakers"]},
        explanation={"reason": "headset unavailable"},
    )
    return graph, plan


def test_resolved_plan_is_content_addressed_and_immutable(resolved_plan) -> None:
    _, plan = resolved_plan
    assert len(plan.plan_digest) == 64
    plan.document = {"selected": ["headset"]}
    with pytest.raises(ValidationError, match="immutable"):
        plan.save()


def test_applied_state_and_transition_share_plan_correlation(resolved_plan) -> None:
    graph, plan = resolved_plan
    state = AppliedPlanState(
        graph_definition=graph,
        current_plan=plan,
        transition_generation=1,
        status=AppliedPlanStatus.CONVERGED,
        correlation_id=plan.correlation_id,
    )
    state.full_clean()
    state.save()
    journal = TransitionJournal(
        graph_definition=graph,
        plan=plan,
        generation=1,
        correlation_id=plan.correlation_id,
        phase=TransitionPhase.COMPLETED,
        status=TransitionStatus.SUCCEEDED,
        entries=[{"action": "route", "status": "confirmed"}],
        completed_at=timezone.now(),
    )
    journal.full_clean()
    journal.save()

    assert state.current_plan == plan
    assert state.correlation_id == journal.correlation_id == plan.correlation_id
    assert journal.entries[0]["status"] == "confirmed"


def test_cross_graph_applied_state_is_rejected(resolved_plan) -> None:
    _, plan = resolved_plan
    owner = plan.graph_definition.owner
    other = GraphDefinition.objects.create(name="Other plan graph", owner=owner)
    state = AppliedPlanState(
        graph_definition=other,
        current_plan=plan,
        status=AppliedPlanStatus.CONVERGED,
    )
    with pytest.raises(ValidationError, match="another graph"):
        state.full_clean()


@override_settings(AUDIO_ORCHESTRATION_AUDIT_MAX_RECORDS=3)
def test_audit_stream_is_trimmed_to_configured_bound(resolved_plan) -> None:
    graph, plan = resolved_plan
    for number in range(5):
        record_orchestration_event(
            correlation_id=plan.correlation_id,
            graph_definition=graph,
            event_type="resolution.step",
            payload={"number": number},
        )

    events = list(OrchestrationEvent.objects.all())
    assert len(events) == 3
    assert [event.payload["number"] for event in events] == [2, 3, 4]
    assert [event.sequence for event in events] == sorted(
        event.sequence for event in events
    )
    assert all(isinstance(event.id, uuid.UUID) for event in events)
