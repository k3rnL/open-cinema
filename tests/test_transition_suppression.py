import pytest

from core.orchestration.action_planning import (
    ReconciliationPhase,
    ResolvedDriverIntent,
)
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionVerification,
)
from core.orchestration.transition_suppression import (
    SuppressionCapability,
    SuppressionTarget,
    SuppressionUnavailable,
    UnsafeUnsuppressionError,
    UnsuppressionGate,
    build_transition_suppression_plan,
    evaluate_unsuppression,
    require_safe_unsuppression,
)


def _gate():
    return UnsuppressionGate(
        runtime_verification=(
            ActionVerification(
                "runtime.route.ready",
                ActionAssertionOperator.EQUALS,
                True,
            ),
        ),
        processor_verification=(
            ActionVerification(
                "processor.camilladsp.ready",
                ActionAssertionOperator.EQUALS,
                True,
            ),
        ),
    )


def _plan(target, *, preference=None):
    arguments = {}
    if preference is not None:
        arguments["preference"] = preference
    return build_transition_suppression_plan(
        (target,),
        _gate(),
        intent_scope="transition:7",
        timeout_seconds=2,
        fade_duration_seconds=0.1,
        **arguments,
    )


def test_fade_is_preferred_and_restores_exact_observed_volume() -> None:
    plan = _plan(
        SuppressionTarget(
            "wireplumber",
            "node",
            "endpoint:main-speakers",
            (SuppressionCapability.MUTE, SuppressionCapability.FADE),
            volume=0.65,
            muted=False,
        )
    )

    suppress = plan.suppress_actions[0]
    unsuppress = plan.unsuppress_actions[0]
    assert suppress.phase is ReconciliationPhase.SUPPRESS
    assert suppress.action.command.to_document() == {
        "operation": "fade-volume",
        "arguments": {"durationSeconds": 0.1, "from": 0.65, "to": 0.0},
    }
    assert unsuppress.phase is ReconciliationPhase.UNSUPPRESS
    assert unsuppress.action.command.arguments["to"] == 0.65
    assert plan.strategies == (("endpoint:main-speakers", SuppressionCapability.FADE),)
    intent = ResolvedDriverIntent(
        "plan:suppression",
        1,
        plan.suppress_actions + plan.unsuppress_actions,
    )
    assert len({item.action.identity.key for item in intent.actions}) == 2


def test_deployment_preference_can_choose_mute_and_pause_is_fallback() -> None:
    mute_plan = _plan(
        SuppressionTarget(
            "wireplumber",
            "node",
            "endpoint:main-speakers",
            (SuppressionCapability.FADE, SuppressionCapability.MUTE),
            volume=0.5,
            muted=False,
        ),
        preference=(SuppressionCapability.MUTE, SuppressionCapability.FADE),
    )
    pause_plan = _plan(
        SuppressionTarget(
            "decoder",
            "processor",
            "decoder:tv",
            (SuppressionCapability.PAUSE,),
            paused=False,
        )
    )

    assert mute_plan.suppress_actions[0].action.command.operation == "set-mute"
    assert mute_plan.unsuppress_actions[0].action.command.arguments["mute"] is False
    assert pause_plan.suppress_actions[0].action.command.operation == "set-paused"
    assert pause_plan.unsuppress_actions[0].action.command.arguments["paused"] is False


def test_unknown_state_cannot_create_a_guessed_suppression_action() -> None:
    target = SuppressionTarget(
        "wireplumber",
        "node",
        "endpoint:main-speakers",
        (SuppressionCapability.MUTE,),
        muted=None,
    )

    with pytest.raises(SuppressionUnavailable, match="known observed state"):
        _plan(target)


def test_unsuppression_requires_both_runtime_and_processor_verification() -> None:
    plan = _plan(
        SuppressionTarget(
            "wireplumber",
            "node",
            "endpoint:main-speakers",
            (SuppressionCapability.MUTE,),
            muted=False,
        )
    )

    missing_processor = evaluate_unsuppression(plan, {"runtime.route.ready": True})
    assert missing_processor.allowed is False
    assert missing_processor.reasons == ("verification-unsatisfied:processor.camilladsp.ready",)
    with pytest.raises(UnsafeUnsuppressionError):
        require_safe_unsuppression(plan, {"runtime.route.ready": True})

    released = require_safe_unsuppression(
        plan,
        {
            "runtime.route.ready": True,
            "processor.camilladsp.ready": True,
        },
    )
    assert released == plan.unsuppress_actions


def test_gate_cannot_omit_runtime_or_processor_health() -> None:
    check = ActionVerification(
        "runtime.ready",
        ActionAssertionOperator.EQUALS,
        True,
    )
    with pytest.raises(ValueError, match="processor_verification"):
        UnsuppressionGate((check,), ())
