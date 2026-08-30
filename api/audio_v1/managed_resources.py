from __future__ import annotations

from collections import defaultdict

from api.models import ManagedAudioAdapter, PluginInstance, RuntimeProjection

from .representations import redact, timestamp

_PROCESSOR_NAMES = {
    "camilladsp": "CamillaDSP",
    "pcm-auto-decoder": "Adaptive PCM decoder",
    "decoder": "Adaptive PCM decoder",
}


def _adapter_action(adapter, state) -> dict[str, object]:
    available = bool(adapter.enabled)
    reason = None if available else "Enable this resource before restarting it."
    if state is not None and state.lifecycle in {"starting", "stopping"}:
        available = False
        reason = f"The adapter is currently {state.lifecycle}."
    return {
        "id": "restart",
        "label": "Restart",
        "available": available,
        "reason": reason,
        "method": "POST",
        "href": f"/api/audio/v1/adapters/{adapter.pk}/restart",
        "updateVersion": adapter.update_version,
    }


def _adapter_documents(user, projections) -> list[dict[str, object]]:
    by_adapter = defaultdict(list)
    for projection in projections:
        managed = projection.payload.get("managedAdapter")
        if isinstance(managed, dict) and managed.get("id"):
            by_adapter[str(managed["id"])].append(projection)
    documents = []
    adapters = ManagedAudioAdapter.objects.visible_to(user).select_related(
        "runtime_state"
    )
    for adapter in adapters:
        state = getattr(adapter, "runtime_state", None)
        correlations = by_adapter.get(str(adapter.pk), [])
        documents.append(
            {
                "schemaVersion": 1,
                "id": f"adapter:{adapter.pk}",
                "resourceType": "adapter",
                "name": adapter.name,
                "kind": adapter.kind,
                "version": None,
                "versionStatus": "unknown",
                "desired": {
                    "lifecycle": "running" if adapter.enabled else "stopped",
                    "enabled": adapter.enabled,
                    "updateVersion": adapter.update_version,
                },
                "observed": {
                    "lifecycle": state.lifecycle if state is not None else "unknown",
                    "health": state.health if state is not None else "unknown",
                    "mode": None,
                    "profile": None,
                    "lastError": state.last_error if state is not None else {},
                    "observedAt": timestamp(state.observed_at)
                    if state is not None
                    else None,
                },
                "freshness": {
                    "observedAt": timestamp(state.observed_at)
                    if state is not None
                    else None,
                    "runtimeGeneration": (
                        state.runtime_generation if state is not None else None
                    ),
                    "stale": state is None or state.observed_at is None,
                },
                "actions": [_adapter_action(adapter, state)],
                "correlations": [
                    {
                        "kind": "endpoint-candidate",
                        "subject": item.subject_key,
                        "worldGeneration": item.world_generation,
                        "worldSequence": item.world_sequence,
                        "evidence": redact(item.payload, admin=user.is_staff),
                    }
                    for item in correlations
                ],
            }
        )
    return documents


def _processor_documents(user, projections) -> list[dict[str, object]]:
    node_projections = defaultdict(list)
    health_projections = []
    for projection in projections:
        if projection.projection_type == "managed-resource":
            identity = projection.payload.get("identity")
            if isinstance(identity, dict):
                key = (
                    str(identity.get("processorKind")),
                    str(identity.get("instanceId")),
                )
                node_projections[key].append(projection)
        elif projection.projection_type in {"processor", "processor-health"}:
            health_projections.append(projection)
    documents = []
    represented = set()
    for health in health_projections:
        payload = health.payload
        kind = str(payload.get("kind") or payload.get("processorKind") or "processor")
        instance = str(
            payload.get("instanceId") or health.subject_key.rsplit(":", 1)[-1]
        )
        key = (kind, instance)
        represented.add(key)
        nodes = node_projections.get(key, [])
        observed_at = max(
            [health.observed_at, *(item.observed_at for item in nodes)],
        )
        display = _PROCESSOR_NAMES.get(kind, kind.replace("-", " ").title())
        documents.append(
            {
                "schemaVersion": 1,
                "id": f"processor:{kind}:{instance}",
                "resourceType": "processor",
                "name": f"{display} · {instance}",
                "kind": kind,
                "version": payload.get("version"),
                "versionStatus": "known" if payload.get("version") else "unknown",
                "desired": {
                    "lifecycle": "managed",
                    "enabled": True,
                    "updateVersion": None,
                },
                "observed": {
                    "lifecycle": "ready" if payload.get("ready") else "degraded",
                    "health": payload.get("health", "unknown"),
                    "mode": payload.get("mode") or payload.get("format"),
                    "profile": payload.get("profile") or payload.get("profileName"),
                    "lastError": payload.get("lastError", {}),
                    "observedAt": timestamp(observed_at),
                },
                "freshness": {
                    "observedAt": timestamp(observed_at),
                    "runtimeGeneration": health.world_generation,
                    "stale": False,
                },
                "actions": [
                    {
                        "id": "restart",
                        "label": "Restart",
                        "available": False,
                        "reason": "A safe supervisor restart intent is not available yet.",
                        "method": None,
                        "href": None,
                        "updateVersion": None,
                    }
                ],
                "correlations": [
                    {
                        "kind": "pipewire-node",
                        "subject": item.subject_key,
                        "worldGeneration": item.world_generation,
                        "worldSequence": item.world_sequence,
                        "evidence": redact(item.payload, admin=user.is_staff),
                    }
                    for item in sorted(nodes, key=lambda value: value.subject_key)
                ],
            }
        )
    for key, nodes in node_projections.items():
        if key in represented:
            continue
        kind, instance = key
        observed_at = max(item.observed_at for item in nodes)
        display = _PROCESSOR_NAMES.get(kind, kind.replace("-", " ").title())
        documents.append(
            {
                "schemaVersion": 1,
                "id": f"processor:{kind}:{instance}",
                "resourceType": "processor",
                "name": f"{display} · {instance}",
                "kind": kind,
                "version": None,
                "versionStatus": "unknown",
                "desired": {
                    "lifecycle": "managed",
                    "enabled": True,
                    "updateVersion": None,
                },
                "observed": {
                    "lifecycle": "unknown",
                    "health": "unknown",
                    "mode": None,
                    "profile": None,
                    "lastError": {},
                    "observedAt": timestamp(observed_at),
                },
                "freshness": {
                    "observedAt": timestamp(observed_at),
                    "runtimeGeneration": nodes[0].world_generation,
                    "stale": False,
                },
                "actions": [
                    {
                        "id": "restart",
                        "label": "Restart",
                        "available": False,
                        "reason": "Processor health has not been correlated to a safe supervisor action.",
                        "method": None,
                        "href": None,
                        "updateVersion": None,
                    }
                ],
                "correlations": [
                    {
                        "kind": "pipewire-node",
                        "subject": item.subject_key,
                        "worldGeneration": item.world_generation,
                        "worldSequence": item.world_sequence,
                        "evidence": redact(item.payload, admin=user.is_staff),
                    }
                    for item in sorted(nodes, key=lambda value: value.subject_key)
                ],
            }
        )
    return documents


