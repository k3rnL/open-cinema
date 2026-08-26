from __future__ import annotations

import json
from dataclasses import dataclass
from threading import RLock

from wyreplumber.runtime import (
    FrozenDict,
    RuntimeSnapshot,
    capture_runtime_snapshot,
    require_orchestration_contract,
)

from .endpoint_inventory import EndpointInventorySnapshot, map_runtime_endpoints
from .endpoint_continuity import (
    InventoryContinuityAction,
    RuntimeInventoryContinuity,
)


class StaleRuntimeSnapshotError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrchestratorWorldSnapshot:
    version: int
    runtime: RuntimeSnapshot
    endpoints: EndpointInventorySnapshot

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("world version must be a positive integer")
        if not isinstance(self.runtime, RuntimeSnapshot):
            raise TypeError("runtime must be a detached RuntimeSnapshot")
        if not isinstance(self.endpoints, EndpointInventorySnapshot):
            raise TypeError("endpoints must be an EndpointInventorySnapshot")
        runtime_position = (self.runtime.generation, self.runtime.sequence)
        endpoint_position = (self.endpoints.generation, self.endpoints.sequence)
        if runtime_position != endpoint_position:
            raise ValueError("runtime and endpoint positions must match")

    @property
    def position(self) -> tuple[int, int]:
        return self.runtime.generation, self.runtime.sequence


