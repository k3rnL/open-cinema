from dataclasses import replace

import pytest
from wyreplumber.runtime import FrozenDict, LinkValue

from core.orchestration.processor_topology import (
    ExpectedManagedLink,
    ProcessorTopologyExpectation,
    TopologyLinkStatus,
    verify_processor_topology,
)
from tests.test_endpoint_inventory_mapping import _snapshot

_GENERATION = _snapshot().generation


def _expected(
    desired_id: str,
    channel: str,
    endpoints: tuple[int, int, int, int],
    *,
    ingress: bool,
) -> ExpectedManagedLink:
    return ExpectedManagedLink(
        desired_id=desired_id,
        edge_id="source-to-processor" if ingress else "processor-to-output",
        channel=channel,
        runtime_generation=_GENERATION,
        output_node_id=endpoints[0],
        output_port_id=endpoints[1],
        input_node_id=endpoints[2],
        input_port_id=endpoints[3],
        processor_edge=True,
        ingress=ingress,
    )


def _link(link_id: int, expected: ExpectedManagedLink, *, endpoints=None) -> LinkValue:
    output_node, output_port, input_node, input_port = endpoints or expected.endpoints
    return LinkValue(
        id=link_id,
        output_node_id=output_node,
        output_port_id=output_port,
        input_node_id=input_node,
        input_port_id=input_port,
        owner="open-cinema.orchestrator",
        desired_id=expected.desired_id,
        properties=FrozenDict(),
    )


def test_expected_topology_rejects_duplicate_desired_link_identities() -> None:
    link = _expected("graph:edge:FL", "FL", (1, 2, 3, 4), ingress=False)

    with pytest.raises(ValueError, match="identities must be unique"):
        ProcessorTopologyExpectation("graph", _GENERATION, (link, link))


def test_topology_verification_classifies_complete_missing_duplicate_and_mismatch() -> None:
    satisfied = _expected("graph:edge:FL", "FL", (1, 2, 3, 4), ingress=False)
    missing = _expected("graph:edge:FR", "FR", (1, 5, 3, 6), ingress=False)
    duplicate = _expected("graph:edge:FC", "FC", (1, 7, 3, 8), ingress=False)
    mismatched = _expected("graph:edge:LFE", "LFE", (1, 9, 3, 10), ingress=False)
    expectation = ProcessorTopologyExpectation(
        "graph",
        _GENERATION,
        (satisfied, missing, duplicate, mismatched),
    )
    unrelated = LinkValue(
        id=99,
        output_node_id=50,
        output_port_id=51,
        input_node_id=52,
        input_port_id=53,
        owner="another-owner",
        desired_id=missing.desired_id,
        properties=FrozenDict(),
    )
    runtime = replace(
        _snapshot(),
        links=(
            _link(1, satisfied),
            _link(2, duplicate),
            _link(3, duplicate),
            _link(4, mismatched, endpoints=(1, 9, 30, 10)),
            unrelated,
        ),
    )

    verification = verify_processor_topology(
        runtime,
        expectation,
        include_ingress=True,
    )

    assert verification.satisfied is False
    assert [item.status for item in verification.links] == [
        TopologyLinkStatus.SATISFIED,
        TopologyLinkStatus.MISSING,
        TopologyLinkStatus.DUPLICATE,
        TopologyLinkStatus.ENDPOINT_MISMATCH,
    ]
    assert verification.missing_channels == ("FR", "FC", "LFE")
    assert verification.to_document()["counts"] == {
        "satisfied": 1,
        "missing": 1,
        "duplicate": 1,
        "endpoint-mismatch": 1,
        "stale-generation": 0,
    }


def test_downstream_verification_excludes_ingress_and_rejects_stale_generation() -> None:
    ingress = _expected("graph:input:FL", "FL", (1, 2, 3, 4), ingress=True)
    downstream = _expected("graph:output:FL", "FL", (3, 5, 6, 7), ingress=False)
    expectation = ProcessorTopologyExpectation(
        "graph",
        _GENERATION,
        (ingress, downstream),
    )
    current = replace(
        _snapshot(),
        links=(_link(1, downstream),),
    )

    downstream_only = verify_processor_topology(
        current,
        expectation,
        include_ingress=False,
    )
    stale = verify_processor_topology(
        replace(
            current,
            generation=_GENERATION + 1,
            health=replace(current.health, generation=_GENERATION + 1),
        ),
        expectation,
        include_ingress=True,
    )

    assert downstream_only.satisfied is True
    assert [item.expected.desired_id for item in downstream_only.links] == [downstream.desired_id]
    assert {item.status for item in stale.links} == {TopologyLinkStatus.STALE_GENERATION}
