import pytest

from core.orchestration.action_retry import (
    ActionFailureHandling,
    ActionRetryController,
    ActionRetryPolicy,
    ActionRetryTerminated,
    run_with_action_retry,
)
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


def _action(resource_id="processor:decoder"):
    identity = DriverActionIdentity(
        "fake-driver",
        "processor",
        resource_id,
        "ensure-running",
    )
    return DriverAction.create(
        identity=identity,
        command=DriverCommand("ensure-running", {}),
        intent_scope="plan:retry",
        timeout_seconds=1,
        verification=(
            ActionVerification(
                f"resource.{resource_id}.running",
                ActionAssertionOperator.EQUALS,
                True,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "The fake action is idempotent.",
        ),
    )


def _failure(classification, *, retry_after=None):
    return ActionFailure(
        classification,
        "controlled-failure",
        "controlled test failure",
        retry_after_seconds=retry_after,
    )


def _controller(max_attempts=3):
    return ActionRetryController(
        ActionRetryPolicy(
            max_attempts=max_attempts,
            initial_seconds=0.25,
            max_seconds=1,
            multiplier=2,
            jitter_ratio=0.5,
        ),
        random_value=lambda: 0.5,
    )


def test_transient_failures_retry_with_bounded_exponential_delay() -> None:
    action = _action()
    calls = []
    waits = []

    def operation(received):
        calls.append(received)
        if len(calls) < 3:
            raise DriverActionError(
                received,
                _failure(ActionFailureClassification.TRANSIENT),
            )
        return "ready"

    result = run_with_action_retry(
        action,
        operation,
        _controller(),
        wait=waits.append,
    )

    assert result == "ready"
    assert calls == [action, action, action]
    assert waits == [0.25, 0.5]


def test_dependency_retry_honors_hint_without_exceeding_bound() -> None:
    action = _action()
    controller = _controller(max_attempts=4)

    first = controller.record_failure(
        action,
        _failure(ActionFailureClassification.DEPENDENCY, retry_after=0.8),
    )
    second = controller.record_failure(
        action,
        _failure(ActionFailureClassification.DEPENDENCY, retry_after=5),
    )

    assert first.delay_seconds == 0.8
    assert second.delay_seconds == 1


@pytest.mark.parametrize(
    ("classification", "handling"),
    (
        (ActionFailureClassification.STALE_PRECONDITION, ActionFailureHandling.RERESOLVE),
        (ActionFailureClassification.PERMANENT, ActionFailureHandling.STOP_PERMANENT),
        (ActionFailureClassification.SAFETY, ActionFailureHandling.SAFE_RECOVERY),
    ),
)
def test_non_retryable_failures_have_distinct_next_steps(classification, handling) -> None:
    decision = _controller().record_failure(_action(), _failure(classification))

    assert decision.handling is handling
    assert decision.delay_seconds is None
    assert decision.next_attempt is None


def test_retry_budget_is_bounded() -> None:
    action = _action()
    controller = _controller(max_attempts=2)

    first = controller.record_failure(
        action,
        _failure(ActionFailureClassification.TRANSIENT),
    )
    exhausted = controller.record_failure(
        action,
        _failure(ActionFailureClassification.TRANSIENT),
    )

    assert first.handling is ActionFailureHandling.RETRY_SAME_ACTION
    assert exhausted.handling is ActionFailureHandling.RETRIES_EXHAUSTED
    assert exhausted.failed_attempt == 2


def test_retry_runner_stops_immediately_for_permanent_failure() -> None:
    action = _action()
    calls = []

    def operation(received):
        calls.append(received)
        raise DriverActionError(
            received,
            _failure(ActionFailureClassification.PERMANENT),
        )

    with pytest.raises(ActionRetryTerminated) as caught:
        run_with_action_retry(action, operation, _controller(), wait=lambda _delay: None)

    assert calls == [action]
    assert caught.value.decision.handling is ActionFailureHandling.STOP_PERMANENT


def test_success_clears_attempt_budget_independently_per_action() -> None:
    controller = _controller(max_attempts=2)
    first = _action("processor:first")
    second = _action("processor:second")
    controller.record_failure(first, _failure(ActionFailureClassification.TRANSIENT))
    second_decision = controller.record_failure(
        second,
        _failure(ActionFailureClassification.TRANSIENT),
    )
    controller.clear(first)
    first_again = controller.record_failure(
        first,
        _failure(ActionFailureClassification.TRANSIENT),
    )

    assert second_decision.failed_attempt == 1
    assert first_again.failed_attempt == 1
