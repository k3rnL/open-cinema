import pytest

from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionFailure,
    ActionFailureClassification,
    ActionPrecondition,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionRecoveryStep,
    ActionVerification,
    DriverAction,
    DriverActionError,
    DriverActionIdentity,
    DriverCommand,
    derive_action_idempotency_key,
)


def _verification(expected="endpoint:headset"):
    return ActionVerification(
        subject="stream:programme.target",
        operator=ActionAssertionOperator.EQUALS,
        expected=expected,
        description="Observe the selected target in a fresh runtime snapshot.",
    )


def _recovery():
    return ActionRecoveryPolicy(
        mode=ActionRecoveryMode.INVERSE_THEN_FALLBACK,
        reason="Restore the prior target, or mute the stream if restoration fails.",
        inverse=ActionRecoveryStep(
            command=DriverCommand("set-stream-target", {"target": "endpoint:speakers"}),
            verification=(_verification("endpoint:speakers"),),
            description="Restore the previously observed stream target.",
        ),
        safe_fallback=ActionRecoveryStep(
            command=DriverCommand("set-stream-mute", {"mute": True}),
            verification=(
                ActionVerification(
                    "stream:programme.mute",
                    ActionAssertionOperator.EQUALS,
                    True,
                ),
            ),
            description="Keep the affected stream muted.",
        ),
    )


def _action(arguments=None):
    identity = DriverActionIdentity(
        driver="wireplumber",
        resource_kind="stream",
        resource_id="stream:programme",
        operation="set-stream-target",
    )
    command = DriverCommand(
        "set-stream-target",
        arguments or {"target": "endpoint:headset", "generation": 4},
    )
    return DriverAction.create(
        identity=identity,
        command=command,
        intent_scope="plan:sha256:abc:generation:7",
        preconditions=(
            ActionPrecondition(
                "runtime.generation",
                ActionAssertionOperator.EQUALS,
                4,
                "Reject stale PipeWire objects.",
            ),
        ),
        timeout_seconds=2.5,
        verification=(_verification(),),
        recovery=_recovery(),
        metadata={"phase": "route", "managed": True},
    )


def test_driver_action_is_typed_immutable_and_round_trips() -> None:
    action = _action()

    assert action.identity.key == action.identity.key
    assert action.preconditions[0].expected == 4
    assert action.timeout_seconds == 2.5
    assert action.recovery.mode is ActionRecoveryMode.INVERSE_THEN_FALLBACK
    assert action.idempotency_key.startswith("action-v1:")
    with pytest.raises(TypeError):
        action.command.arguments["target"] = "endpoint:speakers"

    restored = DriverAction.from_document(action.to_document())

    assert restored == action
    assert restored.to_document() == action.to_document()


def test_idempotency_key_is_canonical_and_changes_with_intent() -> None:
    identity = DriverActionIdentity(
        "wireplumber",
        "node",
        "endpoint:main-speakers",
        "set-volume",
    )
    first = DriverCommand("set-volume", {"volume": 0.5, "channels": [1, 2]})
    reordered = DriverCommand("set-volume", {"channels": [1, 2], "volume": 0.5})

    first_key = derive_action_idempotency_key(
        identity,
        first,
        intent_scope="desired:9",
    )

    assert first_key == derive_action_idempotency_key(
        identity,
        reordered,
        intent_scope="desired:9",
    )
    assert first_key != derive_action_idempotency_key(
        identity,
        reordered,
        intent_scope="desired:10",
    )


def test_recovery_policy_requires_every_declared_step() -> None:
    with pytest.raises(ValueError, match="invalid safe fallback"):
        ActionRecoveryPolicy(
            mode=ActionRecoveryMode.INVERSE_THEN_FALLBACK,
            reason="Both recovery paths are required.",
            inverse=_recovery().inverse,
        )

    read_only = ActionRecoveryPolicy(
        mode=ActionRecoveryMode.NONE_REQUIRED,
        reason="This action only verifies observed state and performs no mutation.",
    )
    assert read_only.to_document()["inverse"] is None


@pytest.mark.parametrize(
    ("classification", "retryable", "reresolve", "blocks_unsuppress"),
    (
        (ActionFailureClassification.TRANSIENT, True, False, False),
        (ActionFailureClassification.PERMANENT, False, False, False),
        (ActionFailureClassification.STALE_PRECONDITION, False, True, False),
        (ActionFailureClassification.DEPENDENCY, True, False, False),
        (ActionFailureClassification.SAFETY, False, False, True),
    ),
)
def test_failures_have_explicit_reconciliation_semantics(
    classification,
    retryable,
    reresolve,
    blocks_unsuppress,
) -> None:
    failure = ActionFailure(
        classification=classification,
        code="test-failure",
        message="controlled failure",
        retry_after_seconds=0.25 if retryable else None,
    )

    assert failure.retryable is retryable
    assert failure.requires_reresolution is reresolve
    assert failure.blocks_unsuppress is blocks_unsuppress
    document = failure.to_document()
    assert document["classification"] == classification.value
    assert document["retryable"] is retryable


def test_driver_action_error_keeps_typed_action_and_failure() -> None:
    action = _action()
    failure = ActionFailure(
        ActionFailureClassification.DEPENDENCY,
        "wireplumber-disconnected",
        "The runtime connection was lost.",
        {"generation": 4},
        0.5,
    )

    error = DriverActionError(action, failure)

    assert error.action is action
    assert error.failure is failure
    assert "dependency driver action failure" in str(error)


def test_action_rejects_operation_mismatch_and_missing_verification() -> None:
    action = _action()
    with pytest.raises(ValueError, match="operations must match"):
        DriverAction(
            identity=action.identity,
            command=DriverCommand("set-volume", {"volume": 0.5}),
            preconditions=(),
            idempotency_key="action-v1:mismatch",
            timeout_seconds=1,
            verification=(_verification(),),
            recovery=action.recovery,
        )

    with pytest.raises(ValueError, match="verification"):
        DriverAction(
            identity=action.identity,
            command=action.command,
            preconditions=(),
            idempotency_key="action-v1:no-verification",
            timeout_seconds=1,
            verification=(),
            recovery=action.recovery,
        )
