from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping

from wyreplumber.runtime import FrozenDict, NodeState, RuntimeSnapshot


_AVAILABLE_NODE_STATES = {
    NodeState.IDLE.value,
    NodeState.RUNNING.value,
    NodeState.SUSPENDED.value,
}


class ProcessorNodeMatchStatus(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no-match"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ManagedProcessorNodeIdentity:
    """Stable processor-port identity; PipeWire numeric IDs are operation targets only."""

    processor_kind: str
    instance_id: str
    port: str
    node_name: str
    node_group_name: str
    required_properties: FrozenDict | Mapping[str, object] = FrozenDict()

    def __post_init__(self) -> None:
        for field in (
            "processor_kind",
            "instance_id",
            "port",
            "node_name",
            "node_group_name",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        object.__setattr__(self, "required_properties", FrozenDict(self.required_properties))

    @property
    def stable_key(self) -> str:
        return f"processor:{self.processor_kind}:{self.instance_id}:{self.port}"

    def matches(self, node) -> bool:
        properties = node.properties
        observed_name = node.name or properties.get("node.name")
        if observed_name != self.node_name:
            return False
        if properties.get("node.group") != self.node_group_name:
            return False
        return all(properties.get(key) == value for key, value in self.required_properties.items())


@dataclass(frozen=True, slots=True)
class ManagedProcessorNodeCandidate:
    identity: ManagedProcessorNodeIdentity
    runtime_generation: int
    runtime_node_id: int
    state: str
    error: str | None
    properties: FrozenDict

    @property
    def runtime_key(self) -> str:
        return f"runtime:{self.runtime_generation}:node:{self.runtime_node_id}"

    def projection_document(self) -> dict[str, object]:
        return {
            "identity": {
                "key": self.identity.stable_key,
                "processorKind": self.identity.processor_kind,
                "instanceId": self.identity.instance_id,
                "port": self.identity.port,
                "nodeName": self.identity.node_name,
                "nodeGroupName": self.identity.node_group_name,
            },
            "runtimeKey": self.runtime_key,
            "runtimeKeyEphemeral": True,
            "state": self.state,
            "error": self.error,
            # PipeWire suspends an unlinked native stream to save resources.
            # Its ports remain matchable and a managed link wakes it, so this
            # is availability rather than processor degradation.
            "ready": self.state in _AVAILABLE_NODE_STATES and self.error is None,
        }


@dataclass(frozen=True, slots=True)
class ManagedProcessorNodeMatch:
    status: ProcessorNodeMatchStatus
    selected: ManagedProcessorNodeCandidate | None
    candidates: tuple[ManagedProcessorNodeCandidate, ...]


def match_managed_processor_node(
    snapshot: RuntimeSnapshot,
    identity: ManagedProcessorNodeIdentity,
) -> ManagedProcessorNodeMatch:
    if not isinstance(snapshot, RuntimeSnapshot):
        raise TypeError("snapshot must be a RuntimeSnapshot")
    if not isinstance(identity, ManagedProcessorNodeIdentity):
        raise TypeError("identity must be a ManagedProcessorNodeIdentity")
    candidates = tuple(
        ManagedProcessorNodeCandidate(
            identity=identity,
            runtime_generation=snapshot.generation,
            runtime_node_id=node.id,
            state=node.state.value,
            error=node.error,
            properties=node.properties,
        )
        for node in sorted(snapshot.nodes, key=lambda item: item.id)
        if identity.matches(node)
    )
    if not candidates:
        status = ProcessorNodeMatchStatus.NO_MATCH
        selected = None
    elif len(candidates) == 1:
        status = ProcessorNodeMatchStatus.MATCHED
        selected = candidates[0]
    else:
        status = ProcessorNodeMatchStatus.AMBIGUOUS
        selected = None
    return ManagedProcessorNodeMatch(status, selected, candidates)


def project_managed_processor_nodes(
    snapshot: RuntimeSnapshot,
    identities: tuple[ManagedProcessorNodeIdentity, ...],
) -> tuple[ManagedProcessorNodeMatch, ...]:
    stable_keys = [identity.stable_key for identity in identities]
    if len(stable_keys) != len(set(stable_keys)):
        raise ValueError("managed processor node identities must be unique")
    return tuple(
        match_managed_processor_node(snapshot, identity)
        for identity in sorted(identities, key=lambda item: item.stable_key)
    )


_CAMILLADSP_NAME = re.compile(
    r"^opencinema\.camilladsp\.(?P<index>[A-Za-z0-9_.-]+)\.(?P<port>capture|playback)$"
)


def discover_managed_processor_nodes(
    snapshot: RuntimeSnapshot,
) -> tuple[ManagedProcessorNodeCandidate, ...]:
    """Discover managed nodes from stable properties, including native CamillaDSP names."""

    if not isinstance(snapshot, RuntimeSnapshot):
        raise TypeError("snapshot must be a RuntimeSnapshot")
    discovered = []
    for node in snapshot.nodes:
        properties = node.properties
        node_name = node.name or properties.get("node.name")
        node_group = properties.get("node.group")
        if not isinstance(node_name, str) or not isinstance(node_group, str):
            continue
        processor_kind = properties.get("open-cinema.processor.kind") or properties.get(
            "opencinema.processor.kind"
        )
        instance_id = properties.get("open-cinema.processor.instance") or properties.get(
            "opencinema.processor.instance"
        )
        port = properties.get("open-cinema.processor.port") or properties.get(
            "opencinema.processor.port"
        )
        if not all(
            isinstance(value, str) and value for value in (processor_kind, instance_id, port)
        ):
            camilladsp = _CAMILLADSP_NAME.fullmatch(node_name)
            if camilladsp is None:
                continue
            processor_kind = "camilladsp"
            instance_id = f"camilladsp-{camilladsp.group('index')}"
            port = camilladsp.group("port")
        identity = ManagedProcessorNodeIdentity(
            processor_kind,
            instance_id,
            port,
            node_name,
            node_group,
        )
        discovered.append(
            ManagedProcessorNodeCandidate(
                identity,
                snapshot.generation,
                node.id,
                node.state.value,
                node.error,
                properties,
            )
        )
    return tuple(
        sorted(
            discovered,
            key=lambda item: (item.identity.stable_key, item.runtime_node_id),
        )
    )
