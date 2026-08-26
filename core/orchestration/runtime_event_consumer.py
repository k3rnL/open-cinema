from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from wyreplumber.runtime import (
    FrozenDict,
    RuntimeEvent,
    RuntimeEventQueueClosed,
    RuntimeEventQueueResnapshotRequired,
    next_runtime_event,
)

from .endpoint_continuity import InventoryContinuityAction, RuntimeInventoryContinuity


class RuntimeEventBatchStatus(StrEnum):
    IDLE = "idle"
    RESNAPSHOTTED = "resnapshotted"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RuntimeEventBatchResult:
    status: RuntimeEventBatchStatus
    event_count: int
    first_sequence: int | None
    last_sequence: int | None
    world_version: int | None
    reasons: tuple[str, ...]
    causes: FrozenDict


class RuntimeEventConsumer:
    """Coalesce detached event bursts and replace state from one coherent snapshot."""

    def __init__(
        self,
        owner,
        continuity: RuntimeInventoryContinuity,
        *,
        next_event=next_runtime_event,
        coalesce_window_seconds: float = 0.05,
        max_batch_events: int = 256,
    ) -> None:
        if not isinstance(continuity, RuntimeInventoryContinuity):
            raise TypeError("continuity must be RuntimeInventoryContinuity")
        if (
            isinstance(coalesce_window_seconds, bool)
            or not isinstance(coalesce_window_seconds, (int, float))
            or coalesce_window_seconds < 0
        ):
            raise ValueError("coalesce_window_seconds must be non-negative")
        if (
            isinstance(max_batch_events, bool)
            or not isinstance(max_batch_events, int)
            or max_batch_events < 1
        ):
            raise ValueError("max_batch_events must be a positive integer")
        self.owner = owner
        self.continuity = continuity
        self.next_event = next_event
        self.coalesce_window_seconds = float(coalesce_window_seconds)
        self.max_batch_events = max_batch_events

    @staticmethod
    def _causes(events: tuple[RuntimeEvent, ...]) -> FrozenDict:
        grouped: dict[str, list[str]] = {}
        for event in events:
            values = grouped.setdefault(event.object_kind.value, [])
            identity = str(event.object_id)
            if identity not in values:
                values.append(identity)
        return FrozenDict(
            {kind: sorted(identities) for kind, identities in sorted(grouped.items())}
        )

    def _result(
        self,
        status: RuntimeEventBatchStatus,
        events: tuple[RuntimeEvent, ...],
        *,
        world_version: int | None = None,
        reasons=(),
    ) -> RuntimeEventBatchResult:
        return RuntimeEventBatchResult(
            status=status,
            event_count=len(events),
            first_sequence=events[0].sequence if events else None,
            last_sequence=events[-1].sequence if events else None,
            world_version=world_version,
            reasons=tuple(sorted(set(reasons))),
            causes=self._causes(events),
        )

    def consume_once(self, *, timeout: float | None = None) -> RuntimeEventBatchResult:
        connection = self.owner.connection
        if connection is None:
            raise RuntimeError("runtime owner must be started before consuming events")
        try:
            first = self.next_event(connection, timeout=timeout)
        except RuntimeEventQueueResnapshotRequired as error:
            decision = self.continuity.queue_requires_resnapshot(error)
            world = self.owner.resnapshot()
            return self._result(
                RuntimeEventBatchStatus.RESNAPSHOTTED,
                (),
                world_version=world.version,
                reasons=(decision.reason,),
            )
        except RuntimeEventQueueClosed:
            return self._result(RuntimeEventBatchStatus.CLOSED, ())
        if first is None:
            self.owner.publish_current()
            return self._result(RuntimeEventBatchStatus.IDLE, ())

        events = [first]
        deadline = monotonic() + self.coalesce_window_seconds
        while len(events) < self.max_batch_events:
            remaining = max(0.0, deadline - monotonic())
            if remaining <= 0 and self.coalesce_window_seconds > 0:
                break
            try:
                event = self.next_event(connection, timeout=remaining)
            except RuntimeEventQueueResnapshotRequired as error:
                decision = self.continuity.queue_requires_resnapshot(error)
                world = self.owner.resnapshot()
                return self._result(
                    RuntimeEventBatchStatus.RESNAPSHOTTED,
                    tuple(events),
                    world_version=world.version,
                    reasons=(decision.reason,),
                )
            except RuntimeEventQueueClosed:
                break
            if event is None:
                break
            events.append(event)

        reasons = []
        accepted = False
        for event in events:
            decision = self.continuity.accept_event(event)
            if decision.action is InventoryContinuityAction.EVENT_ACCEPTED:
                accepted = True
            elif decision.action is InventoryContinuityAction.FULL_REMAP_REQUIRED:
                reasons.append(decision.reason)
        if accepted and not reasons:
            reasons.append("coalesced_runtime_event_batch")
        world = self.owner.resnapshot()
        return self._result(
            RuntimeEventBatchStatus.RESNAPSHOTTED,
            tuple(events),
            world_version=world.version,
            reasons=reasons,
        )
