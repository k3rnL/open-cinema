from wyreplumber.runtime import (
    ConnectionHealthValue,
    ConnectionState,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventQueueResnapshotRequired,
    RuntimeObjectKind,
    RuntimeSnapshot,
)

from core.orchestration.endpoint_continuity import (
    InventoryContinuityAction,
    RuntimeInventoryContinuity,
)

TIMESTAMP = "2026-08-22T13:00:00Z"


def _snapshot(generation: int, sequence: int) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        generation=generation,
        sequence=sequence,
        captured_at=TIMESTAMP,
        health=ConnectionHealthValue(
            state=ConnectionState.CONNECTED,
            generation=generation,
        ),
    )


def _event(
    generation: int,
    sequence: int,
    *,
    kind: RuntimeEventKind = RuntimeEventKind.OBJECT_CHANGED,
    current=None,
) -> RuntimeEvent:
    return RuntimeEvent(
        generation=generation,
        sequence=sequence,
        occurred_at=TIMESTAMP,
        kind=kind,
        object_kind=(
            RuntimeObjectKind.CONNECTION
            if kind is RuntimeEventKind.CONNECTION_CHANGED
            else RuntimeObjectKind.NODE
        ),
        object_id="connection" if kind is RuntimeEventKind.CONNECTION_CHANGED else 42,
        current={} if current is None else current,
    )


def test_delayed_generation_and_sequence_events_never_revert_position() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(4, 10))

    old_generation = continuity.accept_event(_event(3, 100))
    duplicate_sequence = continuity.accept_event(_event(4, 10))

    assert old_generation.action is InventoryContinuityAction.IGNORED
    assert old_generation.reason == "delayed_event_generation"
    assert duplicate_sequence.action is InventoryContinuityAction.IGNORED
    assert continuity.generation == 4
    assert continuity.sequence == 10
    assert not continuity.requires_full_remap


def test_contiguous_event_advances_position_but_gap_requires_full_remap() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(4, 10))

    accepted = continuity.accept_event(_event(4, 11))
    gap = continuity.accept_event(_event(4, 13))

    assert accepted.action is InventoryContinuityAction.EVENT_ACCEPTED
    assert continuity.sequence == 11
    assert gap.action is InventoryContinuityAction.FULL_REMAP_REQUIRED
    assert gap.reason == "event_sequence_gap:12:13"
    assert continuity.requires_full_remap


def test_snapshot_at_accepted_event_position_refreshes_stale_inventory() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(4, 10))
    continuity.accept_event(_event(4, 11))

    refreshed = continuity.accept_snapshot(_snapshot(4, 11))

    assert refreshed.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert continuity.inventory.sequence == 11


def test_overflow_discontinuity_requires_snapshot_at_or_after_trigger() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(2, 5))
    overflow = RuntimeEvent.discontinuity(
        generation=2,
        sequence=6,
        occurred_at=TIMESTAMP,
        reason="event queue capacity 64 exceeded",
    )

    decision = continuity.accept_event(overflow)
    stale_snapshot = continuity.accept_snapshot(_snapshot(2, 5))
    replacement = continuity.accept_snapshot(_snapshot(2, 7))

    assert decision.action is InventoryContinuityAction.FULL_REMAP_REQUIRED
    assert "capacity 64 exceeded" in decision.reason
    assert stale_snapshot.action is InventoryContinuityAction.IGNORED
    assert replacement.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert continuity.sequence == 7
    assert not continuity.requires_full_remap


def test_queue_overflow_exception_requires_full_remap() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(7, 30))
    error = RuntimeEventQueueResnapshotRequired(
        generation=7,
        sequence=31,
        reason="event queue capacity 8 exceeded",
    )

    decision = continuity.queue_requires_resnapshot(error)

    assert decision.action is InventoryContinuityAction.FULL_REMAP_REQUIRED
    assert decision.reason == ("runtime_queue_discontinuity:event queue capacity 8 exceeded")


def test_reconnect_event_triggers_full_remap_even_when_sequence_is_contiguous() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(9, 1))
    connected = _event(
        9,
        2,
        kind=RuntimeEventKind.CONNECTION_CHANGED,
        current=ConnectionHealthValue(
            state=ConnectionState.CONNECTED,
            generation=9,
        ),
    )

    decision = continuity.accept_event(connected)

    assert decision.action is InventoryContinuityAction.FULL_REMAP_REQUIRED
    assert decision.reason == "runtime_reconnected:connected"
    assert continuity.sequence == 1


def test_new_generation_requires_remap_and_old_snapshot_cannot_satisfy_it() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(11, 50))

    decision = continuity.accept_event(_event(12, 1))
    old_snapshot = continuity.accept_snapshot(_snapshot(11, 51))
    new_snapshot = continuity.accept_snapshot(_snapshot(12, 2))

    assert decision.action is InventoryContinuityAction.FULL_REMAP_REQUIRED
    assert decision.reason == "connection_generation_changed"
    assert old_snapshot.action is InventoryContinuityAction.IGNORED
    assert new_snapshot.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert continuity.generation == 12
    assert continuity.sequence == 2


def test_older_snapshot_is_ignored_after_newer_snapshot() -> None:
    continuity = RuntimeInventoryContinuity()
    continuity.accept_snapshot(_snapshot(3, 10))

    decision = continuity.accept_snapshot(_snapshot(2, 999))

    assert decision.action is InventoryContinuityAction.IGNORED
    assert decision.reason == "delayed_snapshot_generation"
    assert continuity.generation == 3
    assert continuity.sequence == 10
