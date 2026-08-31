from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from django.db import DatabaseError

from api.models import LogicalEndpoint, PluginInstance

from .host_services import CorePluginHostServices
from .managed_source_identity import managed_source_endpoint_id
from .storage import PluginInstanceRepository
from .v2_contracts import (
    ManagedAudioSourceCapability,
    ManagedResourceContext,
    PluginDesiredState,
    PluginRuntimeResult,
    RuntimeStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ManagedSourceReconcileResult:
    started: tuple[str, ...] = ()
    stopped: tuple[str, ...] = ()
    restarted: tuple[str, ...] = ()
    ready: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


_RESOLUTION_FACT_KEYS = (
    "generation",
    "health",
    "routeAvailable",
    "pipewireCorrelation",
    "activeSignal",
    "activityHeld",
    "playbackState",
)


def _resolution_facts(facts) -> tuple[object, ...]:
    return tuple(facts.get(key) for key in _RESOLUTION_FACT_KEYS)


def _context(instance: PluginInstance) -> ManagedResourceContext:
    return ManagedResourceContext(
        instance.plugin_id,
        instance.capability_id,
        instance.instance_id,
        instance.configuration,
        instance.configuration_version,
        concurrency_token=str(instance.update_version),
        host_services=CorePluginHostServices(instance.plugin_id, instance.instance_id),
    )


def _selector(plugin_id: str, instance_id: str) -> dict[str, object]:
    return {
        "version": 1,
        "match": "all",
        "predicates": [
            {
                "path": "direction",
                "operator": "exact",
                "value": "input",
            },
            {
                "path": "node.properties.open-cinema.plugin.id",
                "operator": "exact",
                "value": plugin_id,
            },
            {
                "path": "node.properties.open-cinema.instance.id",
                "operator": "exact",
                "value": instance_id,
            },
        ],
    }


def _synchronize_endpoint(instance: PluginInstance) -> str:
    endpoint_id = managed_source_endpoint_id(
        instance.plugin_id,
        instance.capability_id,
        instance.instance_id,
    )
    if instance.owner_id is None:
        return endpoint_id
    endpoint_name = instance.display_name
    collision = LogicalEndpoint.objects.filter(
        owner_id=instance.owner_id,
        name=endpoint_name,
    ).exclude(pk=endpoint_id)
    if collision.exists():
        suffix = f" · {instance.plugin_id.rsplit('.', 1)[-1]} · {endpoint_id[:8]}"
        endpoint_name = f"{endpoint_name[: 255 - len(suffix)]}{suffix}"
    defaults = {
        "name": endpoint_name,
        "owner_id": instance.owner_id,
        "direction": "input",
        "selector": _selector(instance.plugin_id, instance.instance_id),
        "tags": ["managed-source", f"plugin:{instance.plugin_id}"],
        "groups": ["plugin-managed-inputs"],
        "policy_metadata": {
            "managedSource": True,
            "pluginId": instance.plugin_id,
            "capabilityId": instance.capability_id,
            "instanceId": instance.instance_id,
        },
        "explicit_binding": None,
        "last_known_summary": {
            "pluginId": instance.plugin_id,
            "instanceId": instance.instance_id,
            "desiredState": instance.desired_state,
        },
    }
    endpoint, created = LogicalEndpoint.objects.get_or_create(id=endpoint_id, defaults=defaults)
    if not created:
        changed = False
        for field in (
            "name",
            "owner_id",
            "direction",
            "selector",
            "tags",
            "groups",
            "policy_metadata",
            "explicit_binding",
        ):
            value = defaults[field]
            if getattr(endpoint, field) != value:
                setattr(endpoint, field, value)
                changed = True
        if changed:
            endpoint.update_version += 1
            endpoint.save()
    return endpoint_id


def _correlation(world, *, plugin_id: str, instance_id: str, generation: object):
    matches = []
    mismatched = []
    for candidate in world.endpoints.candidates:
        properties = candidate.node_properties
        if (
            properties.get("open-cinema.plugin.id") != plugin_id
            or properties.get("open-cinema.instance.id") != instance_id
        ):
            continue
        if properties.get("open-cinema.generation") != generation:
            mismatched.append(candidate)
            continue
        if candidate.direction.value != "input":
            mismatched.append(candidate)
            continue
        matches.append(candidate)
    if len(matches) == 1:
        candidate = matches[0]
        return "ready", candidate, tuple(mismatched)
    if len(matches) > 1:
        return "ambiguous", None, tuple((*matches, *mismatched))
    if mismatched:
        return "mismatched", None, tuple(mismatched)
    return "missing", None, ()


def _provider_activity_is_recent(
    facts: Mapping[str, object],
    configuration: Mapping[str, object],
) -> bool:
    """Bound event-only activity while PipeWire is not yet producing audio."""

    if facts.get("activeSignal") is not True:
        return False
    raw_hold_ms = configuration.get("activityHoldMs", 1500)
    if isinstance(raw_hold_ms, bool):
        hold_ms = 1500
    else:
        try:
            hold_ms = max(0, min(int(raw_hold_ms), 30_000))
        except (TypeError, ValueError):
            hold_ms = 1500
    events = facts.get("events")
    if not isinstance(events, Mapping):
        return False
    event = events.get("lastPlaybackEvent") or events.get("lastEvent")
    if not isinstance(event, Mapping):
        return False
    observed_at = event.get("observedAtUnixMs")
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
        return False
    age_ms = int(datetime.now(UTC).timestamp() * 1000) - int(observed_at)
    return -5_000 <= age_ms <= hold_ms


def _enrich_result(
    result: PluginRuntimeResult,
    world,
    instance: PluginInstance,
) -> PluginRuntimeResult:
    facts = result.facts.to_dict()
    endpoint_id = _synchronize_endpoint(instance)
    generation = facts.get("generation")
    correlation, candidate, conflicts = _correlation(
        world,
        plugin_id=instance.plugin_id,
        instance_id=instance.instance_id,
        generation=generation,
    )
    process_ready = result.status in {RuntimeStatus.READY, RuntimeStatus.DEGRADED}
    pipewire_active = bool(candidate is not None and candidate.has_active_signal)
    provider_active = facts.get("activeSignal") is True
    provider_activity_recent = _provider_activity_is_recent(facts, instance.configuration)
    active = pipewire_active or (provider_active and provider_activity_recent)
    playback_state = facts.get("playbackState")
    if pipewire_active:
        playback_state = "playing"
    elif provider_active and not provider_activity_recent and playback_state == "playing":
        playback_state = "idle"
    facts.update(
        {
            "logicalEndpointId": endpoint_id,
            "pipewireCorrelation": correlation,
            "routeAvailable": process_ready and correlation == "ready",
            "correlatedRuntimeKey": candidate.runtime_key if candidate is not None else None,
            "correlationConflicts": [item.runtime_key for item in conflicts],
            "pipewireActiveSignal": pipewire_active,
            "activeSignal": active,
            "activityHeld": bool(
                facts.get("activityHeld") is True
                or (provider_active and provider_activity_recent and not pipewire_active)
            ),
            "playbackState": playback_state,
            "endpointControls": {
                "volume": bool(candidate is not None and candidate.volume_writable),
                "mute": bool(candidate is not None and candidate.mute_writable),
            },
            "worldGeneration": world.runtime.generation,
            "worldSequence": world.runtime.sequence,
        }
    )
    if process_ready and correlation != "ready":
        status = RuntimeStatus.DEGRADED
    else:
        status = result.status
    details = result.details.to_dict()
    details["correlation"] = {
        "status": correlation,
        "expectedGeneration": generation,
        "matches": 1 if candidate is not None else 0,
        "conflicts": len(conflicts),
    }
    return PluginRuntimeResult(
        status,
        facts=facts,
        details=details,
        retry_after_ms=result.retry_after_ms,
        concurrency_token=result.concurrency_token,
    )


def _observed_state(result: PluginRuntimeResult, *, desired_enabled: bool) -> str:
    if not desired_enabled:
        return "stopped"
    return {
        RuntimeStatus.READY: "started",
        RuntimeStatus.DEGRADED: "started",
        RuntimeStatus.FAILED: "failed",
        RuntimeStatus.UNAVAILABLE: "stopped",
    }[result.status]


class ManagedPluginSourceReconciler:
    """Reconcile every external managed source in the single controller."""

    def __init__(self, registry, *, minimum_interval_seconds: float = 0.5, clock=monotonic) -> None:
        self.registry = registry
        self.minimum_interval_seconds = minimum_interval_seconds
        self.clock = clock
        self._last_reconciled_at: float | None = None
        self._applied_versions: dict[tuple[str, str, str], int] = {}
        self._contexts: dict[tuple[str, str, str], ManagedResourceContext] = {}

    def _capabilities(self):
        for record in self.registry.records:
            for capability_record in record.capabilities:
                contribution = capability_record.contribution
                if isinstance(contribution, ManagedAudioSourceCapability):
                    yield record, capability_record, contribution

    def reconcile(self, world, *, force: bool = False) -> ManagedSourceReconcileResult:
        from .persistence_sync import refresh_plugin_desired_state

        now = self.clock()
        if (
            not force
            and self._last_reconciled_at is not None
            and now - self._last_reconciled_at < self.minimum_interval_seconds
        ):
            return ManagedSourceReconcileResult()
        self._last_reconciled_at = now
        refresh_plugin_desired_state(self.registry)
        stop_disabled = getattr(self.registry, "stop_disabled", None)
        start_enabled = getattr(self.registry, "start_enabled", None)
        if callable(stop_disabled):
            stop_disabled()
        if callable(start_enabled):
            start_enabled()
        started: list[str] = []
        stopped: list[str] = []
        restarted: list[str] = []
        ready: list[str] = []
        failed: list[str] = []
        changed: list[str] = []
        seen: set[tuple[str, str, str]] = set()

        for record, _capability_record, capability in self._capabilities():
            instances = PluginInstance.objects.filter(
                plugin_id=record.manifest.plugin_id,
                capability_id=capability.capability_id,
            )
            plugin_enabled = record.desired_state is PluginDesiredState.ENABLED
            for instance in instances:
                key = (instance.plugin_id, instance.capability_id, instance.instance_id)
                seen.add(key)
                context = _context(instance)
                self._contexts[key] = context
                desired_enabled = plugin_enabled and instance.desired_state == "enabled"
                try:
                    before = capability.provider.observe(context)
                    lifecycle = before.result.facts.get("lifecycle")
                    if desired_enabled:
                        applied = self._applied_versions.get(key)
                        if lifecycle != "running":
                            prepared = capability.provider.prepare(context)
                            if prepared.status is not RuntimeStatus.READY:
                                result = prepared
                            else:
                                result = capability.provider.activate(context)
                                self._applied_versions[key] = instance.update_version
                                started.append(instance.instance_id)
                        elif applied is not None and applied != instance.update_version:
                            result = capability.provider.reconfigure(context)
                            self._applied_versions[key] = instance.update_version
                            restarted.append(instance.instance_id)
                        else:
                            result = before.result
                            self._applied_versions.setdefault(key, instance.update_version)
                    else:
                        if lifecycle == "running":
                            result = capability.provider.deactivate(context)
                            stopped.append(instance.instance_id)
                        else:
                            result = before.result
                        self._applied_versions.pop(key, None)

                    result = _enrich_result(result, world, instance)
                    observation = capability.provider.observe(context)
                    facts = result.facts.to_dict()
                    facts["actions"] = [item.to_document() for item in observation.actions]
                    facts["observedAt"] = datetime.now(UTC).isoformat()
                    facts["freshForMs"] = observation.fresh_for_ms
                    if _resolution_facts(instance.runtime_facts) != _resolution_facts(facts):
                        changed.append(instance.instance_id)
                    PluginInstanceRepository.record_observation(
                        instance.plugin_id,
                        instance.capability_id,
                        instance.instance_id,
                        observed_state=_observed_state(
                            result,
                            desired_enabled=desired_enabled,
                        ),
                        runtime_facts=facts,
                    )
                    if result.status in {RuntimeStatus.READY, RuntimeStatus.DEGRADED}:
                        ready.append(instance.instance_id)
                    else:
                        failed.append(instance.instance_id)
                except Exception as error:
                    logger.exception(
                        "Managed source reconciliation failed for %s/%s",
                        instance.plugin_id,
                        instance.instance_id,
                    )
                    failed.append(instance.instance_id)
                    try:
                        PluginInstanceRepository.record_observation(
                            instance.plugin_id,
                            instance.capability_id,
                            instance.instance_id,
                            observed_state="failed",
                            runtime_facts={
                                **dict(instance.runtime_facts),
                                "routeAvailable": False,
                                "health": "failed",
                                "lastError": {
                                    "code": "managed-source-reconcile-failed",
                                    "message": str(error),
                                    "exception": type(error).__name__,
                                },
                                "observedAt": datetime.now(UTC).isoformat(),
                            },
                        )
                    except DatabaseError:
                        logger.exception("Could not persist managed source failure")

        for key in set(self._contexts) - seen:
            context = self._contexts.pop(key)
            for _record, _capability_record, capability in self._capabilities():
                if capability.capability_id == key[1]:
                    try:
                        capability.provider.cleanup(context)
                    except Exception:
                        logger.exception(
                            "Managed source cleanup failed for removed instance %s", key
                        )
                    break
            self._applied_versions.pop(key, None)

        return ManagedSourceReconcileResult(
            tuple(started),
            tuple(stopped),
            tuple(restarted),
            tuple(ready),
            tuple(failed),
            tuple(changed),
        )

    def shutdown(self) -> None:
        capabilities = {item.capability_id: item for _, _, item in self._capabilities()}
        for key, context in tuple(self._contexts.items()):
            capability = capabilities.get(key[1])
            if capability is None:
                continue
            try:
                capability.provider.deactivate(context)
            except Exception:
                logger.exception("Managed source shutdown failed for %s", key)
        self._contexts.clear()
        self._applied_versions.clear()
