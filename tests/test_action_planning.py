from core.orchestration.action_planning import (
    ActionDiffDisposition,
    ObservedManagedResource,
    ObservedManagedState,
    PhasedDriverAction,
    RECONCILIATION_PHASE_ORDER,
    ReconciliationPhase,
    ResolvedDriverIntent,
    build_reconciliation_action_plan,
)
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.camilladsp_driver import plan_camilladsp_transition


def _action(phase, resource_id, *, operation=None, expected=True):
    operation = operation or f"{phase.value}-resource"
    identity = DriverActionIdentity(
        "test-driver",
        "audio-resource",
        resource_id,
        operation,
    )
    command = DriverCommand(operation, {"enabled": expected})
    return PhasedDriverAction(
        phase,
        DriverAction.create(
            identity=identity,
            command=command,
            intent_scope="plan:one",
            timeout_seconds=1,
            verification=(
                ActionVerification(
                    f"resource.{resource_id}.enabled",
                    ActionAssertionOperator.EQUALS,
                    expected,
                ),
            ),
            recovery=ActionRecoveryPolicy(
                ActionRecoveryMode.NONE_REQUIRED,
                "The test driver action is declarative and has no mutation.",
            ),
        ),
    )


def _cleanup(resource_id):
    return _action(
        ReconciliationPhase.CLEANUP,
        resource_id,
        operation="remove-resource",
        expected=False,
    ).action


def test_diff_orders_required_actions_by_safety_phase_and_stable_identity() -> None:
    actions = tuple(
        _action(phase, f"resource:{index}")
        for index, phase in reversed(tuple(enumerate(RECONCILIATION_PHASE_ORDER)))
    )
    intent = ResolvedDriverIntent("plan-digest", 3, actions)
    observed = ObservedManagedState(2, 17, {})

    plan = build_reconciliation_action_plan(intent, observed)

    assert tuple(entry.phase for entry in plan.entries) == RECONCILIATION_PHASE_ORDER
    assert all(entry.disposition is ActionDiffDisposition.REQUIRED for entry in plan.entries)
    assert plan.ordered_actions == tuple(entry.action for entry in plan.entries)


def test_satisfied_actions_are_explained_and_not_executed() -> None:
    prepare = _action(ReconciliationPhase.PREPARE, "processor:decoder")
    route = _action(ReconciliationPhase.ROUTE, "stream:programme")
    intent = ResolvedDriverIntent("plan-digest", 3, (route, prepare))
    observed = ObservedManagedState(
        2,
        18,
        {"resource.processor:decoder.enabled": True},
    )

    plan = build_reconciliation_action_plan(intent, observed)

    assert plan.entries[0].disposition is ActionDiffDisposition.ALREADY_SATISFIED
    assert plan.entries[0].reasons == ("all-verifications-satisfied",)
    assert plan.ordered_actions == (route.action,)


def test_cleanup_only_targets_owned_resources_absent_from_desired_intent() -> None:
    desired = _action(ReconciliationPhase.ROUTE, "stream:programme")
    owned_obsolete = ObservedManagedResource(
        "test-driver",
        "audio-resource",
        "processor:old",
        True,
        {"enabled": True},
        _cleanup("processor:old"),
    )
    unmanaged = ObservedManagedResource(
        "external",
        "audio-resource",
        "stream:browser",
        False,
        {"enabled": True},
        None,
    )
    observed = ObservedManagedState(2, 19, {}, (unmanaged, owned_obsolete))

    plan = build_reconciliation_action_plan(
        ResolvedDriverIntent("plan-digest", 3, (desired,)),
        observed,
    )

    assert plan.actions_for_phase(ReconciliationPhase.CLEANUP) == (owned_obsolete.cleanup_action,)
    assert plan.entries[-1].disposition is ActionDiffDisposition.CLEANUP
    assert plan.unmanaged_resource_keys == (unmanaged.key,)
    assert all(action.identity.resource_id != "stream:browser" for action in plan.ordered_actions)


def test_owned_resource_without_safe_cleanup_is_diagnostic_not_guessed() -> None:
    orphan = ObservedManagedResource(
        "test-driver",
        "audio-resource",
        "processor:unknown",
        True,
        {"enabled": True},
    )

    plan = build_reconciliation_action_plan(
        ResolvedDriverIntent("empty-plan", 1, ()),
        ObservedManagedState(1, 0, {}, (orphan,)),
    )

    assert plan.ordered_actions == ()
    assert plan.missing_cleanup_resource_keys == (orphan.key,)


def test_diff_is_deterministic_for_equivalent_input_ordering() -> None:
    first_action = _action(ReconciliationPhase.ROUTE, "stream:a")
    second_action = _action(ReconciliationPhase.ROUTE, "stream:b")
    first_resource = ObservedManagedResource(
        "external", "stream", "unmanaged:a", False, {"state": "running"}
    )
    second_resource = ObservedManagedResource(
        "external", "stream", "unmanaged:b", False, {"state": "running"}
    )

    first = build_reconciliation_action_plan(
        ResolvedDriverIntent("same-plan", 4, (second_action, first_action)),
        ObservedManagedState(3, 20, {}, (second_resource, first_resource)),
    )
    second = build_reconciliation_action_plan(
        ResolvedDriverIntent("same-plan", 4, (first_action, second_action)),
        ObservedManagedState(3, 20, {}, (first_resource, second_resource)),
    )

    assert first.digest == second.digest
    assert first.to_document() == second.to_document()


def test_content_selected_profile_change_keeps_safe_downstream_phases() -> None:
    previous_digest = "a" * 64
    selected_digest = "b" * 64
    actions = plan_camilladsp_transition(
        instance_id="room",
        intent_scope="content-rule:dts",
        configuration_digest=selected_digest,
        output_target="main-speakers",
        material_format_change=True,
    )
    observed = ObservedManagedState(
        7,
        42,
        {
            "processor.room.validation": "valid",
            "processor.room.outputSuppressed": False,
            "processor.room.activeConfigurationDigest": previous_digest,
            "processor.room.outputTarget": "main-speakers",
            "processor.room.readiness": True,
        },
    )

    plan = build_reconciliation_action_plan(
        ResolvedDriverIntent("content-plan", 9, actions),
        observed,
    )

    assert tuple(entry.phase for entry in plan.entries) == (
        ReconciliationPhase.PREPARE,
        ReconciliationPhase.SUPPRESS,
        ReconciliationPhase.CONFIGURE,
        ReconciliationPhase.ROUTE,
        ReconciliationPhase.VERIFY,
        ReconciliationPhase.UNSUPPRESS,
    )
    assert plan.entries[0].disposition is ActionDiffDisposition.ALREADY_SATISFIED
    assert all(entry.disposition is ActionDiffDisposition.REQUIRED for entry in plan.entries[1:])
    assert plan.entries[-1].reasons == ("prerequisite-action-required",)
