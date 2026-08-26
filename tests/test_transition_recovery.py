import pytest
from django.contrib.auth import get_user_model

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanStatus,
    TransitionStatus,
)
from core.orchestration.action_planning import PhasedDriverAction, ReconciliationPhase
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionFailure,
    ActionFailureClassification,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionRecoveryStep,
    ActionVerification,
    DriverAction,
    DriverActionError,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.transition_journal import TransitionJournalStore
from core.orchestration.transition_recovery import (
    DeclaredDegradedFallback,
    TransitionRecoveryExecutor,
    TransitionRecoveryStatus,
)
from core.orchestration.startup_transition_recovery import StartupTransitionRecovery
from core.orchestration.runtime_world import InMemoryWorldStore
from tests.test_endpoint_inventory_mapping import _snapshot

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def resolved_plan():
    author = get_user_model().objects.create_user(username="recovery-author")
    graph = GraphDefinition.objects.create(name="Recovery graph", owner=author)
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
        desired_state_version=1,
        world_generation=1,
        world_sequence=1,
        status=ResolvedPlanStatus.RESOLVED,
        document={},
        explanation={},
    )


def _verification(operation, expected=True):
    return ActionVerification(
        f"operation.{operation}.satisfied",
        ActionAssertionOperator.EQUALS,
        expected,
    )


def _step(operation):
    return ActionRecoveryStep(
        DriverCommand(operation, {}),
        (_verification(operation),),
        f"Execute {operation}.",
    )


def _failed_action(phase, recovery):
    operation = f"apply-{phase.value}"
    identity = DriverActionIdentity("fake-driver", "route", "route:main", operation)
    return PhasedDriverAction(
        phase,
        DriverAction.create(
            identity=identity,
            command=DriverCommand(operation, {}),
            intent_scope="plan:recovery",
            timeout_seconds=1,
            verification=(_verification(operation),),
            recovery=recovery,
        ),
    )


def _fallback_action(operation="apply-speaker-fallback"):
    identity = DriverActionIdentity(
        "fake-driver",
        "route",
        "route:fallback",
        operation,
    )
    return PhasedDriverAction(
        ReconciliationPhase.ROUTE,
        DriverAction.create(
            identity=identity,
            command=DriverCommand(operation, {}),
            intent_scope="fallback:speakers",
            timeout_seconds=1,
            verification=(_verification(operation),),
            recovery=ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "This is the final declared fallback.",
            ),
        ),
    )


def test_startup_recovery_closes_interrupted_journal_after_connection_cleanup(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=1)
    AppliedPlanState.objects.create(
        graph_definition=resolved_plan.graph_definition,
        transition_generation=1,
        status=AppliedPlanStatus.APPLYING,
        correlation_id=resolved_plan.correlation_id,
    )
    world = InMemoryWorldStore().install_runtime_snapshot(_snapshot(generation=2))

    recovered = StartupTransitionRecovery(store).recover(world)

    journal.refresh_from_db()
    state = AppliedPlanState.objects.get(graph_definition=resolved_plan.graph_definition)
    assert len(recovered) == 1
    assert recovered[0].status == TransitionStatus.CANCELLED
    assert recovered[0].remaining_owned_link_ids == ()
    assert journal.status == TransitionStatus.CANCELLED
    assert journal.entries[-1]["summary"]["freshRuntimeGeneration"] == 2
    assert state.status == AppliedPlanStatus.DEGRADED
    assert state.last_error["code"] == "transition-interrupted-clean"
    assert resolved_plan.graph_definition.orchestration_events.filter(
        event_type="transition-startup-recovery"
    ).exists()


class RecoveryDriver:
    def __init__(self, *, fail=()):
        self.satisfied = set()
        self.fail = set(fail)
        self.calls = []

    def observe(self, action):
        operation = action.command.operation
        return {f"operation.{operation}.satisfied": operation in self.satisfied}

    def perform(self, action):
        operation = action.command.operation
        self.calls.append(operation)
        if operation in self.fail:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.SAFETY,
                    "recovery-step-failed",
                    f"{operation} failed",
                ),
            )
        self.satisfied.add(operation)
        return self.observe(action)


