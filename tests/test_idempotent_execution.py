import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanStatus,
)
from core.orchestration.action_planning import PhasedDriverAction, ReconciliationPhase
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.idempotent_execution import (
    IdempotentActionExecutor,
    IdempotentExecutionDisposition,
)
from core.orchestration.transition_journal import (
    JournalActionStatus,
    TransitionJournalStore,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def resolved_plan():
    author = get_user_model().objects.create_user(username="idempotency-author")
    graph = GraphDefinition.objects.create(name="Idempotency graph", owner=author)
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


def _action(resource_kind):
    resource_id = f"managed:{resource_kind}"
    operation = f"ensure-{resource_kind}"
    identity = DriverActionIdentity(
        "fake-driver",
        resource_kind,
        resource_id,
        operation,
    )
    return PhasedDriverAction(
        ReconciliationPhase.PREPARE,
        DriverAction.create(
            identity=identity,
            command=DriverCommand(operation, {"managedId": resource_id}),
            intent_scope="plan:idempotency",
            timeout_seconds=1,
            verification=(
                ActionVerification(
                    f"resource.{resource_id}.exists",
                    ActionAssertionOperator.EQUALS,
                    True,
                ),
            ),
            recovery=ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "The fake driver uses an idempotent ensure operation.",
            ),
        ),
    )


class FakeEnsureDriver:
    def __init__(self):
        self.resources = set()
        self.calls = []

    def observe(self, action):
        return {
            f"resource.{action.identity.resource_id}.exists": (
                action.identity.resource_id in self.resources
            )
        }

    def perform(self, action):
        self.calls.append(action.idempotency_key)
        self.resources.add(action.identity.resource_id)
        return self.observe(action)


@pytest.mark.parametrize("resource_kind", ("processor", "metadata", "managed-link"))
def test_already_satisfied_resource_is_skipped_without_duplicate_mutation(
    resolved_plan,
    resource_kind,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=1)
    phased = _action(resource_kind)
    driver = FakeEnsureDriver()
    driver.resources.add(phased.action.identity.resource_id)

    result = IdempotentActionExecutor(store).execute(
        journal,
        phased,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.disposition is IdempotentExecutionDisposition.ALREADY_SATISFIED
    assert driver.calls == []
    assert result.journal.entries[-1]["status"] == (JournalActionStatus.ALREADY_SATISFIED)


@pytest.mark.parametrize("resource_kind", ("processor", "metadata", "managed-link"))
def test_uncertain_success_is_verified_without_duplicate_retry(
    resolved_plan,
    resource_kind,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=2)
    phased = _action(resource_kind)
    driver = FakeEnsureDriver()
    store.begin_action(journal, phased)
    driver.perform(phased.action)  # External mutation succeeded; process dies before outcome.

    directive = next(item for item in store.recover_incomplete() if item.journal_id == journal.pk)
    result = IdempotentActionExecutor(store).recover_uncertain(
        directive,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.disposition is IdempotentExecutionDisposition.UNCERTAIN_VERIFIED
    assert driver.calls == [phased.action.idempotency_key]
    assert len(driver.resources) == 1
    assert result.journal.entries[-1]["status"] == (JournalActionStatus.ALREADY_SATISFIED)


def test_uncertain_unsatisfied_action_retries_with_identical_idempotency_key(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=3)
    phased = _action("processor")
    driver = FakeEnsureDriver()
    store.begin_action(journal, phased)
    directive = next(item for item in store.recover_incomplete() if item.journal_id == journal.pk)

    result = IdempotentActionExecutor(store).recover_uncertain(
        directive,
        observe=driver.observe,
        perform=driver.perform,
    )

    assert result.disposition is IdempotentExecutionDisposition.UNCERTAIN_RETRIED
    assert result.idempotency_key == phased.action.idempotency_key
    assert driver.calls == [phased.action.idempotency_key]
    assert result.journal.entries[-1]["status"] == JournalActionStatus.SUCCEEDED


def test_driver_return_is_not_success_until_fresh_verification_passes(
    resolved_plan,
) -> None:
    store = TransitionJournalStore()
    journal = store.start(resolved_plan, generation=4)
    phased = _action("managed-link")
    driver = FakeEnsureDriver()

    result = IdempotentActionExecutor(store).execute(
        journal,
        phased,
        observe=driver.observe,
        perform=lambda _action: {},
    )

    assert result.disposition is IdempotentExecutionDisposition.FAILED
    assert result.journal.entries[-1]["failure"]["classification"] == "safety"
    assert result.journal.entries[-1]["failure"]["code"] == ("postcondition-not-satisfied")
