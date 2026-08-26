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
from core.orchestration.drift_reconciliation import (
    DriftDisposition,
    MovableStreamIntent,
    MovableStreamRoutingPolicy,
    ObservedRuntimeResource,
    RuntimeResourceOwnership,
    build_drift_reconciliation_plan,
)


def _action(resource_id, operation, fact, expected):
    identity = DriverActionIdentity(
        "wireplumber",
        "stream" if resource_id.startswith("stream:") else "managed-link",
        resource_id,
        operation,
    )
    return PhasedDriverAction(
        ReconciliationPhase.ROUTE,
        DriverAction.create(
            identity=identity,
            command=DriverCommand(operation, {"expected": expected}),
            intent_scope="plan:drift",
            timeout_seconds=1,
            verification=(ActionVerification(fact, ActionAssertionOperator.EQUALS, expected),),
            recovery=ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "The fake ensure action is idempotent.",
            ),
        ),
    )


def test_managed_drift_is_restored_but_satisfied_state_is_skipped() -> None:
    link = _action("link:main", "ensure-link", "link.main.connected", True)
    metadata = _action(
        "metadata:default-output",
        "set-default-output",
        "metadata.default-output.target",
        "endpoint:speakers",
    )

    plan = build_drift_reconciliation_plan(
        desired_managed_actions=(metadata, link),
        movable_streams=(),
        observed_resources=(),
        facts={
            "link.main.connected": False,
            "metadata.default-output.target": "endpoint:speakers",
        },
    )

    assert plan.actions == (link,)
    by_resource = {decision.resource_id: decision for decision in plan.decisions}
    assert by_resource["link:main"].disposition is DriftDisposition.RESTORE_MANAGED
    assert by_resource["metadata:default-output"].disposition is (DriftDisposition.SATISFIED)


def test_follow_default_clears_only_conflicting_explicit_stream_target() -> None:
    clear = _action(
        "stream:programme",
        "clear-stream-target",
        "stream.programme.target",
        None,
    )
    conflicting = MovableStreamIntent(
        "stream:programme",
        MovableStreamRoutingPolicy.FOLLOW_DEFAULT,
        current_target="endpoint:speakers",
        default_target="endpoint:speakers",
        desired_target=None,
        has_explicit_target=True,
        clear_target_action=clear,
    )
    following = MovableStreamIntent(
        "stream:music",
        MovableStreamRoutingPolicy.FOLLOW_DEFAULT,
        current_target=None,
        default_target="endpoint:speakers",
        desired_target=None,
        has_explicit_target=False,
        clear_target_action=_action(
            "stream:music",
            "clear-stream-target",
            "stream.music.target",
            None,
        ),
    )

    plan = build_drift_reconciliation_plan(
        desired_managed_actions=(),
        movable_streams=(following, conflicting),
        observed_resources=(),
        facts={},
    )

    assert plan.actions == (clear,)
    assert "default policy applies" in next(
        decision.reason for decision in plan.decisions if decision.resource_id == "stream:programme"
    )


def test_explicit_target_policy_restores_movable_stream() -> None:
    target = _action(
        "stream:programme",
        "set-stream-target",
        "stream.programme.target",
        "endpoint:headset",
    )
    stream = MovableStreamIntent(
        "stream:programme",
        MovableStreamRoutingPolicy.EXPLICIT_TARGET,
        current_target="endpoint:speakers",
        default_target="endpoint:speakers",
        desired_target="endpoint:headset",
        has_explicit_target=True,
        set_target_action=target,
    )

    plan = build_drift_reconciliation_plan(
        desired_managed_actions=(),
        movable_streams=(stream,),
        observed_resources=(),
        facts={},
    )

    assert plan.actions == (target,)
    assert plan.decisions[0].disposition is DriftDisposition.RESTORE_STREAM_POLICY


def test_unmanaged_resources_are_visible_but_never_become_actions() -> None:
    browser = ObservedRuntimeResource(
        "wireplumber",
        "stream",
        "stream:browser",
        RuntimeResourceOwnership.UNMANAGED,
        {"target": "endpoint:speakers"},
    )

    plan = build_drift_reconciliation_plan(
        desired_managed_actions=(),
        movable_streams=(),
        observed_resources=(browser,),
        facts={},
    )

    assert plan.actions == ()
    assert plan.unmanaged_resource_keys == (browser.key,)
    assert plan.decisions[0].ownership is RuntimeResourceOwnership.UNMANAGED
    assert plan.decisions[0].disposition is DriftDisposition.OBSERVE_ONLY
    assert "never mutated or deleted" in plan.decisions[0].reason


def test_observe_only_stream_respects_external_target_choice() -> None:
    stream = MovableStreamIntent(
        "stream:guest",
        MovableStreamRoutingPolicy.OBSERVE_ONLY,
        current_target="endpoint:external",
        default_target="endpoint:speakers",
        desired_target=None,
        has_explicit_target=True,
    )

    plan = build_drift_reconciliation_plan(
        desired_managed_actions=(),
        movable_streams=(stream,),
        observed_resources=(),
        facts={},
    )

    assert plan.actions == ()
    assert plan.decisions[0].disposition is DriftDisposition.OBSERVE_ONLY
