from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from .condition_evaluation import EligibilityStatus


class PathSelectionMode(StrEnum):
    EXCLUSIVE = "exclusive"
    FIRST_AVAILABLE = "first-available"
    FALLBACK = "fallback"
    FAN_OUT = "fan-out"
    MIX = "mix"


class PathSelectionStatus(StrEnum):
    RESOLVED = "resolved"
    WAITING = "waiting"
    UNAVAILABLE = "unavailable"
    CONFLICTED = "conflicted"


class SelectionTieBreak(StrEnum):
    DECLARATION_ORDER = "declaration-order"
    REFERENCE_ID = "reference-id"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PathCandidate:
    reference_id: str
    priority: int
    declaration_order: int
    eligibility: EligibilityStatus
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reference_id, str) or not self.reference_id:
            raise ValueError("candidate reference_id must be a non-empty string")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("candidate priority must be an integer")
        if (
            isinstance(self.declaration_order, bool)
            or not isinstance(self.declaration_order, int)
            or self.declaration_order < 0
        ):
            raise ValueError("candidate declaration_order must be non-negative")
        object.__setattr__(self, "eligibility", EligibilityStatus(self.eligibility))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class RejectedPathCandidate:
    candidate: PathCandidate
    reason: str


@dataclass(frozen=True, slots=True)
class PathSelectionDecision:
    mode: PathSelectionMode
    status: PathSelectionStatus
    selected: tuple[PathCandidate, ...]
    rejected: tuple[RejectedPathCandidate, ...]
    tied: tuple[PathCandidate, ...] = ()

    def to_document(self) -> dict[str, object]:
        def candidate_document(candidate: PathCandidate) -> dict[str, object]:
            return {
                "referenceId": candidate.reference_id,
                "priority": candidate.priority,
                "declarationOrder": candidate.declaration_order,
                "eligibility": candidate.eligibility.value,
                "evidence": list(candidate.evidence),
            }

        return {
            "mode": self.mode.value,
            "status": self.status.value,
            "selected": [candidate_document(item) for item in self.selected],
            "rejected": [
                {"candidate": candidate_document(item.candidate), "reason": item.reason}
                for item in self.rejected
            ],
            "tied": [candidate_document(item) for item in self.tied],
        }


def _canonical_candidates(candidates: Iterable[PathCandidate]) -> tuple[PathCandidate, ...]:
    received = tuple(candidates)
    if any(not isinstance(candidate, PathCandidate) for candidate in received):
        raise TypeError("candidates must contain PathCandidate values")
    identities = [candidate.reference_id for candidate in received]
    if len(identities) != len(set(identities)):
        raise ValueError("candidate reference identifiers must be unique")
    orders = [candidate.declaration_order for candidate in received]
    if len(orders) != len(set(orders)):
        raise ValueError("candidate declaration orders must be unique")
    return tuple(
        sorted(
            received,
            key=lambda candidate: (
                -candidate.priority,
                candidate.declaration_order,
                candidate.reference_id,
            ),
        )
    )


def _no_selection(candidates, mode):
    if any(candidate.eligibility is EligibilityStatus.ERROR for candidate in candidates):
        status = PathSelectionStatus.CONFLICTED
    elif any(candidate.eligibility is EligibilityStatus.WAITING for candidate in candidates):
        status = PathSelectionStatus.WAITING
    else:
        status = PathSelectionStatus.UNAVAILABLE
    return PathSelectionDecision(
        mode=mode,
        status=status,
        selected=(),
        rejected=tuple(
            RejectedPathCandidate(candidate, candidate.eligibility.value)
            for candidate in candidates
        ),
    )


