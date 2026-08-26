import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    GraphActivation,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanStatus,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)
from core.orchestration.readiness import inspect_orchestration_readiness


pytestmark = pytest.mark.django_db


def _active_graph():
    owner = get_user_model().objects.create_user(username="readiness-owner")
    graph = GraphDefinition.objects.create(name="Readiness graph", owner=owner)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={"nodes": []},
    )
    activation = GraphActivation.objects.create(
        definition=graph,
        revision=revision,
        enabled=True,
        desired_state_version=3,
        activated_at=timezone.now(),
    )
    plan = ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=3,
        world_generation=2,
        world_sequence=17,
        status=ResolvedPlanStatus.RESOLVED,
        document={"selected": []},
        explanation={"reason": "ready"},
    )
    state = AppliedPlanState.objects.create(
        graph_definition=graph,
        current_plan=plan,
        transition_generation=1,
        status=AppliedPlanStatus.CONVERGED,
        correlation_id=plan.correlation_id,
    )
    return activation, plan, state


def test_readiness_accepts_matching_converged_desired_state(capsys) -> None:
    _active_graph()

    report = inspect_orchestration_readiness()
    call_command("check_orchestration_readiness")
    output = json.loads(capsys.readouterr().out.splitlines()[-1])

    assert report.ready is True
    assert report.active_graphs == report.converged_graphs == 1
    assert report.unfinished_transitions == 0
    assert output["ready"] is True


def test_readiness_reports_version_drift_and_unfinished_transition() -> None:
    activation, plan, state = _active_graph()
    activation.desired_state_version = 4
    activation.save(update_fields=["desired_state_version", "updated_at"])
    state.status = AppliedPlanStatus.APPLYING
    state.save(update_fields=["status", "updated_at"])
    TransitionJournal.objects.create(
        graph_definition=activation.definition,
        plan=plan,
        generation=1,
        correlation_id=plan.correlation_id,
        phase=TransitionPhase.ROUTE,
        status=TransitionStatus.RUNNING,
        entries=[],
    )

    report = inspect_orchestration_readiness()

    assert report.ready is False
    assert report.unfinished_transitions == 1
    assert any("applying plan state" in failure for failure in report.failures)
    assert any("unfinished" in failure for failure in report.failures)
    with pytest.raises(CommandError, match='"ready": false'):
        call_command("check_orchestration_readiness")
