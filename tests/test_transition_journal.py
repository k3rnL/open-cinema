import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanStatus,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)
from core.orchestration.action_planning import PhasedDriverAction, ReconciliationPhase
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionFailure,
    ActionFailureClassification,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionError,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.transition_journal import (
    JournalActionStatus,
    TransitionJournalStore,
    TransitionRecoveryMode,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def resolved_plan():
    author = get_user_model().objects.create_user(username="journal-author")
    graph = GraphDefinition.objects.create(name="Journal graph", owner=author)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={"nodes": []},
    )
    return ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=3,
        world_generation=2,
        world_sequence=17,
        status=ResolvedPlanStatus.RESOLVED,
        document={"actionIntent": []},
        explanation={},
    )


def _action():
    identity = DriverActionIdentity(
        "wireplumber",
        "stream",
        "stream:programme",
        "set-stream-target",
    )
    return PhasedDriverAction(
        ReconciliationPhase.ROUTE,
        DriverAction.create(
            identity=identity,
            command=DriverCommand("set-stream-target", {"target": "endpoint:headset"}),
            intent_scope="plan:journal",
            timeout_seconds=2,
            verification=(
                ActionVerification(
                    "stream:programme.target",
                    ActionAssertionOperator.EQUALS,
                    "endpoint:headset",
                ),
            ),
            recovery=ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "The fake action has no external mutation.",
            ),
        ),
    )


def test_action_start_is_committed_before_external_mutation_and_outcome_after(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=1)
    observed_inside_driver = []

    def perform(action):
        persisted = TransitionJournal.objects.get(pk=journal.pk)
        observed_inside_driver.append(
            (
                persisted.phase,
                persisted.status,
                persisted.entries[-1]["status"],
                persisted.entries[-1]["idempotencyKey"],
            )
        )
        assert action is _phased.action
        return {"target": "endpoint:headset"}

    _phased = _action()
    finished = store.execute(journal, _phased, perform)

    assert observed_inside_driver == [
        (
            TransitionPhase.ROUTE,
            TransitionStatus.RUNNING,
            JournalActionStatus.STARTED,
            _phased.action.idempotency_key,
        )
    ]
    assert finished.entries[-1]["status"] == JournalActionStatus.SUCCEEDED
    assert finished.entries[-1]["observed"] == {"target": "endpoint:headset"}
    assert finished.entries[-1]["completedAt"] is not None


def test_classified_driver_failure_is_persisted_before_retry_policy_runs(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=2)
    phased = _action()
    failure = ActionFailure(
        ActionFailureClassification.DEPENDENCY,
        "wireplumber-disconnected",
        "WirePlumber restarted.",
        retry_after_seconds=0.5,
    )

    failed = store.execute(
        journal,
        phased,
        lambda action: (_ for _ in ()).throw(DriverActionError(action, failure)),
    )

    assert failed.status == TransitionStatus.RUNNING
    assert failed.completed_at is None
    assert failed.entries[-1]["status"] == JournalActionStatus.FAILED
    assert failed.entries[-1]["failure"]["classification"] == "dependency"


def test_restart_recovers_started_action_by_verifying_before_retry(resolved_plan) -> None:
    first_process = TransitionJournalStore()
    journal = first_process.start(resolved_plan, generation=3)
    phased = _action()
    first_process.begin_action(journal, phased)

    restarted_process = TransitionJournalStore()
    directives = restarted_process.recover_incomplete()

    directive = next(item for item in directives if item.journal_id == journal.pk)
    assert directive.mode is TransitionRecoveryMode.VERIFY_UNCERTAIN_ACTION
    assert directive.phase is ReconciliationPhase.ROUTE
    assert directive.action == phased.action
    assert "verify postconditions" in directive.reason
    journal.refresh_from_db()
    assert journal.entries[-1]["status"] == JournalActionStatus.UNCERTAIN

    repeated = restarted_process.recover_incomplete()
    repeated_directive = next(item for item in repeated if item.journal_id == journal.pk)
    assert repeated_directive.mode is TransitionRecoveryMode.VERIFY_UNCERTAIN_ACTION


def test_restart_resumes_phase_when_all_persisted_outcomes_are_known(resolved_plan) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=4)
    store.execute(journal, _action(), lambda _action: {"target": "endpoint:headset"})

    directive = next(item for item in store.recover_incomplete() if item.journal_id == journal.pk)

    assert directive.mode is TransitionRecoveryMode.RESUME_PHASE
    assert directive.phase is ReconciliationPhase.ROUTE
    assert directive.action is None


def test_completed_transition_is_not_recovered(resolved_plan) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=5)
    journal = store.execute(
        journal,
        _action(),
        lambda _action: {"target": "endpoint:headset"},
    )
    completed = store.complete(journal)

    assert completed.phase == TransitionPhase.COMPLETED
    assert completed.status == TransitionStatus.SUCCEEDED
    assert completed.completed_at is not None
    assert all(directive.journal_id != journal.pk for directive in store.recover_incomplete())
