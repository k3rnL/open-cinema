from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .action_planning import (
    PhasedDriverAction,
    ReconciliationPhase,
    evaluate_verifications,
)
from .driver_actions import (
    ActionAssertionOperator,
    ActionPrecondition,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionRecoveryStep,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)


class SuppressionCapability(StrEnum):
    FADE = "fade"
    MUTE = "mute"
    PAUSE = "pause"


class SuppressionUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SuppressionTarget:
    driver: str
    resource_kind: str
    resource_id: str
    capabilities: tuple[SuppressionCapability, ...]
    volume: float | None = None
    muted: bool | None = None
    paused: bool | None = None
    preconditions: tuple[ActionPrecondition, ...] = ()

    def __post_init__(self) -> None:
        for field in ("driver", "resource_kind", "resource_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        capabilities = tuple(
            dict.fromkeys(SuppressionCapability(item) for item in self.capabilities)
        )
        if not capabilities:
            raise SuppressionUnavailable("suppression target declares no safe capability")
        object.__setattr__(self, "capabilities", capabilities)
        if self.volume is not None and (
            isinstance(self.volume, bool)
            or not isinstance(self.volume, (int, float))
            or not 0 <= self.volume <= 1
        ):
            raise ValueError("volume must be between zero and one or null")
        for field in ("muted", "paused"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{field} must be a boolean or null")
        preconditions = tuple(self.preconditions)
        if any(not isinstance(item, ActionPrecondition) for item in preconditions):
            raise TypeError("preconditions must contain ActionPrecondition values")
        object.__setattr__(self, "preconditions", preconditions)


@dataclass(frozen=True, slots=True)
class UnsuppressionGate:
    runtime_verification: tuple[ActionVerification, ...]
    processor_verification: tuple[ActionVerification, ...]

    def __post_init__(self) -> None:
        for field in ("runtime_verification", "processor_verification"):
            verification = tuple(getattr(self, field))
            if not verification or any(
                not isinstance(item, ActionVerification) for item in verification
            ):
                raise ValueError(f"{field} must contain typed verification assertions")
            object.__setattr__(self, field, verification)

    @property
    def verification(self) -> tuple[ActionVerification, ...]:
        return self.runtime_verification + self.processor_verification


@dataclass(frozen=True, slots=True)
class UnsuppressionDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitionSuppressionPlan:
    suppress_actions: tuple[PhasedDriverAction, ...]
    unsuppress_actions: tuple[PhasedDriverAction, ...]
    strategies: tuple[tuple[str, SuppressionCapability], ...]
    gate: UnsuppressionGate


class UnsafeUnsuppressionError(RuntimeError):
    def __init__(self, decision: UnsuppressionDecision) -> None:
        self.decision = decision
        super().__init__("unsuppression blocked: " + ", ".join(decision.reasons))


def _verification(subject: str, expected) -> ActionVerification:
    return ActionVerification(subject, ActionAssertionOperator.EQUALS, expected)


def _strategy(
    target: SuppressionTarget,
    preference: tuple[SuppressionCapability, ...],
) -> SuppressionCapability:
    available = set(target.capabilities)
    for candidate in preference:
        if candidate not in available:
            continue
        if candidate is SuppressionCapability.FADE and target.volume is None:
            continue
        if candidate is SuppressionCapability.MUTE and target.muted is None:
            continue
        if candidate is SuppressionCapability.PAUSE and target.paused is None:
            continue
        return candidate
    raise SuppressionUnavailable(
        f"target {target.resource_id!r} has no capability with known observed state"
    )


def _commands(
    target: SuppressionTarget,
    strategy: SuppressionCapability,
    *,
    fade_duration_seconds: float,
) -> tuple[DriverCommand, ActionVerification, DriverCommand, ActionVerification]:
    prefix = f"resource.{target.resource_id}"
    if strategy is SuppressionCapability.FADE:
        suppress = DriverCommand(
            "fade-volume",
            {
                "from": target.volume,
                "to": 0.0,
                "durationSeconds": fade_duration_seconds,
            },
        )
        restore = DriverCommand(
            "fade-volume",
            {
                "from": 0.0,
                "to": target.volume,
                "durationSeconds": fade_duration_seconds,
            },
        )
        return (
            suppress,
            _verification(f"{prefix}.volume", 0.0),
            restore,
            _verification(f"{prefix}.volume", target.volume),
        )
    if strategy is SuppressionCapability.MUTE:
        suppress = DriverCommand("set-mute", {"mute": True})
        restore = DriverCommand("set-mute", {"mute": target.muted})
        return (
            suppress,
            _verification(f"{prefix}.mute", True),
            restore,
            _verification(f"{prefix}.mute", target.muted),
        )
    suppress = DriverCommand("set-paused", {"paused": True})
    restore = DriverCommand("set-paused", {"paused": target.paused})
    return (
        suppress,
        _verification(f"{prefix}.paused", True),
        restore,
        _verification(f"{prefix}.paused", target.paused),
    )


def _recovery_step(
    command: DriverCommand,
    verification: ActionVerification,
    description: str,
) -> ActionRecoveryStep:
    return ActionRecoveryStep(command, (verification,), description)


def _paired_actions(
    target: SuppressionTarget,
    strategy: SuppressionCapability,
    *,
    intent_scope: str,
    timeout_seconds: float,
    fade_duration_seconds: float,
) -> tuple[PhasedDriverAction, PhasedDriverAction]:
    suppress, suppressed, restore, restored = _commands(
        target,
        strategy,
        fade_duration_seconds=fade_duration_seconds,
    )
    suppress_action = DriverAction.create(
        identity=DriverActionIdentity(
            target.driver,
            target.resource_kind,
            target.resource_id,
            suppress.operation,
            "suppress",
        ),
        command=suppress,
        intent_scope=f"{intent_scope}:suppress",
        preconditions=target.preconditions,
        timeout_seconds=timeout_seconds,
        verification=(suppressed,),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Restore the exact observed state if transition preparation aborts.",
            inverse=_recovery_step(
                restore,
                restored,
                "Restore the target's pre-transition state.",
            ),
        ),
        metadata={"suppressionStrategy": strategy.value},
    )
    unsuppress_action = DriverAction.create(
        identity=DriverActionIdentity(
            target.driver,
            target.resource_kind,
            target.resource_id,
            restore.operation,
            "unsuppress",
        ),
        command=restore,
        intent_scope=f"{intent_scope}:unsuppress",
        preconditions=target.preconditions,
        timeout_seconds=timeout_seconds,
        verification=(restored,),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.SAFE_FALLBACK,
            "Return to suppression if restoring audible output cannot be verified.",
            safe_fallback=_recovery_step(
                suppress,
                suppressed,
                "Keep the affected target safely suppressed.",
            ),
        ),
        metadata={"suppressionStrategy": strategy.value},
    )
    return (
        PhasedDriverAction(ReconciliationPhase.SUPPRESS, suppress_action),
        PhasedDriverAction(ReconciliationPhase.UNSUPPRESS, unsuppress_action),
    )


