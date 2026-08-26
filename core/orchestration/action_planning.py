from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from wyreplumber.runtime import FrozenDict, freeze_json

from .driver_actions import (
    ActionAssertionOperator,
    DriverAction,
)
from .graph_documents import graph_content_digest


class ReconciliationPhase(StrEnum):
    PREPARE = "prepare"
    SUPPRESS = "suppress"
    CONFIGURE = "configure"
    ROUTE = "route"
    VERIFY = "verify"
    UNSUPPRESS = "unsuppress"
    CLEANUP = "cleanup"


RECONCILIATION_PHASE_ORDER = tuple(ReconciliationPhase)
_MISSING = object()


def _frozen_mapping(value: Mapping[str, object], *, field: str) -> FrozenDict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    frozen = freeze_json(dict(value))
    if not isinstance(frozen, FrozenDict):  # pragma: no cover - Mapping guarantees it.
        raise TypeError(f"{field} must be a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class PhasedDriverAction:
    phase: ReconciliationPhase
    action: DriverAction

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", ReconciliationPhase(self.phase))
        if not isinstance(self.action, DriverAction):
            raise TypeError("action must be a DriverAction")

    def to_document(self) -> dict[str, object]:
        return {"phase": self.phase.value, "action": self.action.to_document()}


@dataclass(frozen=True, slots=True)
class ResolvedDriverIntent:
    plan_digest: str
    desired_state_version: int
    actions: tuple[PhasedDriverAction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan_digest, str) or not self.plan_digest:
            raise ValueError("plan_digest must be a non-empty string")
        if (
            isinstance(self.desired_state_version, bool)
            or not isinstance(self.desired_state_version, int)
            or self.desired_state_version < 1
        ):
            raise ValueError("desired_state_version must be a positive integer")
        actions = tuple(self.actions)
        if any(not isinstance(action, PhasedDriverAction) for action in actions):
            raise TypeError("actions must contain PhasedDriverAction values")
        identities = [action.action.identity.key for action in actions]
        if len(identities) != len(set(identities)):
            raise ValueError("resolved driver action identities must be unique")
        object.__setattr__(self, "actions", actions)


@dataclass(frozen=True, slots=True)
class ObservedManagedResource:
    driver: str
    resource_kind: str
    resource_id: str
    owned_by_open_cinema: bool
    state: FrozenDict
    cleanup_action: DriverAction | None = None

    def __post_init__(self) -> None:
        for field in ("driver", "resource_kind", "resource_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        if not isinstance(self.owned_by_open_cinema, bool):
            raise TypeError("owned_by_open_cinema must be a boolean")
        object.__setattr__(
            self,
            "state",
            _frozen_mapping(self.state, field="managed resource state"),
        )
        if self.cleanup_action is not None:
            if not isinstance(self.cleanup_action, DriverAction):
                raise TypeError("cleanup_action must be a DriverAction or null")
            cleanup_identity = self.cleanup_action.identity
            if (
                cleanup_identity.driver,
                cleanup_identity.resource_kind,
                cleanup_identity.resource_id,
            ) != (self.driver, self.resource_kind, self.resource_id):
                raise ValueError("cleanup action must target its observed managed resource")

    @property
    def key(self) -> str:
        return graph_content_digest(
            {
                "driver": self.driver,
                "resourceKind": self.resource_kind,
                "resourceId": self.resource_id,
            }
        )

    def to_document(self) -> dict[str, object]:
        return {
            "driver": self.driver,
            "resourceKind": self.resource_kind,
            "resourceId": self.resource_id,
            "ownedByOpenCinema": self.owned_by_open_cinema,
            "state": self.state.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ObservedManagedState:
    runtime_generation: int
    runtime_sequence: int
    facts: FrozenDict
    resources: tuple[ObservedManagedResource, ...] = ()

    def __post_init__(self) -> None:
        for field, minimum in (("runtime_generation", 1), ("runtime_sequence", 0)):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
        object.__setattr__(
            self,
            "facts",
            _frozen_mapping(self.facts, field="observed facts"),
        )
        resources = tuple(self.resources)
        if any(not isinstance(item, ObservedManagedResource) for item in resources):
            raise TypeError("resources must contain ObservedManagedResource values")
        keys = [resource.key for resource in resources]
        if len(keys) != len(set(keys)):
            raise ValueError("observed managed resource identities must be unique")
        object.__setattr__(self, "resources", resources)


class ActionDiffDisposition(StrEnum):
    REQUIRED = "required"
    ALREADY_SATISFIED = "already-satisfied"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class ActionDiffEntry:
    phase: ReconciliationPhase
    action: DriverAction
    disposition: ActionDiffDisposition
    reasons: tuple[str, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "identity": self.action.identity.to_document(),
            "idempotencyKey": self.action.idempotency_key,
            "disposition": self.disposition.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationActionPlan:
    plan_digest: str
    desired_state_version: int
    runtime_generation: int
    runtime_sequence: int
    entries: tuple[ActionDiffEntry, ...]
    unmanaged_resource_keys: tuple[str, ...]
    missing_cleanup_resource_keys: tuple[str, ...]
    digest: str

    @property
    def ordered_actions(self) -> tuple[DriverAction, ...]:
        return tuple(
            entry.action
            for entry in self.entries
            if entry.disposition in {ActionDiffDisposition.REQUIRED, ActionDiffDisposition.CLEANUP}
        )

    def actions_for_phase(
        self,
        phase: ReconciliationPhase,
    ) -> tuple[DriverAction, ...]:
        phase = ReconciliationPhase(phase)
        return tuple(
            entry.action
            for entry in self.entries
            if entry.phase is phase
            and entry.disposition in {ActionDiffDisposition.REQUIRED, ActionDiffDisposition.CLEANUP}
        )

    def to_document(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "resolvedPlanDigest": self.plan_digest,
            "desiredStateVersion": self.desired_state_version,
            "runtimeGeneration": self.runtime_generation,
            "runtimeSequence": self.runtime_sequence,
            "entries": [entry.to_document() for entry in self.entries],
            "unmanagedResourceKeys": list(self.unmanaged_resource_keys),
            "missingCleanupResourceKeys": list(self.missing_cleanup_resource_keys),
            "digest": self.digest,
        }


def _assertion_satisfied(assertion, facts: Mapping[str, Any]) -> bool:
    observed = facts.get(assertion.subject, _MISSING)
    operator = assertion.operator
    if operator is ActionAssertionOperator.EXISTS:
        return observed is not _MISSING
    if operator is ActionAssertionOperator.ABSENT:
        return observed is _MISSING
    if observed is _MISSING:
        return False
    if operator is ActionAssertionOperator.EQUALS:
        return observed == assertion.expected
    if operator is ActionAssertionOperator.NOT_EQUALS:
        return observed != assertion.expected
    if operator is ActionAssertionOperator.CONTAINS:
        try:
            return assertion.expected in observed
        except TypeError:
            return False
    raise AssertionError(f"unsupported action assertion operator {operator!r}")


def evaluate_verifications(
    verification: Sequence,
    facts: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(facts, Mapping):
        raise TypeError("facts must be a mapping")
    failed = tuple(
        assertion.subject
        for assertion in verification
        if not _assertion_satisfied(assertion, facts)
    )
    if failed:
        return False, tuple(f"verification-unsatisfied:{subject}" for subject in failed)
    return True, ("all-verifications-satisfied",)


def evaluate_action_verification(
    action: DriverAction,
    facts: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(action, DriverAction):
        raise TypeError("action must be a DriverAction")
    return evaluate_verifications(action.verification, facts)


def _entry_sort_key(entry: ActionDiffEntry) -> tuple[object, ...]:
    return (
        RECONCILIATION_PHASE_ORDER.index(entry.phase),
        entry.action.identity.driver,
        entry.action.identity.resource_kind,
        entry.action.identity.resource_id,
        entry.action.identity.operation,
        entry.action.idempotency_key,
    )


def build_reconciliation_action_plan(
    intent: ResolvedDriverIntent,
    observed: ObservedManagedState,
) -> ReconciliationActionPlan:
    """Pure deterministic diff; this function performs no driver or storage calls."""

    if not isinstance(intent, ResolvedDriverIntent):
        raise TypeError("intent must be a ResolvedDriverIntent")
    if not isinstance(observed, ObservedManagedState):
        raise TypeError("observed must be an ObservedManagedState")

    entries = []
    desired_resource_keys = set()
    ordered_intent = tuple(
        sorted(
            intent.actions,
            key=lambda item: (
                RECONCILIATION_PHASE_ORDER.index(item.phase),
                item.action.identity.driver,
                item.action.identity.resource_kind,
                item.action.identity.resource_id,
                item.action.identity.operation,
                item.action.idempotency_key,
            ),
        )
    )
    prerequisite_mutation_required = False
    for phased in ordered_intent:
        action = phased.action
        desired_resource_keys.add(action.identity.resource_key)
        satisfied, reasons = evaluate_action_verification(action, observed.facts)
        forced_by_prerequisite = (
            prerequisite_mutation_required and phased.phase is not ReconciliationPhase.CLEANUP
        )
        required = not satisfied or forced_by_prerequisite
        if forced_by_prerequisite:
            reasons = ("prerequisite-action-required",)
        entries.append(
            ActionDiffEntry(
                phase=phased.phase,
                action=action,
                disposition=(
                    ActionDiffDisposition.REQUIRED
                    if required
                    else ActionDiffDisposition.ALREADY_SATISFIED
                ),
                reasons=reasons,
            )
        )
        if required and phased.phase is not ReconciliationPhase.CLEANUP:
            prerequisite_mutation_required = True

    unmanaged = []
    missing_cleanup = []
    for resource in observed.resources:
        if resource.key in desired_resource_keys:
            continue
        if not resource.owned_by_open_cinema:
            unmanaged.append(resource.key)
            continue
        if resource.cleanup_action is None:
            missing_cleanup.append(resource.key)
            continue
        entries.append(
            ActionDiffEntry(
                phase=ReconciliationPhase.CLEANUP,
                action=resource.cleanup_action,
                disposition=ActionDiffDisposition.CLEANUP,
                reasons=("owned-resource-no-longer-desired",),
            )
        )

    ordered_entries = tuple(sorted(entries, key=_entry_sort_key))
    document = {
        "schemaVersion": 1,
        "resolvedPlanDigest": intent.plan_digest,
        "desiredStateVersion": intent.desired_state_version,
        "runtimeGeneration": observed.runtime_generation,
        "runtimeSequence": observed.runtime_sequence,
        "entries": [entry.to_document() for entry in ordered_entries],
        "unmanagedResourceKeys": sorted(unmanaged),
        "missingCleanupResourceKeys": sorted(missing_cleanup),
    }
    return ReconciliationActionPlan(
        plan_digest=intent.plan_digest,
        desired_state_version=intent.desired_state_version,
        runtime_generation=observed.runtime_generation,
        runtime_sequence=observed.runtime_sequence,
        entries=ordered_entries,
        unmanaged_resource_keys=tuple(sorted(unmanaged)),
        missing_cleanup_resource_keys=tuple(sorted(missing_cleanup)),
        digest=graph_content_digest(document),
    )
