from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from api.models import TransitionJournal

from .action_planning import PhasedDriverAction, evaluate_action_verification
from .driver_actions import (
    ActionFailure,
    ActionFailureClassification,
    DriverAction,
    DriverActionError,
)
from .transition_journal import (
    JournalActionAttempt,
    TransitionJournalStore,
    TransitionRecoveryDirective,
    TransitionRecoveryMode,
)


class IdempotentExecutionDisposition(StrEnum):
    ALREADY_SATISFIED = "already-satisfied"
    APPLIED = "applied"
    UNCERTAIN_VERIFIED = "uncertain-verified"
    UNCERTAIN_RETRIED = "uncertain-retried"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IdempotentExecutionResult:
    journal: TransitionJournal
    disposition: IdempotentExecutionDisposition
    idempotency_key: str
    verification_reasons: tuple[str, ...]
    failure: ActionFailure | None = None


class IdempotentActionExecutor:
    """Observe-before-apply and verify uncertain attempts before retrying them."""

    def __init__(self, journal_store: TransitionJournalStore | None = None) -> None:
        self.journal_store = journal_store or TransitionJournalStore()

    @staticmethod
    def _observe(
        action: DriverAction,
        observe: Callable[[DriverAction], Mapping[str, object]],
    ) -> tuple[Mapping[str, object], bool, tuple[str, ...]]:
        if not callable(observe):
            raise TypeError("observe must be callable")
        facts = observe(action)
        if not isinstance(facts, Mapping):
            raise TypeError("observe must return a mapping of fresh facts")
        satisfied, reasons = evaluate_action_verification(action, facts)
        return facts, satisfied, reasons

    def execute(
        self,
        journal: TransitionJournal,
        phased_action: PhasedDriverAction,
        *,
        observe: Callable[[DriverAction], Mapping[str, object]],
        perform: Callable[[DriverAction], Mapping[str, object] | None],
    ) -> IdempotentExecutionResult:
        if not isinstance(phased_action, PhasedDriverAction):
            raise TypeError("phased_action must be a PhasedDriverAction")
        facts, satisfied, reasons = self._observe(phased_action.action, observe)
        attempt = self.journal_store.begin_action(journal, phased_action)
        if satisfied:
            updated = self.journal_store.satisfy_action(attempt, observed=facts)
            return IdempotentExecutionResult(
                updated,
                IdempotentExecutionDisposition.ALREADY_SATISFIED,
                attempt.idempotency_key,
                reasons,
                None,
            )
        return self._perform_attempt(
            attempt,
            phased_action.action,
            observe,
            perform,
            success_disposition=IdempotentExecutionDisposition.APPLIED,
            verification_reasons=reasons,
        )

    def recover_uncertain(
        self,
        directive: TransitionRecoveryDirective,
        *,
        observe: Callable[[DriverAction], Mapping[str, object]],
        perform: Callable[[DriverAction], Mapping[str, object] | None],
    ) -> IdempotentExecutionResult:
        if not isinstance(directive, TransitionRecoveryDirective):
            raise TypeError("directive must be a TransitionRecoveryDirective")
        if (
            directive.mode is not TransitionRecoveryMode.VERIFY_UNCERTAIN_ACTION
            or directive.action is None
            or directive.entry_index is None
        ):
            raise ValueError("directive does not describe an uncertain action")
        action = directive.action
        attempt = JournalActionAttempt(
            journal_id=directive.journal_id,
            entry_index=directive.entry_index,
            idempotency_key=action.idempotency_key,
            action=action,
        )
        facts, satisfied, reasons = self._observe(action, observe)
        if satisfied:
            updated = self.journal_store.satisfy_action(attempt, observed=facts)
            return IdempotentExecutionResult(
                updated,
                IdempotentExecutionDisposition.UNCERTAIN_VERIFIED,
                action.idempotency_key,
                reasons,
                None,
            )
        return self._perform_attempt(
            attempt,
            action,
            observe,
            perform,
            success_disposition=IdempotentExecutionDisposition.UNCERTAIN_RETRIED,
            verification_reasons=reasons,
        )

    def _perform_attempt(
        self,
        attempt: JournalActionAttempt,
        action: DriverAction,
        observe: Callable[[DriverAction], Mapping[str, object]],
        perform: Callable[[DriverAction], Mapping[str, object] | None],
        *,
        success_disposition: IdempotentExecutionDisposition,
        verification_reasons: tuple[str, ...],
    ) -> IdempotentExecutionResult:
        if not callable(perform):
            raise TypeError("perform must be callable")
        try:
            perform(action)
        except DriverActionError as error:
            if error.action != action:
                raise ValueError("driver reported a failure for another action") from error
            updated = self.journal_store.fail_action(attempt, error.failure)
            return IdempotentExecutionResult(
                updated,
                IdempotentExecutionDisposition.FAILED,
                action.idempotency_key,
                verification_reasons,
                error.failure,
            )
        observed, satisfied, postcondition_reasons = self._observe(action, observe)
        if not satisfied:
            failure = ActionFailure(
                ActionFailureClassification.SAFETY,
                "postcondition-not-satisfied",
                "The driver returned but fresh observation did not satisfy the action verification.",
                {"reasons": list(postcondition_reasons)},
            )
            updated = self.journal_store.fail_action(
                attempt,
                failure,
                observed=observed,
            )
            return IdempotentExecutionResult(
                updated,
                IdempotentExecutionDisposition.FAILED,
                action.idempotency_key,
                postcondition_reasons,
                failure,
            )
        updated = self.journal_store.succeed_action(attempt, observed=observed)
        return IdempotentExecutionResult(
            updated,
            success_disposition,
            action.idempotency_key,
            postcondition_reasons,
            None,
        )
