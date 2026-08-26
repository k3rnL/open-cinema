from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.utils import timezone

from api.models import (
    GraphRevision,
    GraphRevisionState,
    LogicalEndpoint,
    ManualOverride,
)

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
        processor_version=0,
        override_version=len(overrides),
        resource_policy_version=resource_policy.version,
    )
    return ResolverInputs(
        graph=ResolverGraphRevisionInput.from_model(activation.revision),
        subgraph_revisions=subgraphs,
        activation=ResolverActivationInput.from_model(activation),
        logical_endpoints=endpoints,
        runtime_inventory=world.endpoints,
        signal_facts=signal_facts,
        processors=(),
        overrides=overrides,
        resource_policy=resource_policy,
        world_version=world_version,
        evaluated_at=evaluated_at.isoformat(),
    )