class InMemoryWorldStore:
    """Thread-safe owner of the current immutable, authoritative world snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._current: OrchestratorWorldSnapshot | None = None

    @property
    def current(self) -> OrchestratorWorldSnapshot | None:
        with self._lock:
            return self._current

    def install_runtime_snapshot(
        self,
        runtime: RuntimeSnapshot,
    ) -> OrchestratorWorldSnapshot:
        if not isinstance(runtime, RuntimeSnapshot):
            raise TypeError("runtime must be a detached RuntimeSnapshot")
        with self._lock:
            current = self._current
            incoming = (runtime.generation, runtime.sequence)
            if current is not None:
                existing = current.position
                if incoming == existing:
                    return current
                if runtime.generation < existing[0] or (
                    runtime.generation == existing[0] and runtime.sequence < existing[1]
                ):
                    raise StaleRuntimeSnapshotError(
                        f"runtime snapshot {incoming} precedes current position {existing}"
                    )
            world = OrchestratorWorldSnapshot(
                version=(current.version + 1 if current is not None else 1),
                runtime=runtime,
                endpoints=map_runtime_endpoints(runtime),
            )
            self._current = world
            return world


@dataclass(frozen=True, slots=True)
class RedisProjectionPublishResult:
    delivered: bool
    key: str
    size_bytes: int
    endpoint_count: int
    total_endpoint_count: int
    truncated: bool
    ttl_seconds: int
    reason: str


class RedisWorldProjection:
    """Bounded, expiring UI projection; it is never read as authoritative state."""

    def __init__(
        self,
        client,
        *,
        key: str,
        ttl_seconds: int,
        max_bytes: int,
        max_endpoints: int,
    ) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Redis projection key must be a non-empty string")
        for name, value, minimum in (
            ("ttl_seconds", ttl_seconds, 1),
            ("max_bytes", max_bytes, 512),
            ("max_endpoints", max_endpoints, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
        self.client = client
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes
        self.max_endpoints = max_endpoints

    @staticmethod
    def _endpoint_document(candidate) -> dict[str, object]:
        return {
            "runtimeKey": candidate.runtime_key,
            "direction": candidate.direction.value,
            "name": candidate.name,
            "description": candidate.description,
            "mediaClass": candidate.media_class,
            "state": candidate.node_state,
            "error": candidate.node_error,
            "default": candidate.is_default,
            "linked": candidate.is_linked,
            "activeSignal": candidate.has_active_signal,
            "volume": candidate.volume,
            "mute": candidate.mute,
        }

    @staticmethod
    def _encode(document: dict[str, object]) -> bytes:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _document(self, world: OrchestratorWorldSnapshot) -> tuple[dict[str, object], bytes]:
        candidates = sorted(
            world.endpoints.candidates,
            key=lambda candidate: candidate.runtime_key,
        )
        total = len(candidates)
        endpoints = [
            self._endpoint_document(candidate) for candidate in candidates[: self.max_endpoints]
        ]
        document = {
            "schemaVersion": 1,
            "worldVersion": world.version,
            "runtimeGeneration": world.runtime.generation,
            "runtimeSequence": world.runtime.sequence,
            "capturedAt": world.runtime.captured_at,
            "connection": world.runtime.health.to_dict(),
            "counts": {
                "devices": len(world.runtime.devices),
                "nodes": len(world.runtime.nodes),
                "ports": len(world.runtime.ports),
                "links": len(world.runtime.links),
                "endpoints": total,
            },
            "endpoints": endpoints,
            "truncated": len(endpoints) < total,
        }
        encoded = self._encode(document)
        while len(encoded) > self.max_bytes and document["endpoints"]:
            document["endpoints"].pop()
            document["truncated"] = True
            encoded = self._encode(document)
        if len(encoded) > self.max_bytes:
            raise ValueError("Redis runtime projection metadata exceeds configured max_bytes")
        return document, encoded

    def publish(self, world: OrchestratorWorldSnapshot) -> RedisProjectionPublishResult:
        if not isinstance(world, OrchestratorWorldSnapshot):
            raise TypeError("world must be an OrchestratorWorldSnapshot")
        document, encoded = self._document(world)
        try:
            self.client.set(self.key, encoded, ex=self.ttl_seconds)
        except Exception:
            return RedisProjectionPublishResult(
                delivered=False,
                key=self.key,
                size_bytes=len(encoded),
                endpoint_count=len(document["endpoints"]),
                total_endpoint_count=document["counts"]["endpoints"],
                truncated=document["truncated"],
                ttl_seconds=self.ttl_seconds,
                reason="redis_publish_failed",
            )
        return RedisProjectionPublishResult(
            delivered=True,
            key=self.key,
            size_bytes=len(encoded),
            endpoint_count=len(document["endpoints"]),
            total_endpoint_count=document["counts"]["endpoints"],
            truncated=document["truncated"],
            ttl_seconds=self.ttl_seconds,
            reason="redis_projection_published",
        )


class WyrePlumberRuntimeOwner:
    """Own one connection for the full active-controller lifetime."""

    def __init__(
        self,
        *,
        connection_factory=None,
        snapshot_capture=capture_runtime_snapshot,
        contract_checker=require_orchestration_contract,
        store: InMemoryWorldStore | None = None,
        publisher: RedisWorldProjection | None = None,
    ) -> None:
        if connection_factory is None:
            from wyreplumber._core import WPConnection

            connection_factory = WPConnection
        self.connection_factory = connection_factory
        self.snapshot_capture = snapshot_capture
        self.contract_checker = contract_checker
        self.store = store or InMemoryWorldStore()
        self.publisher = publisher
        self.continuity = RuntimeInventoryContinuity()
        self._connection = None
        self._event_consumer = None

    @property
    def connection(self):
        return self._connection

    @property
    def current(self) -> OrchestratorWorldSnapshot | None:
        return self.store.current

    def start(self) -> OrchestratorWorldSnapshot:
        if self._connection is not None:
            current = self.store.current
            if current is None:
                raise RuntimeError("runtime owner has a connection without a world snapshot")
            return current
        self.contract_checker(1, 1)
        self._connection = self.connection_factory()
        try:
            return self.refresh()
        except Exception:
            self.stop()
            raise

    def refresh(self) -> OrchestratorWorldSnapshot:
        return self.resnapshot()

    def probe(self) -> None:
        """Confirm that the owned connection still reaches the PipeWire core."""

        if self._connection is None:
            raise RuntimeError("runtime owner must be started before probe")
        sync = getattr(self._connection, "sync", None)
        if not callable(sync):
            raise RuntimeError("WirePlumber connection does not support sync probes")
        sync()

    def resnapshot(self, *, max_attempts: int = 3) -> OrchestratorWorldSnapshot:
        if self._connection is None:
            raise RuntimeError("runtime owner must be started before refresh")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        last_decision = None
        for _attempt in range(max_attempts):
            runtime = self.snapshot_capture(self._connection)
            last_decision = self.continuity.accept_snapshot(runtime)
            if last_decision.action is InventoryContinuityAction.IGNORED:
                if not self.continuity.requires_full_remap:
                    world = self.store.current
                    if world is None:
                        raise RuntimeError("duplicate snapshot received before initial world")
                    self.publish_current()
                    return world
                continue
            world = self.store.install_runtime_snapshot(runtime)
            if self.publisher is not None:
                self.publisher.publish(world)
            return world
        raise RuntimeError(
            "fresh runtime snapshot did not satisfy continuity: "
            f"{last_decision.reason if last_decision is not None else 'unknown'}"
        )

    def publish_current(self) -> RedisProjectionPublishResult | None:
        world = self.store.current
        if world is None or self.publisher is None:
            return None
        return self.publisher.publish(world)

    def consume_event_batch(
        self,
        *,
        timeout: float | None = None,
        next_event=None,
        coalesce_window_seconds: float = 0.05,
        max_batch_events: int = 256,
    ):
        if self._event_consumer is None:
            from .runtime_event_consumer import RuntimeEventConsumer

            arguments = {
                "coalesce_window_seconds": coalesce_window_seconds,
                "max_batch_events": max_batch_events,
            }
            if next_event is not None:
                arguments["next_event"] = next_event
            self._event_consumer = RuntimeEventConsumer(
                self,
                self.continuity,
                **arguments,
            )
        return self._event_consumer.consume_once(timeout=timeout)

    def stop(self) -> None:
        connection = self._connection
        self._connection = None
        self._event_consumer = None
        if connection is not None:
            stop = getattr(connection, "stop", None)
            if callable(stop):
                stop()

    def __enter__(self) -> WyrePlumberRuntimeOwner:
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.stop()
