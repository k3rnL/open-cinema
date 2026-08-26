import uuid
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth import get_user_model

from api.models import GraphDefinition, OrchestrationEvent
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionFailure,
    ActionFailureClassification,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.reconciliation_audit import (
    AuditedActionStatus,
    GenerationConvergenceStatus,
    ReconciliationActionAudit,
    ReconciliationGenerationAudit,
    ReconciliationInputVersions,
    ReconciliationTriggerAudit,
    persist_reconciliation_generation_audit,
)

pytestmark = pytest.mark.django_db


def _action():
    identity = DriverActionIdentity(
        "wireplumber", "stream", "stream:programme", "set-stream-target"
    )
    return DriverAction.create(
        identity=identity,
        command=DriverCommand("set-stream-target", {"target": "endpoint:headset"}),
        intent_scope="plan:audit",
        timeout_seconds=2,
        verification=(
            ActionVerification(
                "stream.programme.target",
                ActionAssertionOperator.EQUALS,
                "endpoint:headset",
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "The fake action has no mutation.",
        ),
    )


def _audit(graph, *, status=GenerationConvergenceStatus.CONVERGED, failure=None):
    started = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    completed = started + timedelta(milliseconds=350)
    action = ReconciliationActionAudit(
        phase="route",
        action=_action(),
        status=AuditedActionStatus.FAILED if failure else AuditedActionStatus.SUCCEEDED,
        started_at=started + timedelta(milliseconds=100),
        completed_at=started + timedelta(milliseconds=250),
        attempts=2,
        observed={"target": "endpoint:headset"},
        failure=failure,
    )
    return ReconciliationGenerationAudit(
        graph_definition_id=str(graph.pk),
        correlation_id=uuid.uuid4(),
        generation=7,
        trigger=ReconciliationTriggerAudit(
            "runtime-change",
            ("headset-connected", "default-changed"),
            started - timedelta(milliseconds=10),
        ),
        inputs=ReconciliationInputVersions(
            graph_revision_id="revision:main:3",
            graph_revision_digest="revision-digest",
            desired_state_version=9,
            world_version=12,
            runtime_generation=4,
            runtime_sequence=88,
            resolved_plan_id="plan:resolved",
            resolved_plan_digest="plan-digest",
            transition_generation=7,
            applied_plan_id="plan:previous",
            applied_plan_digest="previous-digest",
        ),
        decision={
            "selectedOutput": "endpoint:headset",
            "reason": "Headset has higher priority.",
        },
        actions=(action,),
        started_at=started,
        completed_at=completed,
        convergence_status=status,
        final_runtime_generation=4,
        final_runtime_sequence=91,
        errors=(failure,) if failure else (),
    )


def test_generation_audit_persists_every_correlation_and_timing_dimension() -> None:
    owner = get_user_model().objects.create_user(username="audit-author")
    graph = GraphDefinition.objects.create(name="Audit graph", owner=owner)
    audit = _audit(graph)

    event = persist_reconciliation_generation_audit(audit, graph_definition=graph)

    event.refresh_from_db()
    payload = event.payload
    assert event.event_type == "reconciliation.generation.completed"
    assert event.severity == "info"
    assert event.correlation_id == audit.correlation_id
    assert payload["generation"] == 7
    assert payload["trigger"] == {
        "kind": "runtime-change",
        "causes": ["headset-connected", "default-changed"],
        "occurredAt": "2026-08-22T11:59:59.990000+00:00",
    }
    assert payload["inputs"]["desiredStateVersion"] == 9
    assert payload["inputs"]["worldVersion"] == 12
    assert payload["inputs"]["resolvedPlanDigest"] == "plan-digest"
    assert payload["inputs"]["appliedPlanDigest"] == "previous-digest"
    assert payload["decision"]["selectedOutput"] == "endpoint:headset"
    assert payload["actions"][0]["idempotencyKey"].startswith("action-v1:")
    assert payload["actions"][0]["attempts"] == 2
    assert payload["actions"][0]["durationMs"] == 150
    assert payload["timing"]["durationMs"] == 350
    assert payload["timing"]["phaseDurationMs"] == {"route": 150}
    assert payload["final"] == {
        "convergenceStatus": "converged",
        "runtimeGeneration": 4,
        "runtimeSequence": 91,
    }


def test_failed_generation_persists_classified_errors_with_error_severity() -> None:
    owner = get_user_model().objects.create_user(username="failed-audit-author")
    graph = GraphDefinition.objects.create(name="Failed audit graph", owner=owner)
    failure = ActionFailure(
        ActionFailureClassification.SAFETY,
        "verification-failed",
        "The routed stream was not observed.",
    )

    event = persist_reconciliation_generation_audit(
        _audit(graph, status=GenerationConvergenceStatus.FAILED, failure=failure),
        graph_definition=graph,
    )

    assert event.severity == "error"
    assert event.payload["errors"][0]["classification"] == "safety"
    assert event.payload["actions"][0]["failure"]["code"] == "verification-failed"
    assert (
        OrchestrationEvent.objects.filter(event_type="reconciliation.generation.completed").count()
        == 1
    )


def test_audit_rejects_mismatched_graph_identity() -> None:
    owner = get_user_model().objects.create_user(username="mismatch-audit-author")
    graph = GraphDefinition.objects.create(name="First graph", owner=owner)
    other = GraphDefinition.objects.create(name="Other graph", owner=owner)

    with pytest.raises(ValueError, match="identities do not match"):
        persist_reconciliation_generation_audit(_audit(graph), graph_definition=other)
