from datetime import datetime, timezone

import pytest
from wyreplumber.runtime import (
    ConfirmationOperator,
    ConfirmationPredicateValue,
    MutationConfirmationValue,
    MutationFailureCode,
    MutationFailurePhase,
    MutationFailureValue,
    MutationOperation,
    MutationOutcome,
    MutationStatus,
    MutationTargetValue,
    RuntimeObjectKind,
)

from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionFailureClassification,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionError,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.wireplumber_driver import (
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    classify_wireplumber_failure,
)
from tests.test_endpoint_inventory_mapping import _snapshot


def _action(operation="set-node-mute"):
    identity = DriverActionIdentity("wireplumber", "node", "endpoint:headset", operation)
    return DriverAction.create(
        identity=identity,
        command=DriverCommand(operation, {"mute": True}),
        intent_scope="plan:wireplumber",
        timeout_seconds=1,
        verification=(
            ActionVerification(
                "endpoint.headset.mute",
                ActionAssertionOperator.EQUALS,
                True,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "The fake binding operation is idempotent.",
        ),
    )


def _target():
    return MutationTargetValue(RuntimeObjectKind.NODE, 20, {"parameter_id": "Props"})


def _confirmed_outcome():
    target = _target()
    predicate = ConfirmationPredicateValue(
        target,
        ConfirmationOperator.EQUALS,
        ("mute",),
        True,
    )
    confirmation = MutationConfirmationValue(
        generation=3,
        sequence=11,
        observed_at="2026-08-22T12:00:00Z",
        predicate=predicate,
        observation={"mute": True},
    )
    return MutationOutcome(
        request_id="request:mute",
        generation=3,
        operation=MutationOperation.SET_PARAMETER,
        status=MutationStatus.CONFIRMED,
        completed_at="2026-08-22T12:00:00Z",
        confirmations=(confirmation,),
    )


def _failed_outcome(code, phase, status, *, retryable=False):
    return MutationOutcome(
        request_id="request:failed",
        generation=3,
        operation=MutationOperation.SET_PARAMETER,
        status=status,
        completed_at="2026-08-22T12:00:00Z",
        failure=MutationFailureValue(
            phase,
            code,
            "controlled binding failure",
            retryable,
            {"native": "detached"},
        ),
    )


def test_adapter_checks_contract_observes_detached_snapshot_and_does_not_store_proxy() -> None:
    connection = object()
    checks = []
    captures = []
    runtime = _snapshot(generation=3)
    adapter = WirePlumberDriverAdapter(
        lambda: connection,
        snapshot_capture=lambda received: captures.append(received) or runtime,
        contract_checker=lambda minimum, maximum: checks.append((minimum, maximum))
        or {"contract": 1},
    )

    observed = adapter.observe_runtime()

    assert checks == [(1, 1)]
    assert captures == [connection]
    assert observed is runtime
    assert not hasattr(adapter, "connection")
    assert datetime.fromisoformat(observed.captured_at).utcoffset() == timezone.utc.utcoffset(None)


def test_adapter_dispatches_registered_control_and_returns_only_detached_document() -> None:
    connection = object()
    runtime = _snapshot(generation=3)
    registry = WirePlumberControlRegistry()
    calls = []
    registry.register(
        "set-node-mute",
        lambda received_connection, action, snapshot: calls.append(
            (received_connection, action, snapshot)
        )
        or _confirmed_outcome(),
    )
    adapter = WirePlumberDriverAdapter(
        lambda: connection,
        registry=registry,
        snapshot_capture=lambda _connection: runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )
    action = _action()

    result = adapter.perform(action)

    assert calls == [(connection, action, runtime)]
    assert result["status"] == "confirmed"
    assert result["runtimeGeneration"] == 3
    assert result["bindingOutcome"]["value_type"] == "mutation_outcome"
    assert result["staleSequenceRetries"] == 0
    assert all(value is not connection for value in result.values())


def test_adapter_recaptures_and_revalidates_after_stale_sequence() -> None:
    connection = object()
    runtime = _snapshot(generation=3)
    registry = WirePlumberControlRegistry()
    calls = []
    outcomes = [
        _failed_outcome(
            MutationFailureCode.STALE_SEQUENCE,
            MutationFailurePhase.PRECONDITION,
            MutationStatus.REJECTED,
        ),
        _confirmed_outcome(),
    ]
    registry.register(
        "set-node-mute",
        lambda received_connection, action, snapshot: calls.append(
            (received_connection, action, snapshot)
        )
        or outcomes.pop(0),
    )
    captures = []
    adapter = WirePlumberDriverAdapter(
        lambda: connection,
        registry=registry,
        snapshot_capture=lambda received: captures.append(received) or runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )
    action = _action()

    result = adapter.perform(action)

    assert captures == [connection, connection]
    assert calls[0][1].idempotency_key == action.idempotency_key
    assert calls[1][1].idempotency_key.endswith(":stale-sequence:1")
    assert result["status"] == "confirmed"
    assert result["staleSequenceRetries"] == 1


@pytest.mark.parametrize(
    ("code", "classification"),
    (
        (MutationFailureCode.STALE_GENERATION, ActionFailureClassification.STALE_PRECONDITION),
        (MutationFailureCode.TARGET_NOT_FOUND, ActionFailureClassification.STALE_PRECONDITION),
        (MutationFailureCode.RUNTIME_STOPPED, ActionFailureClassification.DEPENDENCY),
        (MutationFailureCode.OWNERSHIP_CONFLICT, ActionFailureClassification.SAFETY),
        (MutationFailureCode.CONFIRMATION_TIMEOUT, ActionFailureClassification.TRANSIENT),
        (MutationFailureCode.NOT_WRITABLE, ActionFailureClassification.PERMANENT),
    ),
)
def test_binding_failure_codes_map_to_reconciliation_classification(code, classification) -> None:
    assert classify_wireplumber_failure(code) is classification


def test_unsuccessful_binding_outcome_becomes_typed_driver_failure() -> None:
    registry = WirePlumberControlRegistry()
    registry.register(
        "set-node-mute",
        lambda _connection, _action, _snapshot: _failed_outcome(
            MutationFailureCode.STALE_GENERATION,
            MutationFailurePhase.PRECONDITION,
            MutationStatus.REJECTED,
        ),
    )
    adapter = WirePlumberDriverAdapter(
        lambda: object(),
        registry=registry,
        snapshot_capture=lambda _connection: _snapshot(generation=3),
        contract_checker=lambda _minimum, _maximum: None,
    )

    with pytest.raises(DriverActionError) as caught:
        adapter.perform(_action())

    failure = caught.value.failure
    assert failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert failure.code == "wireplumber:stale_generation"
    assert failure.details["bindingPhase"] == "precondition"
    assert failure.details["bindingDetails"] == {"native": "detached"}


def test_unregistered_operation_is_permanent_and_never_calls_connection() -> None:
    connections = []
    adapter = WirePlumberDriverAdapter(
        lambda: connections.append("called"),
        contract_checker=lambda _minimum, _maximum: None,
    )

    with pytest.raises(DriverActionError) as caught:
        adapter.perform(_action("future-operation"))

    assert caught.value.failure.classification is ActionFailureClassification.PERMANENT
    assert "unsupported-driver-operation" in caught.value.failure.code
    assert connections == []
