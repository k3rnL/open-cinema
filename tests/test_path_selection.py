import itertools

import pytest

from core.orchestration.condition_evaluation import EligibilityStatus
from core.orchestration.path_selection import (
    PathCandidate,
    PathSelectionMode,
    PathSelectionStatus,
    SelectionTieBreak,
    resolve_exclusive_selection,
    resolve_fan_out_selection,
    resolve_mixer_selection,
)


def _candidate(
    reference_id,
    priority,
    order,
    eligibility=EligibilityStatus.ELIGIBLE,
):
    return PathCandidate(reference_id, priority, order, eligibility)


def test_priority_wins_and_declared_order_is_explicit_secondary_tie_break() -> None:
    candidates = (
        _candidate("speakers", 100, 2),
        _candidate("headset-b", 300, 1),
        _candidate("headset-a", 300, 0),
    )

    decision = resolve_exclusive_selection(
        reversed(candidates),
        mode=PathSelectionMode.FIRST_AVAILABLE,
        tie_break=SelectionTieBreak.DECLARATION_ORDER,
    )

    assert decision.status is PathSelectionStatus.RESOLVED
    assert [item.reference_id for item in decision.selected] == ["headset-a"]
    assert {item.candidate.reference_id: item.reason for item in decision.rejected} == {
        "headset-b": "declaration_order_tie_break",
        "speakers": "lower_priority",
    }


def test_exclusive_choice_can_report_equal_best_as_conflict() -> None:
    decision = resolve_exclusive_selection(
        (
            _candidate("left", 100, 0),
            _candidate("right", 100, 1),
        ),
        tie_break=SelectionTieBreak.CONFLICT,
    )

    assert decision.status is PathSelectionStatus.CONFLICTED
    assert decision.selected == ()
    assert [item.reference_id for item in decision.tied] == ["left", "right"]


def test_reference_id_tie_break_is_independent_of_input_iteration() -> None:
    candidates = (
        _candidate("z-output", 100, 0),
        _candidate("a-output", 100, 1),
        _candidate("fallback", 50, 2),
    )
    results = {
        resolve_exclusive_selection(
            permutation,
            tie_break=SelectionTieBreak.REFERENCE_ID,
        ).selected[0].reference_id
        for permutation in itertools.permutations(candidates)
    }

    assert results == {"a-output"}


def test_fallback_skips_ineligible_candidates_in_priority_order() -> None:
    decision = resolve_exclusive_selection(
        (
            _candidate("headset", 300, 0, EligibilityStatus.INELIGIBLE),
            _candidate("speakers", 100, 1),
        ),
        mode=PathSelectionMode.FALLBACK,
        tie_break=SelectionTieBreak.DECLARATION_ORDER,
    )

    assert decision.selected[0].reference_id == "speakers"
    assert decision.rejected[0].reason == "ineligible"


@pytest.mark.parametrize(
    ("eligibilities", "status"),
    (
        ((EligibilityStatus.INELIGIBLE,), PathSelectionStatus.UNAVAILABLE),
        ((EligibilityStatus.WAITING,), PathSelectionStatus.WAITING),
        ((EligibilityStatus.ERROR,), PathSelectionStatus.CONFLICTED),
    ),
)
def test_no_eligible_candidate_preserves_reason_class(eligibilities, status) -> None:
    decision = resolve_exclusive_selection(
        tuple(
            _candidate(f"candidate-{index}", 100, index, eligibility)
            for index, eligibility in enumerate(eligibilities)
        ),
        tie_break=SelectionTieBreak.DECLARATION_ORDER,
    )

    assert decision.status is status


def test_best_effort_fan_out_selects_every_eligible_branch() -> None:
    candidates = (
        _candidate("room", 100, 0),
        _candidate("kitchen", 90, 1, EligibilityStatus.WAITING),
        _candidate("recorder", 80, 2),
    )

    best_effort = resolve_fan_out_selection(candidates, failure_mode="best-effort")
    all_required = resolve_fan_out_selection(candidates, failure_mode="all-required")

    assert [item.reference_id for item in best_effort.selected] == ["room", "recorder"]
    assert best_effort.status is PathSelectionStatus.RESOLVED
    assert all_required.selected == ()
    assert all_required.status is PathSelectionStatus.WAITING


def test_mixer_selects_multiple_sources_while_exclusive_selects_one() -> None:
    candidates = (
        _candidate("tv", 100, 0),
        _candidate("commentary", 50, 1),
    )

    mixed = resolve_mixer_selection(candidates)
    exclusive = resolve_exclusive_selection(
        candidates,
        tie_break=SelectionTieBreak.DECLARATION_ORDER,
    )

    assert [item.reference_id for item in mixed.selected] == ["tv", "commentary"]
    assert [item.reference_id for item in exclusive.selected] == ["tv"]


def test_duplicate_candidate_identity_or_order_is_rejected() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        resolve_mixer_selection(
            (_candidate("same", 1, 0), _candidate("same", 2, 1))
        )
    with pytest.raises(ValueError, match="orders"):
        resolve_mixer_selection(
            (_candidate("first", 1, 0), _candidate("second", 2, 0))
        )
