from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from django.db import transaction

from api.models import (
    EndpointAudioLevel,
    LogicalEndpoint,
    ManagedAudioAdapterRuntimeState,
    MasterAudioLevel,
    RuntimeProjection,
)

from .endpoint_matching import EndpointMatchStatus, match_endpoint_candidates
from .endpoint_selectors import parse_endpoint_selector
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
        "audio-level",
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
            documents.update(_audio_level_documents(world))
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


def _audio_level_documents(
    world: OrchestratorWorldSnapshot,
) -> dict[tuple[str, str], dict[str, object]]:
    master = MasterAudioLevel.objects.filter(pk=1).first()
    master_level = master.level if master is not None else 1.0
    master_muted = master.muted if master is not None else False
    values = {
        item.endpoint_id: item
        for item in EndpointAudioLevel.objects.select_related("endpoint").all()
    }
    if master is None and not values:
        return {}
    documents: dict[tuple[str, str], dict[str, object]] = {}
    active_outputs = []
    master_degraded = []
    master_applying = False
    for endpoint in LogicalEndpoint.objects.all():
        value = values.get(endpoint.pk)
        endpoint_level = value.level if value is not None else 1.0
        endpoint_muted = value.muted if value is not None else False
        output = endpoint.direction == "output"
        effective_level = endpoint_level * master_level if output else endpoint_level
        effective_muted = endpoint_muted or (master_muted if output else False)
        validation = parse_endpoint_selector(endpoint.explicit_binding or endpoint.selector)
        candidate = None
        availability = "invalid"
        if validation.valid:
            matches = match_endpoint_candidates(
                validation.selector,
                [
                    item
                    for item in world.endpoints.candidates
                    if item.direction.value == endpoint.direction
                ],
            )
            if matches.status is EndpointMatchStatus.MATCHED:
                availability = "available"
                candidate = matches.selected
            elif matches.status is EndpointMatchStatus.AMBIGUOUS:
                availability = "ambiguous"
            else:
                availability = "unavailable"
        observed_level = candidate.volume if candidate is not None else None
        observed_muted = candidate.mute if candidate is not None else None
        volume_writable = bool(candidate is not None and candidate.volume_writable)
        mute_writable = bool(candidate is not None and candidate.mute_writable)
        level_differs = bool(
            candidate is not None
            and observed_level is not None
            and abs(float(observed_level) - float(effective_level)) > 0.0001
        )
        mute_differs = bool(
            candidate is not None
            and observed_muted is not None
            and observed_muted is not effective_muted
        )
        applying = (level_differs and volume_writable) or (mute_differs and mute_writable)
        degraded = []
        if availability != "available":
            degraded.append(
                {
                    "code": f"endpoint-{availability}",
                    "detail": "The saved audio preference will apply when one unique runtime device is available.",
                }
            )
        if level_differs and not volume_writable:
            degraded.append(
                {
                    "code": "endpoint-volume-read-only",
                    "detail": "Observed volume differs from desired state and is read-only.",
                }
            )
        if mute_differs and not mute_writable:
            degraded.append(
                {
                    "code": "endpoint-mute-read-only",
                    "detail": "Observed mute differs from desired state and is read-only.",
                }
            )
        payload = {
            "schemaVersion": 1,
            "scope": "device-level" if output else "input-level",
            "endpointId": str(endpoint.pk),
            "direction": endpoint.direction,
            "availability": availability,
            "desired": {"level": endpoint_level, "muted": endpoint_muted},
            "master": (
                {
                    "level": master_level,
                    "muted": master_muted,
                    "updateVersion": master.update_version if master is not None else 1,
                }
                if output
                else None
            ),
            "effective": {"level": effective_level, "muted": effective_muted},
            "observed": {
                "level": observed_level,
                "muted": observed_muted,
                "known": candidate is not None
                and observed_level is not None
                and observed_muted is not None,
            },
            "capabilities": {
                "volume": {
                    "readable": observed_level is not None,
                    "writable": volume_writable,
                },
                "mute": {
                    "readable": observed_muted is not None,
                    "writable": mute_writable,
                },
            },
            "active": bool(candidate is not None and candidate.is_linked),
            "applying": applying,
            "degraded": degraded,
            "runtimeVersion": world.version,
            "updateVersion": value.update_version if value is not None else 1,
        }
        documents[("audio-level", f"endpoint:{endpoint.pk}")] = _json_document(payload)
        if output and payload["active"]:
            observed = payload["observed"]
            active_outputs.append(
                {
                    "endpointId": str(endpoint.pk),
                    "level": observed["level"],
                    "muted": observed["muted"],
                    "known": observed["known"],
                }
            )
            master_applying = master_applying or applying
            master_degraded.extend({**item, "endpointId": str(endpoint.pk)} for item in degraded)
    documents[("audio-level", "master")] = _json_document(
        {
            "schemaVersion": 1,
            "scope": "master-output",
            "desired": {"level": master_level, "muted": master_muted},
            "effective": {"level": master_level, "muted": master_muted},
            "observed": {
                "outputs": active_outputs,
                "known": bool(active_outputs) and all(item["known"] for item in active_outputs),
            },
            "applying": master_applying,
            "degraded": master_degraded,
            "runtimeVersion": world.version,
            "updateVersion": master.update_version if master is not None else 1,
        }
    )
    return documents
