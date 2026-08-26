from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st
from wyreplumber.runtime import FrozenDict

from core.orchestration.endpoint_inventory import (
    RuntimeEndpointReference,
    map_runtime_endpoints,
)
from core.orchestration.endpoint_matching import (
    EndpointMatchStatus,
    match_endpoint_candidates,
)
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from tests.test_endpoint_inventory_mapping import _snapshot


def _selector(path="direction", value="output"):
    return parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [{"path": path, "operator": "exact", "value": value}],
        }
    ).selector


def _sink():
    return next(
        candidate
        for candidate in map_runtime_endpoints(_snapshot()).candidates
        if candidate.direction.value == "output"
    )


def test_managed_identity_wins_over_hardware_only_candidate() -> None:
    hardware = _sink()
    managed = replace(
        hardware,
        runtime=RuntimeEndpointReference(3, 999, 1),
        name="managed-speakers",
        node_properties=FrozenDict(
            {
                **hardware.node_properties.to_dict(),
                "open-cinema.endpoint-id": "endpoint:main-speakers",
            }
        ),
    )

    result = match_endpoint_candidates(_selector(), [hardware, managed])

    assert result.status == EndpointMatchStatus.MATCHED
    assert result.selected == managed
    assert result.diagnostics[0].runtime_key == managed.runtime_key
    assert result.diagnostics[0].score > result.diagnostics[1].score
    assert any(
        evidence.startswith("identity:managed_id")
        for evidence in result.diagnostics[0].accepted_evidence
    )
    assert any(
        evidence.startswith("candidate:lower-score")
        for evidence in result.diagnostics[1].rejected_evidence
    )


def test_equal_best_candidates_remain_explicitly_ambiguous() -> None:
    first = _sink()
    second = replace(
        first,
        runtime=RuntimeEndpointReference(3, 998, 1),
    )

    result = match_endpoint_candidates(_selector(), [second, first])

    assert result.status == EndpointMatchStatus.AMBIGUOUS
    assert result.selected is None
    assert {candidate.runtime_key for candidate in result.tied} == {
        first.runtime_key,
        second.runtime_key,
    }
    assert all(
        any("equal-best-score" in evidence for evidence in diagnostic.rejected_evidence)
        for diagnostic in result.diagnostics
    )


def test_no_match_keeps_rejected_predicate_evidence() -> None:
    result = match_endpoint_candidates(
        _selector("device.properties.device.serial", "missing"),
        [_sink()],
    )

    assert result.status == EndpointMatchStatus.NO_MATCH
    assert result.selected is None
    assert result.diagnostics[0].score == 0
    assert result.diagnostics[0].predicates[0].matched is False
    assert result.diagnostics[0].rejected_evidence == (
        "selector:device.properties.device.serial:exact:not-matched",
    )


@given(order=st.permutations(range(3)))
def test_input_order_never_changes_selection_or_diagnostic_order(order) -> None:
    base = _sink()
    candidates = [
        replace(
            base,
            runtime=RuntimeEndpointReference(3, 100 + index, 1),
            name=f"sink-{index}",
            node_properties=FrozenDict(
                {
                    **base.node_properties.to_dict(),
                    **(
                        {"open-cinema.endpoint-id": "endpoint:preferred"}
                        if index == 2
                        else {}
                    ),
                }
            ),
        )
        for index in range(3)
    ]

    result = match_endpoint_candidates(
        _selector(),
        [candidates[index] for index in order],
    )

    assert result.status == EndpointMatchStatus.MATCHED
    assert result.selected.runtime_key == candidates[2].runtime_key
    assert [item.runtime_key for item in result.diagnostics] == [
        candidates[2].runtime_key,
        candidates[0].runtime_key,
        candidates[1].runtime_key,
    ]
