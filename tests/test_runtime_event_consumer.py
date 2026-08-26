from dataclasses import replace

from wyreplumber.runtime import (
    ConnectionHealthValue,
    ConnectionState,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventQueueResnapshotRequired,
    RuntimeObjectKind,
)

from core.orchestration.runtime_event_consumer import RuntimeEventBatchStatus
from core.orchestration.runtime_world import WyrePlumberRuntimeOwner
from tests.test_endpoint_inventory_mapping import _snapshot

TIMESTAMP = "2026-08-22T16:00:00Z"


class FakeConnection:
    def stop(self):
        pass


def _event(sequence, *, generation=3, kind=RuntimeEventKind.OBJECT_CHANGED):
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
        current=(
            ConnectionHealthValue(ConnectionState.CONNECTED, generation)
            if kind is RuntimeEventKind.CONNECTION_CHANGED
            else {}
        ),
    )


def _owner(snapshots):
    values = list(snapshots)
    return WyrePlumberRuntimeOwner(
        connection_factory=FakeConnection,
        snapshot_capture=lambda _connection: values.pop(0),
        contract_checker=lambda _minimum, _maximum: None,
    )


def _reader(values):
    queue = list(values)

    def read(_connection, *, timeout=None):
        return queue.pop(0) if queue else None

    return read


def test_related_event_burst_is_coalesced_into_one_fresh_snapshot() -> None:
    initial = _snapshot(generation=3)
    final = replace(initial, sequence=initial.sequence + 2)
    owner = _owner((initial, final))
    owner.start()

    result = owner.consume_event_batch(
        timeout=1,
        next_event=_reader((_event(initial.sequence + 1), _event(initial.sequence + 2))),
        coalesce_window_seconds=1,
    )

    assert result.status is RuntimeEventBatchStatus.RESNAPSHOTTED
    assert result.event_count == 2
    assert result.reasons == ("coalesced_runtime_event_batch",)
    assert result.causes == {"node": ("42",)}
    assert owner.current.version == 2
    assert owner.current.position == (3, initial.sequence + 2)


def test_sequence_gap_forces_snapshot_at_or_after_the_gap() -> None:
    initial = _snapshot(generation=3)
    after_gap = replace(initial, sequence=initial.sequence + 3)
    owner = _owner((initial, after_gap))
    owner.start()

    result = owner.consume_event_batch(
        next_event=_reader((_event(initial.sequence + 3),)),
        coalesce_window_seconds=0,
    )

    assert result.reasons == (f"event_sequence_gap:{initial.sequence + 1}:{initial.sequence + 3}",)
    assert owner.current.position == (3, initial.sequence + 3)


def test_reconnect_event_forces_a_fresh_snapshot() -> None:
    initial = _snapshot(generation=3)
    reconnected = _snapshot(generation=4)
    owner = _owner((initial, reconnected))
    owner.start()

    result = owner.consume_event_batch(
        next_event=_reader(
            (
                _event(
                    1,
                    generation=4,
                    kind=RuntimeEventKind.CONNECTION_CHANGED,
                ),
            )
        ),
        coalesce_window_seconds=0,
    )

    assert "connection_generation_changed" in result.reasons
    assert owner.current.position == (4, reconnected.sequence)


def test_queue_overflow_signal_forces_fresh_snapshot_without_deltas() -> None:
    initial = _snapshot(generation=3)
    recovered = replace(initial, sequence=initial.sequence + 2)
    owner = _owner((initial, recovered))
    owner.start()

    def overflow(_connection, *, timeout=None):
        raise RuntimeEventQueueResnapshotRequired(
            generation=3,
            sequence=initial.sequence + 1,
            reason="native event queue capacity 1 exceeded",
        )

    result = owner.consume_event_batch(next_event=overflow)

    assert result.event_count == 0
    assert result.reasons == ("runtime_queue_discontinuity:native event queue capacity 1 exceeded",)
    assert owner.current.position == (3, initial.sequence + 2)


def test_idle_event_poll_does_not_create_a_new_world_version() -> None:
    initial = _snapshot(generation=3)
    owner = _owner((initial,))
    owner.start()

    result = owner.consume_event_batch(next_event=_reader(()))

    assert result.status is RuntimeEventBatchStatus.IDLE
    assert owner.current.version == 1
