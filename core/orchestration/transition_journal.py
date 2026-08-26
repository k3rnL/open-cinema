from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from django.db import transaction
from django.utils import timezone
from wyreplumber.runtime import FrozenDict, freeze_json, thaw_json

from api.models import (
    ResolvedPlan,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)

from .action_planning import PhasedDriverAction, ReconciliationPhase
from .driver_actions import ActionFailure, DriverAction, DriverActionError


class JournalActionStatus(StrEnum):
    STARTED = "started"
    UNCERTAIN = "uncertain"
    ALREADY_SATISFIED = "already-satisfied"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TransitionRecoveryMode(StrEnum):
    RESUME_PHASE = "resume-phase"
    VERIFY_UNCERTAIN_ACTION = "verify-uncertain-action"


@dataclass(frozen=True, slots=True)
class JournalActionAttempt:
    journal_id: uuid.UUID
    entry_index: int
    idempotency_key: str
    action: DriverAction


@dataclass(frozen=True, slots=True)
class TransitionRecoveryDirective:
    journal_id: uuid.UUID
    graph_definition_id: uuid.UUID
    generation: int
    phase: ReconciliationPhase
    mode: TransitionRecoveryMode
    action: DriverAction | None
    entry_index: int | None
    reason: str


def _json_mapping(value: Mapping[str, object] | None, *, field: str) -> dict[str, object]:
    value = value or {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping or null")
    frozen = freeze_json(dict(value))
    if not isinstance(frozen, FrozenDict):  # pragma: no cover - guarded by Mapping.
        raise TypeError(f"{field} must be a mapping")
    return thaw_json(frozen)


def _phase(value: str | ReconciliationPhase) -> ReconciliationPhase:
    return ReconciliationPhase(value)


class TransitionJournalStore:
    """Short database transactions around externally executed driver actions."""

    def start(self, plan: ResolvedPlan, *, generation: int) -> TransitionJournal:
        if not isinstance(plan, ResolvedPlan):
            raise TypeError("plan must be a ResolvedPlan")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        with transaction.atomic():
            journal, created = TransitionJournal.objects.select_for_update().get_or_create(
                graph_definition=plan.graph_definition,
                generation=generation,
                defaults={
                    "plan": plan,
                    "correlation_id": plan.correlation_id,
                    "phase": TransitionPhase.PREPARE,
                    "status": TransitionStatus.PENDING,
                    "entries": [],
                },
            )
            if not created and (
                journal.plan_id != plan.pk or journal.correlation_id != plan.correlation_id
            ):
                raise ValueError(
                    "transition generation is already correlated to another resolved plan"
                )
            return journal

    def begin_action(
        self,
        journal: TransitionJournal,
        phased_action: PhasedDriverAction,
    ) -> JournalActionAttempt:
        if not isinstance(journal, TransitionJournal):
            raise TypeError("journal must be a TransitionJournal")
        if not isinstance(phased_action, PhasedDriverAction):
            raise TypeError("phased_action must be a PhasedDriverAction")
        with transaction.atomic():
            current = TransitionJournal.objects.select_for_update().get(pk=journal.pk)
            if current.status not in {
                TransitionStatus.PENDING,
                TransitionStatus.RUNNING,
            }:
                raise ValueError("cannot begin an action on a terminal transition")
            entries = list(current.entries)
            if entries and entries[-1].get("status") in {
                JournalActionStatus.STARTED.value,
                JournalActionStatus.UNCERTAIN.value,
            }:
                raise ValueError(
                    "the previous action outcome must be recovered and persisted first"
                )
            started_at = timezone.now().isoformat()
            entry = {
                "schemaVersion": 1,
                "kind": "driver-action",
                "phase": phased_action.phase.value,
                "status": JournalActionStatus.STARTED.value,
                "startedAt": started_at,
                "completedAt": None,
                "idempotencyKey": phased_action.action.idempotency_key,
                "action": phased_action.action.to_document(),
                "observed": {},
                "failure": None,
            }
            entries.append(entry)
            current.phase = phased_action.phase.value
            current.status = TransitionStatus.RUNNING
            current.entries = entries
            current.completed_at = None
            current.save(
                update_fields=(
                    "phase",
                    "status",
                    "entries",
                    "completed_at",
                    "updated_at",
                )
            )
            return JournalActionAttempt(
                journal_id=current.pk,
                entry_index=len(entries) - 1,
                idempotency_key=phased_action.action.idempotency_key,
                action=phased_action.action,
            )

    def succeed_action(
        self,
        attempt: JournalActionAttempt,
        *,
        observed: Mapping[str, object] | None = None,
    ) -> TransitionJournal:
        return self._finish_action(
            attempt,
            status=JournalActionStatus.SUCCEEDED,
            observed=observed,
        )

    def satisfy_action(
        self,
        attempt: JournalActionAttempt,
        *,
        observed: Mapping[str, object],
    ) -> TransitionJournal:
        return self._finish_action(
            attempt,
            status=JournalActionStatus.ALREADY_SATISFIED,
            observed=observed,
        )

    def fail_action(
        self,
        attempt: JournalActionAttempt,
        failure: ActionFailure,
        *,
        observed: Mapping[str, object] | None = None,
    ) -> TransitionJournal:
        if not isinstance(failure, ActionFailure):
            raise TypeError("failure must be an ActionFailure")
        return self._finish_action(
            attempt,
            status=JournalActionStatus.FAILED,
            observed=observed,
            failure=failure,
        )

    def _finish_action(
        self,
        attempt: JournalActionAttempt,
        *,
        status: JournalActionStatus,
        observed: Mapping[str, object] | None,
        failure: ActionFailure | None = None,
    ) -> TransitionJournal:
        if not isinstance(attempt, JournalActionAttempt):
            raise TypeError("attempt must be a JournalActionAttempt")
        status = JournalActionStatus(status)
        if status not in {
            JournalActionStatus.ALREADY_SATISFIED,
            JournalActionStatus.SUCCEEDED,
            JournalActionStatus.FAILED,
        }:
            raise ValueError("finished action status is invalid")
        if (failure is not None) is not (status is JournalActionStatus.FAILED):
            raise ValueError("failure must be present exactly for a failed action")
        with transaction.atomic():
            journal = TransitionJournal.objects.select_for_update().get(pk=attempt.journal_id)
            entries = list(journal.entries)
            if attempt.entry_index >= len(entries):
                raise ValueError("journal action attempt no longer exists")
            entry = dict(entries[attempt.entry_index])
            if entry.get("idempotencyKey") != attempt.idempotency_key:
                raise ValueError("journal action attempt idempotency key changed")
            if entry.get("status") not in {
                JournalActionStatus.STARTED.value,
                JournalActionStatus.UNCERTAIN.value,
            }:
                raise ValueError("journal action outcome was already persisted")
            entry.update(
                {
                    "status": status.value,
                    "completedAt": timezone.now().isoformat(),
                    "observed": _json_mapping(observed, field="observed outcome"),
                    "failure": failure.to_document() if failure is not None else None,
                }
            )
            entries[attempt.entry_index] = entry
            journal.entries = entries
            journal.save(update_fields=("entries", "status", "completed_at", "updated_at"))
            return journal

    def execute(
        self,
        journal: TransitionJournal,
        phased_action: PhasedDriverAction,
        perform: Callable[[DriverAction], Mapping[str, object] | None],
    ) -> TransitionJournal:
        if not callable(perform):
            raise TypeError("perform must be callable")
        attempt = self.begin_action(journal, phased_action)
        try:
            observed = perform(phased_action.action)
        except DriverActionError as error:
            if error.action != phased_action.action:
                raise ValueError("driver reported a failure for another action") from error
            return self.fail_action(attempt, error.failure)
        return self.succeed_action(attempt, observed=observed)

    def complete(self, journal: TransitionJournal) -> TransitionJournal:
        if not isinstance(journal, TransitionJournal):
            raise TypeError("journal must be a TransitionJournal")
        with transaction.atomic():
            current = TransitionJournal.objects.select_for_update().get(pk=journal.pk)
            entries = list(current.entries)
            if entries and entries[-1].get("status") not in {
                JournalActionStatus.ALREADY_SATISFIED.value,
                JournalActionStatus.SUCCEEDED.value,
            }:
                raise ValueError("cannot complete while the latest action is unresolved")
            current.phase = TransitionPhase.COMPLETED
            current.status = TransitionStatus.SUCCEEDED
            current.completed_at = timezone.now()
            current.save(
                update_fields=(
                    "phase",
                    "status",
                    "completed_at",
                    "updated_at",
                )
            )
            return current

    def finish_recovery(
        self,
        journal: TransitionJournal,
        *,
        status: str,
        summary: Mapping[str, object],
    ) -> TransitionJournal:
        if not isinstance(journal, TransitionJournal):
            raise TypeError("journal must be a TransitionJournal")
        status = TransitionStatus(status)
        if status not in {
            TransitionStatus.ROLLED_BACK,
            TransitionStatus.FAILED,
            TransitionStatus.CANCELLED,
        }:
            raise ValueError("recovery status must be rolled_back, failed, or cancelled")
        with transaction.atomic():
            current = TransitionJournal.objects.select_for_update().get(pk=journal.pk)
            if current.status not in {
                TransitionStatus.PENDING,
                TransitionStatus.RUNNING,
            }:
                raise ValueError("cannot finish recovery for a terminal transition")
            entries = list(current.entries)
            entries.append(
                {
                    "schemaVersion": 1,
                    "kind": "transition-recovery",
                    "status": status,
                    "completedAt": timezone.now().isoformat(),
                    "summary": _json_mapping(summary, field="recovery summary"),
                }
            )
            current.entries = entries
            current.status = status
            current.completed_at = timezone.now()
            current.save(update_fields=("entries", "status", "completed_at", "updated_at"))
            return current

    def recover_incomplete(self) -> tuple[TransitionRecoveryDirective, ...]:
        directives = []
        incomplete_ids = tuple(
            TransitionJournal.objects.filter(
                status__in=(TransitionStatus.PENDING, TransitionStatus.RUNNING)
            )
            .order_by("graph_definition_id", "generation")
            .values_list("pk", flat=True)
        )
        for journal_id in incomplete_ids:
            with transaction.atomic():
                journal = TransitionJournal.objects.select_for_update().get(pk=journal_id)
                entries = list(journal.entries)
                action = None
                entry_index = None
                if entries and entries[-1].get("status") in {
                    JournalActionStatus.STARTED.value,
                    JournalActionStatus.UNCERTAIN.value,
                }:
                    latest = dict(entries[-1])
                    action = DriverAction.from_document(latest.get("action"))
                    entry_index = len(entries) - 1
                    latest["status"] = JournalActionStatus.UNCERTAIN.value
                    latest["recoveredAt"] = timezone.now().isoformat()
                    entries[-1] = latest
                    journal.entries = entries
                    journal.save(update_fields=("entries", "updated_at"))
                    mode = TransitionRecoveryMode.VERIFY_UNCERTAIN_ACTION
                    reason = (
                        "The process stopped after persisting action start but before "
                        "persisting its outcome; verify postconditions before retrying."
                    )
                else:
                    mode = TransitionRecoveryMode.RESUME_PHASE
                    reason = "All persisted action outcomes are known; resume the journal phase."
                directives.append(
                    TransitionRecoveryDirective(
                        journal_id=journal.pk,
                        graph_definition_id=journal.graph_definition_id,
                        generation=journal.generation,
                        phase=_phase(journal.phase),
                        mode=mode,
                        action=action,
                        entry_index=entry_index,
                        reason=reason,
                    )
                )
        return tuple(directives)
