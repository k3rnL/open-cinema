from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import RuntimeSnapshot

from .wireplumber_driver import OPEN_CINEMA_LINK_OWNER


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _runtime_identifier(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ExpectedManagedLink:
    desired_id: str
    edge_id: str
    channel: str
    runtime_generation: int
    output_node_id: int
    output_port_id: int
    input_node_id: int
    input_port_id: int
    processor_edge: bool
    ingress: bool

    def __post_init__(self) -> None:
        for field in ("desired_id", "edge_id", "channel"):
            object.__setattr__(self, field, _required_string(getattr(self, field), field))
        if (
            isinstance(self.runtime_generation, bool)
            or not isinstance(self.runtime_generation, int)
            or self.runtime_generation < 1
        ):
            raise ValueError("runtime_generation must be a positive integer")
        for field in (
            "output_node_id",
            "output_port_id",
            "input_node_id",
            "input_port_id",
        ):
            object.__setattr__(
                self,
                field,
                _runtime_identifier(getattr(self, field), field),
            )
        if not isinstance(self.processor_edge, bool):
            raise TypeError("processor_edge must be a boolean")
        if not isinstance(self.ingress, bool):
            raise TypeError("ingress must be a boolean")
        if self.ingress and not self.processor_edge:
            raise ValueError("ingress links must belong to a processor edge")

    @property
    def endpoints(self) -> tuple[int, int, int, int]:
        return (
            self.output_node_id,
            self.output_port_id,
            self.input_node_id,
            self.input_port_id,
        )

    def to_document(self) -> dict[str, object]:
        return {
            "desiredId": self.desired_id,
            "edgeId": self.edge_id,
            "channel": self.channel,
            "runtimeGeneration": self.runtime_generation,
            "outputNodeRuntimeKey": (
                f"runtime:{self.runtime_generation}:node:{self.output_node_id}"
            ),
            "outputPortRuntimeKey": (
                f"runtime:{self.runtime_generation}:port:{self.output_port_id}"
            ),
            "inputNodeRuntimeKey": (f"runtime:{self.runtime_generation}:node:{self.input_node_id}"),
            "inputPortRuntimeKey": (f"runtime:{self.runtime_generation}:port:{self.input_port_id}"),
            "processorEdge": self.processor_edge,
            "ingress": self.ingress,
        }


@dataclass(frozen=True, slots=True)
class ProcessorTopologyExpectation:
    graph_definition_id: str
    runtime_generation: int
    links: tuple[ExpectedManagedLink, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "graph_definition_id",
            _required_string(self.graph_definition_id, "graph_definition_id"),
        )
        if (
            isinstance(self.runtime_generation, bool)
            or not isinstance(self.runtime_generation, int)
            or self.runtime_generation < 1
        ):
            raise ValueError("runtime_generation must be a positive integer")
        links = tuple(self.links)
        if any(not isinstance(link, ExpectedManagedLink) for link in links):
            raise TypeError("links must contain ExpectedManagedLink values")
        if any(link.runtime_generation != self.runtime_generation for link in links):
            raise ValueError("all expected links must use the topology runtime generation")
        desired_ids = [link.desired_id for link in links]
        if len(desired_ids) != len(set(desired_ids)):
            raise ValueError("expected managed-link identities must be unique")
        object.__setattr__(self, "links", links)

    @property
    def processor_links(self) -> tuple[ExpectedManagedLink, ...]:
        return tuple(link for link in self.links if link.processor_edge)

    @property
    def ingress_links(self) -> tuple[ExpectedManagedLink, ...]:
        return tuple(link for link in self.processor_links if link.ingress)

    @property
    def downstream_links(self) -> tuple[ExpectedManagedLink, ...]:
        return tuple(link for link in self.processor_links if not link.ingress)


class TopologyLinkStatus(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    ENDPOINT_MISMATCH = "endpoint-mismatch"
    STALE_GENERATION = "stale-generation"


@dataclass(frozen=True, slots=True)
class TopologyLinkEvidence:
    expected: ExpectedManagedLink
    status: TopologyLinkStatus
    observed_link_ids: tuple[int, ...] = ()
    observed_endpoints: tuple[tuple[int, int, int, int], ...] = ()

    def to_document(self) -> dict[str, object]:
        return {
            **self.expected.to_document(),
            "status": self.status.value,
            "observedLinkIds": list(self.observed_link_ids),
            "observedEndpoints": [list(item) for item in self.observed_endpoints],
        }


@dataclass(frozen=True, slots=True)
class ProcessorTopologyVerification:
    expected_generation: int
    observed_generation: int
    include_ingress: bool
    links: tuple[TopologyLinkEvidence, ...]

    @property
    def satisfied(self) -> bool:
        return all(link.status is TopologyLinkStatus.SATISFIED for link in self.links)

    @property
    def missing_channels(self) -> tuple[str, ...]:
        return tuple(
            link.expected.channel
            for link in self.links
            if link.status is not TopologyLinkStatus.SATISFIED
        )

    def to_document(self) -> dict[str, object]:
        counts = {
            status.value: sum(1 for link in self.links if link.status is status)
            for status in TopologyLinkStatus
        }
        return {
            "satisfied": self.satisfied,
            "expectedRuntimeGeneration": self.expected_generation,
            "observedRuntimeGeneration": self.observed_generation,
            "scope": "complete" if self.include_ingress else "downstream",
            "counts": counts,
            "missingChannels": list(self.missing_channels),
            "links": [link.to_document() for link in self.links],
        }


def verify_processor_topology(
    runtime: RuntimeSnapshot,
    expectation: ProcessorTopologyExpectation,
    *,
    include_ingress: bool,
) -> ProcessorTopologyVerification:
    if not isinstance(runtime, RuntimeSnapshot):
        raise TypeError("runtime must be a detached RuntimeSnapshot")
    if not isinstance(expectation, ProcessorTopologyExpectation):
        raise TypeError("expectation must be a ProcessorTopologyExpectation")
    if not isinstance(include_ingress, bool):
        raise TypeError("include_ingress must be a boolean")

    expected_links = (
        expectation.processor_links if include_ingress else expectation.downstream_links
    )
    if runtime.generation != expectation.runtime_generation:
        evidence = tuple(
            TopologyLinkEvidence(expected, TopologyLinkStatus.STALE_GENERATION)
            for expected in expected_links
        )
        return ProcessorTopologyVerification(
            expectation.runtime_generation,
            runtime.generation,
            include_ingress,
            evidence,
        )

    evidence = []
    for expected in expected_links:
        matches = tuple(
            link
            for link in runtime.links
            if link.owner == OPEN_CINEMA_LINK_OWNER and link.desired_id == expected.desired_id
        )
        endpoints = tuple(
            (
                link.output_node_id,
                link.output_port_id,
                link.input_node_id,
                link.input_port_id,
            )
            for link in matches
        )
        if not matches:
            status = TopologyLinkStatus.MISSING
        elif len(matches) > 1:
            status = TopologyLinkStatus.DUPLICATE
        elif endpoints[0] != expected.endpoints:
            status = TopologyLinkStatus.ENDPOINT_MISMATCH
        else:
            status = TopologyLinkStatus.SATISFIED
        evidence.append(
            TopologyLinkEvidence(
                expected,
                status,
                tuple(link.id for link in matches),
                endpoints,
            )
        )
    return ProcessorTopologyVerification(
        expectation.runtime_generation,
        runtime.generation,
        include_ingress,
        tuple(evidence),
    )
