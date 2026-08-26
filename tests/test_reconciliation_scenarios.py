import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanStatus,
    TransitionStatus,
)
from core.orchestration.action_planning import (
    ObservedManagedState,
    PhasedDriverAction,
    ReconciliationPhase,
    ResolvedDriverIntent,
    build_reconciliation_action_plan,
)
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
from core.orchestration.generation_guard import (
    GenerationInput,
    OrchestrationGenerationCoordinator,
    StaleGenerationAbort,
)
from core.orchestration.idempotent_execution import (
    IdempotentActionExecutor,
    IdempotentExecutionDisposition,
)
from core.orchestration.reconciliation_scheduler import (
    CoalescingReconciliationQueue,
    ReconciliationWork,
)
from core.orchestration.transition_journal import (
    JournalActionStatus,
    TransitionJournalStore,
)
from core.orchestration.transition_recovery import (
    TransitionRecoveryExecutor,
    TransitionRecoveryStatus,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def resolved_plan():
    author = get_user_model().objects.create_user(username="scenario-author")
    graph = GraphDefinition.objects.create(name="Scenario graph", owner=author)
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


def _verification(operation):
    return ActionVerification(
        f"operation.{operation}.ready",
        ActionAssertionOperator.EQUALS,
        True,
    )


def _action(phase, operation, *, recovery=None):
    identity = DriverActionIdentity(
        "fake-driver",
        "scenario-resource",
        f"resource:{operation}",
        operation,
    )
    return PhasedDriverAction(
        phase,
        DriverAction.create(
            identity=identity,
            command=DriverCommand(operation, {}),
            intent_scope="scenario:desired:1",
            timeout_seconds=1,
            verification=(_verification(operation),),
            recovery=recovery
            or ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "The fake ensure action is idempotent.",
            ),
        ),
    )


class FakeDriver:
    def __init__(self, *, failures=()):
        self.ready = set()
        self.failures = set(failures)
        self.calls = []

    def observe(self, action):
        operation = action.command.operation
        return {f"operation.{operation}.ready": operation in self.ready}

    def perform(self, action):
        operation = action.command.operation
        self.calls.append((operation, action.idempotency_key))
        if operation in self.failures:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.DEPENDENCY,
                    "fake-dependency-failure",
                    f"{operation} dependency failed",
                ),
            )
        self.ready.add(operation)
        return self.observe(action)


def test_fake_driver_plan_converges_in_phase_order_without_duplicate_actions(
    resolved_plan,
) -> None:
    prepare = _action(ReconciliationPhase.PREPARE, "prepare-processor")
    route = _action(ReconciliationPhase.ROUTE, "route-headset")
    unsuppress = _action(ReconciliationPhase.UNSUPPRESS, "restore-output")
    action_plan = build_reconciliation_action_plan(
        ResolvedDriverIntent(
            resolved_plan.plan_digest,
            resolved_plan.desired_state_version,
            (unsuppress, route, prepare),
        ),
        ObservedManagedState(1, 1, {}),
    )
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=1)
    executor = IdempotentActionExecutor(store)
    driver = FakeDriver()

    for entry in action_plan.entries:
        if entry.action not in action_plan.ordered_actions:
            continue
        result = executor.execute(
            journal,
            PhasedDriverAction(entry.phase, entry.action),
            observe=driver.observe,
            perform=driver.perform,
        )
        assert result.disposition is IdempotentExecutionDisposition.APPLIED
        journal = result.journal
    journal = store.complete(journal)

    assert [operation for operation, _key in driver.calls] == [
        "prepare-processor",
        "route-headset",
        "restore-output",
    ]
    assert len({key for _operation, key in driver.calls}) == 3
    assert journal.status == TransitionStatus.SUCCEEDED
    assert [entry["status"] for entry in journal.entries] == [
        JournalActionStatus.SUCCEEDED,
        JournalActionStatus.SUCCEEDED,
        JournalActionStatus.SUCCEEDED,
    ]


def test_event_storm_coalesces_before_one_latest_generation_converges(
    resolved_plan,
) -> None:
    queue = CoalescingReconciliationQueue(max_causes=8)
    for generation in range(1, 1001):
        queue.submit(
            ReconciliationWork(
                str(resolved_plan.graph_definition_id),
                generation,
                (f"runtime:{generation}",),
            )
        )
    latest = queue.take(timeout=0)
    driver = FakeDriver()
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=latest.generation)

    result = IdempotentActionExecutor(store).execute(
        journal,
        _action(ReconciliationPhase.ROUTE, "route-latest-world"),
        observe=driver.observe,
        perform=driver.perform,
    )

    assert latest.generation == 1000
    assert latest.causes[-1] == "runtime:1000"
    assert driver.calls[0][0] == "route-latest-world"
    assert result.disposition is IdempotentExecutionDisposition.APPLIED


def test_stale_generation_is_fenced_before_fake_driver_mutation() -> None:
    coordinator = OrchestrationGenerationCoordinator()
    first = coordinator.schedule(
        "graph:main",
        GenerationInput(1, "desired:1", 1, 1, 1),
        cause="startup",
    ).generation
    coordinator.schedule(
        "graph:main",
        GenerationInput(2, "desired:2", 2, 1, 2),
        cause="headset-connected",
    )
    driver = FakeDriver()

    with pytest.raises(StaleGenerationAbort):
        coordinator.require_current_before_unsafe_mutation(
            first,
            operation="route-headset",
        )

    assert driver.calls == []


def test_crash_after_external_success_recovers_without_second_driver_call(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=2)
    action = _action(ReconciliationPhase.PREPARE, "create-processor")
    driver = FakeDriver()
    store.begin_action(journal, action)
    driver.perform(action.action)

    directive = next(item for item in store.recover_incomplete() if item.journal_id == journal.pk)
    result = IdempotentActionExecutor(store).recover_uncertain(
        directive,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.disposition is IdempotentExecutionDisposition.UNCERTAIN_VERIFIED
    assert [operation for operation, _key in driver.calls] == ["create-processor"]


def test_partial_transition_failure_rolls_back_after_prior_action_was_journaled(
    resolved_plan,
) -> None:
    inverse = ActionRecoveryStep(
        DriverCommand("restore-speaker-route", {}),
        (_verification("restore-speaker-route"),),
        "Restore the last safe speakers route.",
    )
    route = _action(
        ReconciliationPhase.ROUTE,
        "route-headset",
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Restore speakers when headset routing fails.",
            inverse=inverse,
        ),
    )
    prepare = _action(ReconciliationPhase.PREPARE, "prepare-headset-profile")
    driver = FakeDriver(failures=("route-headset",))
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=3)
    executor = IdempotentActionExecutor(store)

    prepared = executor.execute(
        journal,
        prepare,
        observe=driver.observe,
        perform=driver.perform,
    )
    failed = executor.execute(
        prepared.journal,
        route,
        observe=driver.observe,
        perform=driver.perform,
    )
    assert failed.failure is not None
    recovered = TransitionRecoveryExecutor(store).recover(
        failed.journal,
        failed_action=route,
        failure=failed.failure,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert recovered.status is TransitionRecoveryStatus.ROLLED_BACK
    assert [operation for operation, _key in driver.calls] == [
        "prepare-headset-profile",
        "route-headset",
        "restore-speaker-route",
    ]
    assert recovered.journal.status == TransitionStatus.ROLLED_BACK
    assert [entry["status"] for entry in recovered.journal.entries[:-1]] == [
        JournalActionStatus.SUCCEEDED,
        JournalActionStatus.FAILED,
        JournalActionStatus.SUCCEEDED,
    ]