def _plugin_instance_documents(user) -> list[dict[str, object]]:
    queryset = PluginInstance.objects.all()
    if not (user.is_staff or user.is_superuser):
        queryset = queryset.filter(owner=user)
    documents = []
    for instance in queryset:
        facts = (
            instance.runtime_facts if isinstance(instance.runtime_facts, dict) else {}
        )
        raw_actions = facts.get("actions", [])
        actions = []
        if isinstance(raw_actions, list):
            for raw in raw_actions:
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                    continue
                actions.append(
                    {
                        **raw,
                        "method": "POST",
                        "href": (
                            f"/api/plugins/{instance.plugin_id}/instances/"
                            f"{instance.instance_id}/actions/{raw['id']}"
                        ),
                        "updateVersion": instance.update_version,
                    }
                )
        documents.append(
            {
                "schemaVersion": 1,
                "id": f"plugin:{instance.plugin_id}:{instance.instance_id}",
                "resourceType": "plugin-managed-source",
                "name": instance.display_name,
                "kind": instance.plugin_id,
                "version": facts.get("librespotVersion"),
                "versionStatus": "known"
                if facts.get("librespotVersion")
                else "unknown",
                "desired": {
                    "lifecycle": (
                        "running" if instance.desired_state == "enabled" else "stopped"
                    ),
                    "enabled": instance.desired_state == "enabled",
                    "updateVersion": instance.update_version,
                },
                "observed": {
                    "lifecycle": facts.get("lifecycle", instance.observed_state),
                    "health": facts.get(
                        "health",
                        "failed" if instance.observed_state == "failed" else "unknown",
                    ),
                    "mode": facts.get("playbackState"),
                    "profile": facts.get("authenticationMode"),
                    "lastError": facts.get("lastError", {}),
                    "observedAt": facts.get("observedAt"),
                },
                "freshness": {
                    "observedAt": facts.get("observedAt"),
                    "runtimeGeneration": facts.get("worldGeneration"),
                    "stale": facts.get("observedAt") is None,
                },
                "actions": actions,
                "correlations": [
                    {
                        "kind": "endpoint-candidate",
                        "subject": facts.get("correlatedRuntimeKey"),
                        "worldGeneration": facts.get("worldGeneration"),
                        "worldSequence": facts.get("worldSequence"),
                        "evidence": {
                            "status": facts.get("pipewireCorrelation", "missing"),
                            "logicalEndpointId": facts.get("logicalEndpointId"),
                            "routeAvailable": facts.get("routeAvailable", False),
                        },
                    }
                ],
            }
        )
    return documents


def managed_resource_documents(user) -> list[dict[str, object]]:
    projections = list(
        RuntimeProjection.objects.filter(
            is_current=True,
            projection_type__in=(
                "endpoint-candidate",
                "managed-resource",
                "processor",
                "processor-health",
            ),
        )
    )
    documents = [
        *_adapter_documents(user, projections),
        *_processor_documents(user, projections),
        *_plugin_instance_documents(user),
    ]
    return sorted(
        documents, key=lambda item: (item["resourceType"], item["name"], item["id"])
    )
