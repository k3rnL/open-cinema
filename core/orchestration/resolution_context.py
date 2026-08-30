from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

from django.conf import settings
from django.utils import timezone

from api.models import (
    GraphRevision,
    GraphRevisionState,
    LogicalEndpoint,
    ManualOverride,
    PluginInstance,
)

from .endpoint_inventory import EndpointInventorySnapshot

from .resolver_inputs import (
    ResolverActivationInput,
    ResolverGraphRevisionInput,
    ResolverInputs,
    ResolverLogicalEndpointInput,
    ResolverOverrideInput,
    ResolverResourceInput,
    ResolverResourcePolicyInput,
    ResolverSignalFactsInput,
    ResolverWorldVersion,
)
from .runtime_world import OrchestratorWorldSnapshot


def deployed_processor_resource_policy() -> ResolverResourcePolicyInput:
    """Expose bounded deployment capacity without binding graphs to Pi instance IDs."""

    from .camilladsp_resources import CamillaDSPDeploymentPolicy

    capacity = settings.AUDIO_PROCESSOR_CAPACITY
    camilladsp_count = int(capacity["camilladsp"])
    decoder_count = int(capacity["decoder"])
    if decoder_count < 0:
        raise ValueError("decoder processor capacity must be non-negative")
    camilladsp = CamillaDSPDeploymentPolicy(instance_count=camilladsp_count)
    decoder = tuple(
        ResolverResourceInput(
            resource_id=f"decoder:{index}",
            kind="decoder",
            capacity=1,
            allocated=0,
            health="ready",
        )
        for index in range(decoder_count)
    )
    return ResolverResourcePolicyInput(
        version=1,
        resources=(*camilladsp.resources(), *decoder),
        policy={"conflict": "priority"},
    )


def _managed_source_activity(endpoints, inventory, instances):
    """Overlay authenticated provider activity onto its exactly correlated stream."""

    by_identity = {
        (item.plugin_id, item.capability_id, item.instance_id): item for item in instances
    }
    overrides: dict[str, bool] = {}
    semantic_state: list[dict[str, object]] = []
    for endpoint in endpoints:
        metadata = endpoint.policy_metadata
        identity = (
            metadata.get("pluginId"),
            metadata.get("capabilityId"),
            metadata.get("instanceId"),
        )
        if metadata.get("managedSource") is not True or not all(
            isinstance(value, str) for value in identity
        ):
            continue
        instance = by_identity.get(identity)
        if instance is None:
            continue
        facts = instance.runtime_facts
        active = bool(
            facts.get("routeAvailable") is True
            and facts.get("pipewireCorrelation") == "ready"
            and facts.get("activeSignal") is True
        )
        runtime_key = facts.get("correlatedRuntimeKey")
        if isinstance(runtime_key, str):
            overrides[runtime_key] = active
        events = facts.get("events")
        semantic_state.append(
            {
                "endpointId": endpoint.endpoint_id,
                "instanceVersion": instance.update_version,
                "generation": facts.get("generation"),
                "correlation": facts.get("pipewireCorrelation"),
                "routeAvailable": facts.get("routeAvailable"),
                "activeSignal": active,
                "playbackState": facts.get("playbackState"),
                "eventSequence": events.get("lastSequence") if isinstance(events, dict) else None,
            }
        )
    if not semantic_state:
        return inventory, 0
    encoded = json.dumps(
        sorted(semantic_state, key=lambda item: str(item["endpointId"])),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    version = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")
    candidates = tuple(
        (
            replace(candidate, has_active_signal=overrides[candidate.runtime_key])
            if candidate.runtime_key in overrides
            else candidate
        )
        for candidate in inventory.candidates
    )
    return replace(inventory, candidates=candidates), version


def build_resolver_inputs(
    activation,
    world: OrchestratorWorldSnapshot,
    *,
    signal_facts_provider: Callable[[], ResolverSignalFactsInput],
) -> ResolverInputs:
    """Build the shared, immutable resolver boundary for shadow and live modes."""

    if not isinstance(world, OrchestratorWorldSnapshot):
        raise TypeError("world must be an OrchestratorWorldSnapshot")
    if not callable(signal_facts_provider):
        raise TypeError("signal_facts_provider must be callable")

    evaluated_at = timezone.now()
    endpoints = tuple(
        ResolverLogicalEndpointInput.from_model(endpoint)
        for endpoint in LogicalEndpoint.objects.filter(owner=activation.definition.owner)
    )
    runtime_inventory, managed_source_version = _managed_source_activity(
        endpoints,
        world.endpoints,
        PluginInstance.objects.filter(owner=activation.definition.owner),
    )
    overrides = tuple(
        ResolverOverrideInput.from_model(override, at=evaluated_at)
        for override in ManualOverride.objects.active_at(evaluated_at)
    )
    subgraphs = tuple(
        ResolverGraphRevisionInput.from_model(revision)
        for revision in GraphRevision.objects.filter(
            definition__owner=activation.definition.owner,
            definition__kind="subgraph",
            state=GraphRevisionState.PUBLISHED,
        ).select_related("definition")
    )
    signal_facts = signal_facts_provider()
    if not isinstance(signal_facts, ResolverSignalFactsInput):
        raise TypeError("signal_facts_provider must return ResolverSignalFactsInput")
    resource_policy = deployed_processor_resource_policy()
    world_version = ResolverWorldVersion(
        runtime_generation=world.runtime.generation,
        runtime_sequence=world.runtime.sequence,
        endpoint_version=sum(endpoint.update_version for endpoint in endpoints),
        signal_version=signal_facts.version,
        processor_version=managed_source_version,
        override_version=len(overrides),
        resource_policy_version=resource_policy.version,
    )
    return ResolverInputs(
        graph=ResolverGraphRevisionInput.from_model(activation.revision),
        subgraph_revisions=subgraphs,
        activation=ResolverActivationInput.from_model(activation),
        logical_endpoints=endpoints,
        runtime_inventory=runtime_inventory,
        signal_facts=signal_facts,
        processors=(),
        overrides=overrides,
        resource_policy=resource_policy,
        world_version=world_version,
        evaluated_at=evaluated_at.isoformat(),
    )
