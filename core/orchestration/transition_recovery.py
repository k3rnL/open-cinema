from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from api.models import TransitionJournal, TransitionStatus

from .action_planning import PhasedDriverAction, ReconciliationPhase
from .driver_actions import (
    ActionFailure,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionRecoveryStep,
    DriverAction,
    DriverActionIdentity,
)
from .idempotent_execution import (
    IdempotentActionExecutor,
    IdempotentExecutionDisposition,
    IdempotentExecutionResult,
)
from .transition_journal import TransitionJournalStore


class TransitionRecoveryStatus(StrEnum):
    ROLLED_BACK = "rolled-back"
    DEGRADED_FALLBACK = "degraded-fallback"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeclaredDegradedFallback:
    fallback_id: str
    reason: str
    actions: tuple[PhasedDriverAction, ...]

    def __post_init__(self) -> None:
        for field in ("fallback_id", "reason"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        actions = tuple(self.actions)
        if not actions or any(not isinstance(item, PhasedDriverAction) for item in actions):
            raise ValueError("degraded fallback must contain typed phased actions")
        object.__setattr__(self, "actions", actions)


@dataclass(frozen=True, slots=True)
class TransitionRecoveryResult:
    status: TransitionRecoveryStatus
    journal: TransitionJournal
    attempts: tuple[IdempotentExecutionResult, ...]
    fallback_id: str | None
    reasons: tuple[str, ...]


def _materialize_recovery_action(
    original: DriverAction,
    step: ActionRecoveryStep,
    *,
    intent_scope: str,
    qualifier: str,
    phase: ReconciliationPhase,
) -> PhasedDriverAction:
    action = DriverAction.create(
        identity=DriverActionIdentity(
            original.identity.driver,
            original.identity.resource_kind,
            original.identity.resource_id,
            step.command.operation,
            qualifier,
        ),
        command=step.command,
        intent_scope=intent_scope,
        preconditions=original.preconditions,
        timeout_seconds=original.timeout_seconds,
        verification=step.verification,
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "This is already a terminal recovery step; failure keeps the path degraded.",
        ),
        metadata={
            "recoveryFor": original.idempotency_key,
            "description": step.description,
        },
    )
    return PhasedDriverAction(phase, action)


class TransitionRecoveryExecutor:
    def __init__(
        self,
        journal_store: TransitionJournalStore | None = None,
        action_executor: IdempotentActionExecutor | None = None,
    ) -> None:
        self.journal_store = journal_store or TransitionJournalStore()
        self.action_executor = action_executor or IdempotentActionExecutor(self.journal_store)

    def _execute_actions(
        self,
        journal: TransitionJournal,
        actions: Sequence[PhasedDriverAction],
        *,
        observe: Callable[[DriverAction], Mapping[str, object]],
        perform: Callable[[DriverAction], Mapping[str, object] | None],
    ) -> tuple[TransitionJournal, tuple[IdempotentExecutionResult, ...], bool]:
        attempts = []
        current = journal
        for action in actions:
            result = self.action_executor.execute(
                current,
                action,
                observe=observe,
                perform=perform,
            )
            attempts.append(result)
            current = result.journal
            if result.disposition is IdempotentExecutionDisposition.FAILED:
                return current, tuple(attempts), False
        return current, tuple(attempts), True

    def recover(
        self,
        journal: TransitionJournal,
        *,
        failed_action: PhasedDriverAction,
        failure: ActionFailure,
        observe: Callable[[DriverAction], Mapping[str, object]],
        perform: Callable[[DriverAction], Mapping[str, object] | None],
        degraded_fallback: DeclaredDegradedFallback | None = None,
    ) -> TransitionRecoveryResult:
        if not isinstance(journal, TransitionJournal):
            raise TypeError("journal must be a TransitionJournal")
        if not isinstance(failed_action, PhasedDriverAction):
            raise TypeError("failed_action must be a PhasedDriverAction")
        if not isinstance(failure, ActionFailure):
            raise TypeError("failure must be an ActionFailure")
        if degraded_fallback is not None and not isinstance(
            degraded_fallback, DeclaredDegradedFallback
        ):
            raise TypeError("degraded_fallback must be a DeclaredDegradedFallback or null")

        policy = failed_action.action.recovery
        attempts = []
        reasons = [f"{failed_action.phase.value}:{failure.classification.value}:{failure.code}"]
        current = journal

        if policy.inverse is not None:
            inverse = _materialize_recovery_action(
                failed_action.action,
                policy.inverse,
                intent_scope=f"{failed_action.action.idempotency_key}:inverse",
                qualifier="recovery-inverse",
                phase=failed_action.phase,
            )
            current, results, succeeded = self._execute_actions(
                current,
                (inverse,),
                observe=observe,
                perform=perform,
            )
            attempts.extend(results)
            if succeeded:
                finished = self.journal_store.finish_recovery(
                    current,
                    status=TransitionStatus.ROLLED_BACK,
                    summary={
                        "outcome": TransitionRecoveryStatus.ROLLED_BACK.value,
                        "failedAction": failed_action.action.idempotency_key,
                        "failure": failure.to_document(),
                    },
                )
                return TransitionRecoveryResult(
                    TransitionRecoveryStatus.ROLLED_BACK,
                    finished,
                    tuple(attempts),
                    None,
                    tuple(reasons + ["inverse-succeeded"]),
                )
            reasons.append("inverse-failed")

        fallback_actions = []
        fallback_id = None
        if policy.safe_fallback is not None:
            fallback_actions.append(
                _materialize_recovery_action(
                    failed_action.action,
                    policy.safe_fallback,
                    intent_scope=f"{failed_action.action.idempotency_key}:safe-fallback",
                    qualifier="recovery-safe-fallback",
                    phase=ReconciliationPhase.SUPPRESS,
                )
            )
            fallback_id = "action-safe-fallback"
        if degraded_fallback is not None:
            fallback_actions.extend(degraded_fallback.actions)
            fallback_id = degraded_fallback.fallback_id
            reasons.append(f"declared-fallback:{degraded_fallback.fallback_id}")

        if fallback_actions:
            current, results, succeeded = self._execute_actions(
                current,
                tuple(fallback_actions),
                observe=observe,
                perform=perform,
            )
            attempts.extend(results)
            if succeeded:
                finished = self.journal_store.finish_recovery(
                    current,
                    status=TransitionStatus.ROLLED_BACK,
                    summary={
                        "outcome": TransitionRecoveryStatus.DEGRADED_FALLBACK.value,
                        "fallbackId": fallback_id,
                        "failedAction": failed_action.action.idempotency_key,
                        "failure": failure.to_document(),
                    },
                )
                return TransitionRecoveryResult(
                    TransitionRecoveryStatus.DEGRADED_FALLBACK,
                    finished,
                    tuple(attempts),
                    fallback_id,
                    tuple(reasons + ["fallback-succeeded"]),
                )
            reasons.append("fallback-failed")

        finished = self.journal_store.finish_recovery(
            current,
            status=TransitionStatus.FAILED,
            summary={
                "outcome": TransitionRecoveryStatus.FAILED.value,
                "failedAction": failed_action.action.idempotency_key,
                "failure": failure.to_document(),
                "reasons": reasons,
            },
        )
        return TransitionRecoveryResult(
            TransitionRecoveryStatus.FAILED,
            finished,
            tuple(attempts),
            fallback_id,
            tuple(reasons),
        )