def resolve_exclusive_selection(
    candidates: Iterable[PathCandidate],
    *,
    mode: PathSelectionMode | str = PathSelectionMode.EXCLUSIVE,
    tie_break: SelectionTieBreak | str,
) -> PathSelectionDecision:
    mode = PathSelectionMode(mode)
    if mode not in {
        PathSelectionMode.EXCLUSIVE,
        PathSelectionMode.FIRST_AVAILABLE,
        PathSelectionMode.FALLBACK,
    }:
        raise ValueError(
            "exclusive selection requires exclusive, first-available, or fallback mode"
        )
    tie_break = SelectionTieBreak(tie_break)
    ordered = _canonical_candidates(candidates)
    eligible = tuple(
        candidate for candidate in ordered if candidate.eligibility is EligibilityStatus.ELIGIBLE
    )
    if not eligible:
        return _no_selection(ordered, mode)
    best_priority = eligible[0].priority
    tied = tuple(candidate for candidate in eligible if candidate.priority == best_priority)
    if len(tied) > 1 and tie_break is SelectionTieBreak.CONFLICT:
        return PathSelectionDecision(
            mode=mode,
            status=PathSelectionStatus.CONFLICTED,
            selected=(),
            tied=tied,
            rejected=tuple(
                RejectedPathCandidate(
                    candidate,
                    "equal_best_priority" if candidate in tied else "lower_priority",
                )
                for candidate in ordered
            ),
        )
    if tie_break is SelectionTieBreak.REFERENCE_ID:
        selected = min(tied, key=lambda candidate: candidate.reference_id)
    else:
        selected = min(tied, key=lambda candidate: candidate.declaration_order)
    rejected = []
    for candidate in ordered:
        if candidate is selected:
            continue
        if candidate.eligibility is not EligibilityStatus.ELIGIBLE:
            reason = candidate.eligibility.value
        elif candidate.priority < selected.priority:
            reason = "lower_priority"
        elif tie_break is SelectionTieBreak.REFERENCE_ID:
            reason = "reference_id_tie_break"
        else:
            reason = "declaration_order_tie_break"
        rejected.append(RejectedPathCandidate(candidate, reason))
    return PathSelectionDecision(
        mode=mode,
        status=PathSelectionStatus.RESOLVED,
        selected=(selected,),
        rejected=tuple(rejected),
        tied=tied if len(tied) > 1 else (),
    )


def resolve_fan_out_selection(
    candidates: Iterable[PathCandidate],
    *,
    failure_mode: str,
) -> PathSelectionDecision:
    if failure_mode not in {"all-required", "best-effort"}:
        raise ValueError("fan-out failure_mode must be all-required or best-effort")
    ordered = _canonical_candidates(candidates)
    eligible = tuple(
        candidate for candidate in ordered if candidate.eligibility is EligibilityStatus.ELIGIBLE
    )
    unavailable = tuple(candidate for candidate in ordered if candidate not in eligible)
    if failure_mode == "all-required" and unavailable:
        base = _no_selection(ordered, PathSelectionMode.FAN_OUT)
        return replace(
            base,
            rejected=tuple(
                RejectedPathCandidate(candidate, "fan_out_all_required") for candidate in ordered
            ),
        )
    if not eligible:
        return _no_selection(ordered, PathSelectionMode.FAN_OUT)
    return PathSelectionDecision(
        mode=PathSelectionMode.FAN_OUT,
        status=PathSelectionStatus.RESOLVED,
        selected=eligible,
        rejected=tuple(
            RejectedPathCandidate(candidate, candidate.eligibility.value)
            for candidate in unavailable
        ),
    )


def resolve_mixer_selection(
    candidates: Iterable[PathCandidate],
) -> PathSelectionDecision:
    ordered = _canonical_candidates(candidates)
    eligible = tuple(
        candidate for candidate in ordered if candidate.eligibility is EligibilityStatus.ELIGIBLE
    )
    if not eligible:
        return _no_selection(ordered, PathSelectionMode.MIX)
    return PathSelectionDecision(
        mode=PathSelectionMode.MIX,
        status=PathSelectionStatus.RESOLVED,
        selected=eligible,
        rejected=tuple(
            RejectedPathCandidate(candidate, candidate.eligibility.value)
            for candidate in ordered
            if candidate not in eligible
        ),
    )