def _failure():
    return ActionFailure(
        ActionFailureClassification.SAFETY,
        "transition-action-failed",
        "The transition action could not be verified.",
    )


@pytest.mark.parametrize(
    "phase",
    (
        ReconciliationPhase.PREPARE,
        ReconciliationPhase.CONFIGURE,
        ReconciliationPhase.ROUTE,
        ReconciliationPhase.VERIFY,
    ),
)
def test_phase_failure_runs_inverse_and_persists_rollback(resolved_plan, phase) -> None:
    recovery = ActionRecoveryPolicy(
        ActionRecoveryMode.INVERSE,
        "Restore the prior state.",
        inverse=_step("restore-prior-state"),
    )
    failed_action = _failed_action(phase, recovery)
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=1)
    driver = RecoveryDriver()

    result = TransitionRecoveryExecutor(store).recover(
        journal,
        failed_action=failed_action,
        failure=_failure(),
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.status is TransitionRecoveryStatus.ROLLED_BACK
    assert result.journal.status == TransitionStatus.ROLLED_BACK
    assert driver.calls == ["restore-prior-state"]
    assert result.journal.entries[-1]["kind"] == "transition-recovery"
    assert result.journal.entries[-1]["summary"]["outcome"] == "rolled-back"


def test_failed_inverse_uses_action_safe_fallback(resolved_plan) -> None:
    recovery = ActionRecoveryPolicy(
        ActionRecoveryMode.INVERSE_THEN_FALLBACK,
        "Try restoration, then keep output muted.",
        inverse=_step("restore-prior-state"),
        safe_fallback=_step("keep-output-muted"),
    )
    failed_action = _failed_action(ReconciliationPhase.CONFIGURE, recovery)
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=2)
    driver = RecoveryDriver(fail=("restore-prior-state",))

    result = TransitionRecoveryExecutor(store).recover(
        journal,
        failed_action=failed_action,
        failure=_failure(),
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.status is TransitionRecoveryStatus.DEGRADED_FALLBACK
    assert result.fallback_id == "action-safe-fallback"
    assert driver.calls == ["restore-prior-state", "keep-output-muted"]
    assert result.journal.status == TransitionStatus.ROLLED_BACK


def test_declared_graph_fallback_is_used_when_action_has_no_inverse(resolved_plan) -> None:
    failed_action = _failed_action(
        ReconciliationPhase.ROUTE,
        ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "Use the graph's declared degraded route.",
        ),
    )
    fallback = DeclaredDegradedFallback(
        "main-speakers",
        "Headset route failed; retain main speakers.",
        (_fallback_action(),),
    )
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=3)
    driver = RecoveryDriver()

    result = TransitionRecoveryExecutor(store).recover(
        journal,
        failed_action=failed_action,
        failure=_failure(),
        degraded_fallback=fallback,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.status is TransitionRecoveryStatus.DEGRADED_FALLBACK
    assert result.fallback_id == "main-speakers"
    assert driver.calls == ["apply-speaker-fallback"]


def test_exhausted_recovery_is_explicit_terminal_failure(resolved_plan) -> None:
    failed_action = _failed_action(
        ReconciliationPhase.VERIFY,
        ActionRecoveryPolicy(
            ActionRecoveryMode.SAFE_FALLBACK,
            "Keep output muted.",
            safe_fallback=_step("keep-output-muted"),
        ),
    )
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=4)
    driver = RecoveryDriver(fail=("keep-output-muted",))

    result = TransitionRecoveryExecutor(store).recover(
        journal,
        failed_action=failed_action,
        failure=_failure(),
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.status is TransitionRecoveryStatus.FAILED
    assert result.journal.status == TransitionStatus.FAILED
    assert result.journal.completed_at is not None
    assert result.reasons[-1] == "fallback-failed"
