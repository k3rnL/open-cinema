from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import (
    ConnectionHealthValue,
    ConnectionState,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventQueueResnapshotRequired,
    RuntimeSnapshot,
)

from .endpoint_inventory import EndpointInventorySnapshot, map_runtime_endpoints


class InventoryContinuityAction(StrEnum):
    SNAPSHOT_ACCEPTED = "snapshot_accepted"
    EVENT_ACCEPTED = "event_accepted"
    IGNORED = "ignored"
    FULL_REMAP_REQUIRED = "full_remap_required"


@dataclass(frozen=True, slots=True)
class InventoryContinuityDecision:
    action: InventoryContinuityAction
    reason: str
    generation: int | None
    sequence: int | None


class RuntimeInventoryContinuity:
    """Guard endpoint inventory position across detached snapshots and events.

    This class deliberately does not mutate an inventory from an event payload.
    It establishes whether incremental event handling is safe. Consumers obtain a
    fresh snapshot whenever ``requires_full_remap`` becomes true and install it
    through :meth:`accept_snapshot`.
    """

    def __init__(self) -> None:
        self._inventory: EndpointInventorySnapshot | None = None
        self._generation: int | None = None
        self._sequence: int | None = None
        self._remap_reason: str | None = None
        self._minimum_remap_position: tuple[int, int] | None = None

    @property
    def inventory(self) -> EndpointInventorySnapshot | None:
        return self._inventory

    @property
    def generation(self) -> int | None:
        return self._generation

    @property
    def sequence(self) -> int | None:
        return self._sequence

    @property
    def requires_full_remap(self) -> bool:
        return self._remap_reason is not None

    @property
    def remap_reason(self) -> str | None:
        return self._remap_reason

    def _decision(
        self,
        action: InventoryContinuityAction,
        reason: str,
    ) -> InventoryContinuityDecision:
        return InventoryContinuityDecision(
            action=action,
            reason=reason,
            generation=self._generation,
            sequence=self._sequence,
        )

    def _require_full_remap(
        self,
        reason: str,
        *,
        minimum_position: tuple[int, int] | None = None,
    ) -> InventoryContinuityDecision:
        if self._remap_reason is None:
            self._remap_reason = reason
        if minimum_position is not None:
            current = self._minimum_remap_position
            if (
                current is None
                or minimum_position[0] > current[0]
                or (minimum_position[0] == current[0] and minimum_position[1] > current[1])
            ):
                self._minimum_remap_position = minimum_position
        return self._decision(
            InventoryContinuityAction.FULL_REMAP_REQUIRED,
            self._remap_reason,
        )

    def accept_snapshot(self, snapshot: RuntimeSnapshot) -> InventoryContinuityDecision:
        if not isinstance(snapshot, RuntimeSnapshot):
            raise TypeError("snapshot must be a detached WyrePlumber RuntimeSnapshot")
        position = (snapshot.generation, snapshot.sequence)
        if self._generation is not None:
            current_position = (self._generation, self._sequence)
            if snapshot.generation < self._generation:
                return self._decision(
                    InventoryContinuityAction.IGNORED,
                    "delayed_snapshot_generation",
                )
            if position == current_position:
                inventory_position = (
                    (self._inventory.generation, self._inventory.sequence)
                    if self._inventory is not None
                    else None
                )
                if inventory_position == position and not self.requires_full_remap:
                    return self._decision(
                        InventoryContinuityAction.IGNORED,
                        "duplicate_snapshot",
                    )
            if snapshot.generation == self._generation and snapshot.sequence < self._sequence:
                return self._decision(
                    InventoryContinuityAction.IGNORED,
                    "delayed_snapshot_sequence",
                )

        minimum = self._minimum_remap_position
        if minimum is not None and (
            snapshot.generation < minimum[0]
            or (snapshot.generation == minimum[0] and snapshot.sequence < minimum[1])
        ):
            return self._decision(
                InventoryContinuityAction.IGNORED,
                "snapshot_precedes_remap_trigger",
            )

        self._inventory = map_runtime_endpoints(snapshot)
        self._generation = snapshot.generation
        self._sequence = snapshot.sequence
        self._remap_reason = None
        self._minimum_remap_position = None
        return self._decision(
            InventoryContinuityAction.SNAPSHOT_ACCEPTED,
            "snapshot_mapped",
        )

    def accept_event(self, event: RuntimeEvent) -> InventoryContinuityDecision:
        if not isinstance(event, RuntimeEvent):
            raise TypeError("event must be a detached WyrePlumber RuntimeEvent")
        if self._generation is None:
            return self._require_full_remap(
                "initial_snapshot_required",
                minimum_position=(event.generation, event.sequence),
            )
        if event.generation < self._generation:
            return self._decision(
                InventoryContinuityAction.IGNORED,
                "delayed_event_generation",
            )
        if event.generation > self._generation:
            return self._require_full_remap(
                "connection_generation_changed",
                minimum_position=(event.generation, event.sequence),
            )
        if event.sequence <= self._sequence:
            return self._decision(
                InventoryContinuityAction.IGNORED,
                "delayed_or_duplicate_event_sequence",
            )
        if self.requires_full_remap:
            return self._require_full_remap(
                self._remap_reason or "full_remap_already_required",
                minimum_position=(event.generation, event.sequence),
            )

        expected_sequence = self._sequence + 1
        if event.sequence != expected_sequence:
            return self._require_full_remap(
                f"event_sequence_gap:{expected_sequence}:{event.sequence}",
                minimum_position=(event.generation, event.sequence),
            )
        if event.requires_resnapshot:
            reason = event.reason or event.kind.value
            return self._require_full_remap(
                f"runtime_discontinuity:{reason}",
                minimum_position=(event.generation, event.sequence),
            )
        if (
            event.kind is RuntimeEventKind.CONNECTION_CHANGED
            and isinstance(event.current, ConnectionHealthValue)
            and event.current.state
            in {
                ConnectionState.CONNECTING,
                ConnectionState.CONNECTED,
                ConnectionState.RECONNECTING,
            }
        ):
            return self._require_full_remap(
                f"runtime_reconnected:{event.current.state.value}",
                minimum_position=(event.generation, event.sequence),
            )

        self._sequence = event.sequence
        return self._decision(
            InventoryContinuityAction.EVENT_ACCEPTED,
            "event_contiguous",
        )

    def queue_requires_resnapshot(
        self,
        error: RuntimeEventQueueResnapshotRequired,
    ) -> InventoryContinuityDecision:
        if not isinstance(error, RuntimeEventQueueResnapshotRequired):
            raise TypeError("error must be RuntimeEventQueueResnapshotRequired")
        if self._generation is not None and error.generation < self._generation:
            return self._decision(
                InventoryContinuityAction.IGNORED,
                "delayed_queue_generation",
            )
        return self._require_full_remap(
            f"runtime_queue_discontinuity:{error.reason}",
            minimum_position=(error.generation, error.sequence),
        )