def build_transition_suppression_plan(
    targets: Sequence[SuppressionTarget],
    gate: UnsuppressionGate,
    *,
    intent_scope: str,
    timeout_seconds: float,
    fade_duration_seconds: float,
    preference: Sequence[SuppressionCapability] = (
        SuppressionCapability.FADE,
        SuppressionCapability.MUTE,
        SuppressionCapability.PAUSE,
    ),
) -> TransitionSuppressionPlan:
    if not isinstance(gate, UnsuppressionGate):
        raise TypeError("gate must be an UnsuppressionGate")
    if not isinstance(intent_scope, str) or not intent_scope:
        raise ValueError("intent_scope must be a non-empty string")
    for field, value in (
        ("timeout_seconds", timeout_seconds),
        ("fade_duration_seconds", fade_duration_seconds),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{field} must be a positive number")
    targets = tuple(targets)
    if not targets or any(not isinstance(item, SuppressionTarget) for item in targets):
        raise ValueError("targets must contain SuppressionTarget values")
    preference = tuple(dict.fromkeys(SuppressionCapability(item) for item in preference))
    if not preference:
        raise ValueError("suppression preference must not be empty")
    pairs = []
    strategies = []
    for target in targets:
        selected = _strategy(target, preference)
        pairs.append(
            _paired_actions(
                target,
                selected,
                intent_scope=intent_scope,
                timeout_seconds=timeout_seconds,
                fade_duration_seconds=fade_duration_seconds,
            )
        )
        strategies.append((target.resource_id, selected))
    pairs.sort(key=lambda pair: pair[0].action.identity.resource_key)
    strategies.sort(key=lambda item: item[0])
    return TransitionSuppressionPlan(
        suppress_actions=tuple(pair[0] for pair in pairs),
        unsuppress_actions=tuple(pair[1] for pair in pairs),
        strategies=tuple(strategies),
        gate=gate,
    )


def evaluate_unsuppression(
    plan: TransitionSuppressionPlan,
    fresh_facts: Mapping[str, object],
) -> UnsuppressionDecision:
    if not isinstance(plan, TransitionSuppressionPlan):
        raise TypeError("plan must be a TransitionSuppressionPlan")
    allowed, reasons = evaluate_verifications(plan.gate.verification, fresh_facts)
    return UnsuppressionDecision(allowed, reasons)


def require_safe_unsuppression(
    plan: TransitionSuppressionPlan,
    fresh_facts: Mapping[str, object],
) -> tuple[PhasedDriverAction, ...]:
    decision = evaluate_unsuppression(plan, fresh_facts)
    if not decision.allowed:
        raise UnsafeUnsuppressionError(decision)
    return plan.unsuppress_actions
