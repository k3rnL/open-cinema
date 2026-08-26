from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .camilladsp_config import CamillaDSPEndpoint
from .processor_runtime import ManagedProcessorNodeIdentity
from .resolver_inputs import ResolverResourceInput


@dataclass(frozen=True, slots=True)
class CamillaDSPDeploymentPolicy:
    instance_count: int = 1
    base_control_port: int = 1234
    bus_prefix: str = "opencinema.camilladsp"
    sharing_policy: str = "exclusive"
    reconfiguration_policy: str = "reconfigure-idle"
    conflict_policy: str = "priority"

    def __post_init__(self) -> None:
        if (
            isinstance(self.instance_count, bool)
            or not isinstance(self.instance_count, int)
            or not 1 <= self.instance_count <= 16
        ):
            raise ValueError("CamillaDSP instance_count must be between 1 and 16")
        if (
            isinstance(self.base_control_port, bool)
            or not isinstance(self.base_control_port, int)
            or not 1 <= self.base_control_port <= 65535
            or self.base_control_port + self.instance_count - 1 > 65535
        ):
            raise ValueError("CamillaDSP control port range is invalid")
        if not isinstance(self.bus_prefix, str) or not self.bus_prefix:
            raise ValueError("CamillaDSP bus_prefix must be non-empty")
        if self.sharing_policy != "exclusive":
            raise ValueError("the first release supports only exclusive CamillaDSP instances")
        if self.reconfiguration_policy != "reconfigure-idle":
            raise ValueError("CamillaDSP instances may only be reconfigured between allocations")
        if self.conflict_policy != "priority":
            raise ValueError("CamillaDSP conflicts must use deterministic priority policy")

    def resource_id(self, index: int) -> str:
        self._check_index(index)
        return f"camilladsp:{index}"

    def instance_id(self, index: int) -> str:
        self._check_index(index)
        return f"camilladsp-{index}"

    def control_port(self, index: int) -> int:
        self._check_index(index)
        return self.base_control_port + index

    def endpoints(self, index: int) -> tuple[CamillaDSPEndpoint, CamillaDSPEndpoint]:
        self._check_index(index)
        prefix = f"{self.bus_prefix}.{index}"
        group = f"{prefix}.group"
        return (
            CamillaDSPEndpoint(
                logical_id=f"processor:camilladsp:{index}:input",
                node_name=f"{prefix}.capture",
                node_description=f"Open Cinema CamillaDSP {index} Capture",
                node_group_name=group,
            ),
            CamillaDSPEndpoint(
                logical_id=f"processor:camilladsp:{index}:output",
                node_name=f"{prefix}.playback",
                node_description=f"Open Cinema CamillaDSP {index} Playback",
                node_group_name=group,
            ),
        )

    def resources(
        self,
        health: Mapping[str, str] | None = None,
    ) -> tuple[ResolverResourceInput, ...]:
        health = health or {}
        return tuple(
            ResolverResourceInput(
                resource_id=self.resource_id(index),
                kind="camilladsp",
                capacity=1,
                allocated=0,
                health=health.get(self.resource_id(index), "ready"),
            )
            for index in range(self.instance_count)
        )

    def runtime_identities(self, index: int) -> tuple[ManagedProcessorNodeIdentity, ...]:
        capture, playback = self.endpoints(index)
        instance_id = self.instance_id(index)
        return (
            ManagedProcessorNodeIdentity(
                "camilladsp",
                instance_id,
                "capture",
                capture.node_name,
                capture.node_group_name,
            ),
            ManagedProcessorNodeIdentity(
                "camilladsp",
                instance_id,
                "playback",
                playback.node_name,
                playback.node_group_name,
            ),
        )

    def driver_defaults(self, index: int) -> dict[str, object]:
        capture, playback = self.endpoints(index)
        return {
            "instanceId": self.instance_id(index),
            "controlHost": "127.0.0.1",
            "controlPort": self.control_port(index),
            "sharingPolicy": self.sharing_policy,
            "reconfigurationPolicy": self.reconfiguration_policy,
            "conflictPolicy": self.conflict_policy,
            "captureEndpoint": capture.to_document(),
            "playbackEndpoint": playback.to_document(),
        }

    def _check_index(self, index: int) -> None:
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < self.instance_count
        ):
            raise ValueError("CamillaDSP instance index is outside deployment capacity")
