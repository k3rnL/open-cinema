import json
from dataclasses import replace

import pytest

from core.orchestration.runtime_world import (
    InMemoryWorldStore,
    RedisWorldProjection,
    StaleRuntimeSnapshotError,
    WyrePlumberRuntimeOwner,
)
from tests.test_endpoint_inventory_mapping import _snapshot


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expiries = {}

    def set(self, key, value, *, ex):
        self.values[key] = value
        self.expiries[key] = ex


def test_world_store_atomically_replaces_immutable_monotonic_snapshots() -> None:
    store = InMemoryWorldStore()
    first = store.install_runtime_snapshot(_snapshot(generation=3))
    duplicate = store.install_runtime_snapshot(_snapshot(generation=3))
    newer_runtime = replace(_snapshot(generation=3), sequence=10)
    newer = store.install_runtime_snapshot(newer_runtime)

    assert duplicate is first
    assert first.version == 1
    assert newer.version == 2
    assert newer.position == (3, 10)
    assert store.current is newer
    with pytest.raises(TypeError):
        newer.endpoints.candidates[0].node_properties["changed"] = True
    with pytest.raises(StaleRuntimeSnapshotError):
        store.install_runtime_snapshot(_snapshot(generation=2))


def test_redis_projection_is_bounded_expiring_and_non_authoritative() -> None:
    world = InMemoryWorldStore().install_runtime_snapshot(_snapshot())
    redis = FakeRedis()
    publisher = RedisWorldProjection(
        redis,
        key="runtime-world",
        ttl_seconds=30,
        max_bytes=700,
        max_endpoints=100,
    )

    result = publisher.publish(world)
    document = json.loads(redis.values["runtime-world"])

    assert result.size_bytes <= 700
    assert redis.expiries["runtime-world"] == 30
    assert document["worldVersion"] == 1
    assert document["runtimeGeneration"] == world.runtime.generation
    assert document["counts"]["endpoints"] == len(world.endpoints.candidates)
    assert result.truncated is True
    assert store_is_not_read_from_redis(publisher)


def test_redis_projection_failure_does_not_replace_or_break_runtime_world() -> None:
    world = InMemoryWorldStore().install_runtime_snapshot(_snapshot())

    class UnavailableRedis:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("redis restarting")

    publisher = RedisWorldProjection(
        UnavailableRedis(),
        key="runtime-world",
        ttl_seconds=30,
        max_bytes=4096,
        max_endpoints=100,
    )

    result = publisher.publish(world)

    assert result.delivered is False
    assert result.reason == "redis_publish_failed"
    assert world.version == 1


def store_is_not_read_from_redis(publisher) -> bool:
    return not hasattr(publisher, "load") and not hasattr(publisher, "current")


def test_runtime_owner_reuses_one_connection_and_stops_it_once() -> None:
    snapshots = [_snapshot(generation=3), replace(_snapshot(generation=3), sequence=10)]
    created = []
    contract_checks = []

    class FakeConnection:
        def __init__(self):
            self.stops = 0
            self.syncs = 0

        def sync(self):
            self.syncs += 1

        def stop(self):
            self.stops += 1

    def connection_factory():
        connection = FakeConnection()
        created.append(connection)
        return connection

    def capture(connection):
        assert connection is created[0]
        return snapshots.pop(0)

    owner = WyrePlumberRuntimeOwner(
        connection_factory=connection_factory,
        snapshot_capture=capture,
        contract_checker=lambda minimum, maximum: contract_checks.append(
            ("contract", minimum, maximum)
        ),
    )

    first = owner.start()
    owner.probe()
    second = owner.refresh()
    owner.stop()
    owner.stop()

    assert contract_checks == [("contract", 1, 1)]
    assert len(created) == 1
    assert first.version == 1
    assert second.version == 2
    assert created[0].syncs == 1
    assert created[0].stops == 1


def test_runtime_owner_probe_propagates_connection_failure() -> None:
    class FailedConnection:
        def sync(self):
            raise RuntimeError("WirePlumber sync failed")

        def stop(self):
            pass

    owner = WyrePlumberRuntimeOwner(
        connection_factory=FailedConnection,
        snapshot_capture=lambda _connection: _snapshot(),
        contract_checker=lambda _minimum, _maximum: None,
    )
    owner.start()

    with pytest.raises(RuntimeError, match="sync failed"):
        owner.probe()


def test_initial_capture_failure_closes_the_owned_connection() -> None:
    connection = type("Connection", (), {"stops": 0})()

    def stop():
        connection.stops += 1

    connection.stop = stop
    owner = WyrePlumberRuntimeOwner(
        connection_factory=lambda: connection,
        snapshot_capture=lambda _connection: (_ for _ in ()).throw(RuntimeError("capture")),
        contract_checker=lambda _minimum, _maximum: None,
    )

    with pytest.raises(RuntimeError, match="capture"):
        owner.start()

    assert connection.stops == 1
    assert owner.connection is None
