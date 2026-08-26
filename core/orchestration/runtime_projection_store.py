from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from django.db import transaction

from api.models import ManagedAudioAdapterRuntimeState, RuntimeProjection

from .runtime_world import OrchestratorWorldSnapshot
from .processor_runtime import _AVAILABLE_NODE_STATES, discover_managed_processor_nodes


@dataclass(frozen=True, slots=True)
class RuntimeProjectionPublishResult:
    created: int
    retired: int
    unchanged: int
    ignored: bool


class DatabaseRuntimeProjectionStore:
    """Publish the current detached runtime world for API/UI consumers.

    The in-memory world remains authoritative. These short database records are
    replaceable projections used by the web process, which does not share the
    orchestrator's WirePlumber connection.
    """

    PROJECTION_TYPES = (
        "endpoint-candidate",
        "managed-resource",
        "processor-health",
        "orchestration-health",
    )
    HEALTH_SUBJECT = "orchestrator"

    def __init__(self) -> None:
        self._lock = RLock()
        self._position: tuple[int, int] | None = None

    def publish(
        self,
        world: OrchestratorWorldSnapshot,
        *,
        health: dict[str, object] | None = None,
    ) -> RuntimeProjectionPublishResult:
        if not isinstance(world, OrchestratorWorldSnapshot):
            raise TypeError("world must be an OrchestratorWorldSnapshot")
        if health is not None and not isinstance(health, dict):
            raise TypeError("health must be a dictionary or None")

        position = world.position
        with self._lock:
            if self._position is not None and position < self._position:
                return RuntimeProjectionPublishResult(0, 0, 0, True)

            observed_at = _observed_at(world.runtime.captured_at)
            adapter_states = {
                str(state.adapter_id): state
                for state in ManagedAudioAdapterRuntimeState.objects.all()
            }
            documents = {}
            for candidate in world.endpoints.candidates:
                payload = candidate.projection_document()
                adapter = payload.get("managedAdapter")
                if isinstance(adapter, dict):
                    state = adapter_states.get(str(adapter.get("id")))
                    adapter.update(
                        {
                            "lifecycle": state.lifecycle if state is not None else "unknown",
                            "health": state.health if state is not None else "unknown",
                            "runtimeGeneration": (
                                state.runtime_generation if state is not None else 0
                            ),
                            "localReady": bool(state is not None and state.lifecycle == "ready"),
                        }
                    )
                documents[("endpoint-candidate", candidate.runtime_key)] = _json_document(payload)
            processor_nodes = discover_managed_processor_nodes(world.runtime)
            processor_groups: dict[tuple[str, str], list[object]] = {}
            for candidate in processor_nodes:
                documents[("managed-resource", candidate.identity.stable_key)] = _json_document(
                    candidate.projection_document()
                )
                processor_groups.setdefault(
                    (candidate.identity.processor_kind, candidate.identity.instance_id), []
                ).append(candidate)
            for (kind, instance_id), candidates in processor_groups.items():
                duplicate_keys = len({item.identity.stable_key for item in candidates}) != len(
                    candidates
                )
                ready = not duplicate_keys and all(
                    item.state in _AVAILABLE_NODE_STATES and item.error is None
                    for item in candidates
                )
                documents[("processor-health", f"processor:{kind}:{instance_id}")] = _json_document(
                    {
                        "processorId": f"processor:{kind}:{instance_id}",
                        "kind": kind,
                        "instanceId": instance_id,
                        "ready": ready,
                        "health": "healthy" if ready else "degraded",
                        "nodes": [
                            item.projection_document()["identity"]
                            for item in sorted(
                                candidates, key=lambda value: value.identity.stable_key
                            )
                        ],
                        "diagnostics": (
                            ["duplicate-stable-processor-node"] if duplicate_keys else []
                        ),
                    }
                )
            documents[("orchestration-health", self.HEALTH_SUBJECT)] = _json_document(
                {
                    **(health or {}),
                    "worldVersion": world.version,
                    "runtimeGeneration": world.runtime.generation,
                    "runtimeSequence": world.runtime.sequence,
                    "connection": world.runtime.health.to_dict(),
                    "counts": {
                        "devices": len(world.runtime.devices),
                        "nodes": len(world.runtime.nodes),
                        "ports": len(world.runtime.ports),
                        "links": len(world.runtime.links),
                        "endpoints": len(world.endpoints.candidates),
                        "processorNodes": len(processor_nodes),
                        "processors": len(processor_groups),
                    },
                }
            )

            with transaction.atomic():
                current = {
                    (item.projection_type, item.subject_key): item
                    for item in RuntimeProjection.objects.select_for_update().filter(
                        is_current=True,
                        projection_type__in=self.PROJECTION_TYPES,
                    )
                }
                unchanged_keys = {
                    key
                    for key, payload in documents.items()
                    if (existing := current.get(key)) is not None
                    and existing.world_generation == position[0]
                    and existing.world_sequence == position[1]
                    and existing.observed_at == observed_at
                    and _equivalent_payload(key[0], existing.payload, payload)
                }
                retire_ids = [item.pk for key, item in current.items() if key not in unchanged_keys]
                if retire_ids:
                    RuntimeProjection.objects.filter(pk__in=retire_ids).update(is_current=False)

                replacements = [
                    RuntimeProjection(
                        projection_type=projection_type,
                        subject_key=subject_key,
                        world_generation=position[0],
                        world_sequence=position[1],
                        payload=payload,
                        observed_at=observed_at,
                    )
                    for (projection_type, subject_key), payload in documents.items()
                    if (projection_type, subject_key) not in unchanged_keys
                ]
                RuntimeProjection.objects.bulk_create(replacements)

            self._position = position
            return RuntimeProjectionPublishResult(
                created=len(replacements),
                retired=len(retire_ids),
                unchanged=len(unchanged_keys),
                ignored=False,
            )


def _observed_at(value: str) -> datetime:
    observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed_at.tzinfo is None:
        raise ValueError("runtime captured_at must include a timezone")
    return observed_at


def _equivalent_payload(
    projection_type: str,
    current: dict[str, object],
    incoming: dict[str, object],
) -> bool:
    if projection_type != "orchestration-health":
        return current == incoming
    volatile = {"sequence", "lastSuccessAt"}
    return {key: value for key, value in current.items() if key not in volatile} == {
        key: value for key, value in incoming.items() if key not in volatile
    }


def _json_document(value: dict[str, object]) -> dict[str, object]:
    """Normalize tuples and other JSON-compatible containers before comparison."""

    return json.loads(json.dumps(value))
