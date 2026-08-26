from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from wyreplumber.runtime import FrozenDict, freeze_json

from .endpoint_inventory import (
    EndpointDirection,
    EndpointFormatSummary,
    EndpointInventorySnapshot,
    EndpointLatencySummary,
    EndpointPortSummary,
    EndpointProfileSummary,
    EndpointRouteSummary,
    ObservedAudioValue,
    RuntimeEndpointCandidate,
    RuntimeEndpointReference,
    RuntimeProfileReference,
    RuntimeRouteReference,
)
from .node_catalogue import NodeTypeRegistry
from .resolved_plan import (
    RESOLVED_PLAN_SCHEMA_VERSION,
    ResolvedPlanOutput,
    resolve_plan,
)
from .resolver_inputs import (
    ResolverActivationInput,
    ResolverGraphRevisionInput,
    ResolverInputs,
    ResolverLogicalEndpointInput,
    ResolverOverrideInput,
    ResolverProcessorHealthInput,
    ResolverResourceInput,
    ResolverResourcePolicyInput,
    ResolverSignalFactsInput,
    ResolverWorldVersion,
)

RESOLVER_REPLAY_FORMAT = "open-cinema.resolver-replay/v1"
RESOLVER_REPLAY_SCHEMA_VERSION = 1


class ResolverReplayError(ValueError):
    pass


class ResolverReplayMismatch(ResolverReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ResolverReplayResult:
    inputs: ResolverInputs
    plan: ResolvedPlanOutput
    expected_digest: str | None
    matches_expected: bool | None


def _json_value(value: object) -> object:
    return FrozenDict({"value": value}).to_dict()["value"]


def _revision_document(revision: ResolverGraphRevisionInput) -> dict[str, object]:
    return {
        "definitionId": revision.definition_id,
        "revisionId": revision.revision_id,
        "revisionNumber": revision.revision_number,
        "schemaVersion": revision.schema_version,
        "contentDigest": revision.content_digest,
        "document": revision.document.to_dict(),
    }


def _candidate_document(candidate: RuntimeEndpointCandidate) -> dict[str, object]:
    return {
        "runtime": {
            "generation": candidate.runtime.generation,
            "nodeId": candidate.runtime.node_id,
            "deviceId": candidate.runtime.device_id,
        },
        "direction": candidate.direction.value,
        "name": candidate.name,
        "description": candidate.description,
        "mediaClass": candidate.media_class,
        "nodeState": candidate.node_state,
        "nodeError": candidate.node_error,
        "nodeProperties": candidate.node_properties.to_dict(),
        "deviceName": candidate.device_name,
        "deviceDescription": candidate.device_description,
        "deviceMediaClass": candidate.device_media_class,
        "deviceProperties": candidate.device_properties.to_dict(),
        "ports": [
            {
                "name": port.name,
                "direction": port.direction,
                "channel": port.channel,
                "properties": port.properties.to_dict(),
            }
            for port in candidate.ports
        ],
        "profiles": [
            {
                "runtime": {
                    "generation": profile.runtime.generation,
                    "deviceId": profile.runtime.device_id,
                    "profileIndex": profile.runtime.profile_index,
                },
                "name": profile.name,
                "description": profile.description,
                "priority": profile.priority,
                "availability": profile.availability,
                "active": profile.active,
                "classes": list(profile.classes),
                "properties": profile.properties.to_dict(),
            }
            for profile in candidate.profiles
        ],
        "routes": [
            {
                "runtime": {
                    "generation": route.runtime.generation,
                    "deviceId": route.runtime.device_id,
                    "routeIndex": route.runtime.route_index,
                },
                "name": route.name,
                "description": route.description,
                "direction": route.direction,
                "priority": route.priority,
                "availability": route.availability,
                "active": route.active,
                "profileNames": list(route.profile_names),
                "volume": route.volume,
                "mute": route.mute,
                "properties": route.properties.to_dict(),
            }
            for route in candidate.routes
        ],
        "formats": [format_value.to_document() for format_value in candidate.formats],
        "volume": candidate.volume,
        "mute": candidate.mute,
        "latency": candidate.latency.to_document(),
        "isDefault": candidate.is_default,
        "isLinked": candidate.is_linked,
        "hasActiveSignal": candidate.has_active_signal,
    }


def resolver_inputs_to_document(inputs: ResolverInputs) -> dict[str, object]:
    if not isinstance(inputs, ResolverInputs):
        raise TypeError("inputs must be ResolverInputs")
    return {
        "desired": {
            "graphRevision": _revision_document(inputs.graph),
            "subgraphRevisions": [
                _revision_document(revision) for revision in inputs.subgraph_revisions
            ],
            "activation": {
                "activationId": inputs.activation.activation_id,
                "definitionId": inputs.activation.definition_id,
                "revisionId": inputs.activation.revision_id,
                "desiredStateVersion": inputs.activation.desired_state_version,
                "parameterBindings": inputs.activation.parameter_bindings.to_dict(),
                "sceneBindings": inputs.activation.scene_bindings.to_dict(),
            },
            "logicalEndpoints": [
                {
                    "endpointId": endpoint.endpoint_id,
                    "name": endpoint.name,
                    "direction": endpoint.direction,
                    "selector": endpoint.selector.to_dict(),
                    "tags": list(endpoint.tags),
                    "groups": list(endpoint.groups),
                    "policyMetadata": endpoint.policy_metadata.to_dict(),
                    "explicitBinding": (
                        endpoint.explicit_binding.to_dict()
                        if endpoint.explicit_binding is not None
                        else None
                    ),
                    "updateVersion": endpoint.update_version,
                }
                for endpoint in inputs.logical_endpoints
            ],
        },
        "world": {
            "version": {
                "runtimeGeneration": inputs.world_version.runtime_generation,
                "runtimeSequence": inputs.world_version.runtime_sequence,
                "endpointVersion": inputs.world_version.endpoint_version,
                "signalVersion": inputs.world_version.signal_version,
                "processorVersion": inputs.world_version.processor_version,
                "overrideVersion": inputs.world_version.override_version,
                "resourcePolicyVersion": inputs.world_version.resource_policy_version,
                "token": inputs.world_version.token,
            },
            "evaluatedAt": inputs.evaluated_at,
            "endpointInventory": {
                "generation": inputs.runtime_inventory.generation,
                "sequence": inputs.runtime_inventory.sequence,
                "capturedAt": inputs.runtime_inventory.captured_at,
                "candidates": [
                    _candidate_document(candidate)
                    for candidate in inputs.runtime_inventory.candidates
                ],
            },
            "signalFacts": {
                "version": inputs.signal_facts.version,
                "facts": inputs.signal_facts.facts.to_dict(),
            },
            "processors": [
                {
                    "processorId": processor.processor_id,
                    "health": processor.health,
                    "ready": processor.ready,
                    "facts": processor.facts.to_dict(),
                }
                for processor in inputs.processors
            ],
            "overrides": [
                {
                    "overrideId": override.override_id,
                    "scopeType": override.scope_type,
                    "scopeId": override.scope_id,
                    "value": _json_value(override.value),
                    "priority": override.priority,
                    "startsAt": override.starts_at,
                    "expiresAt": override.expires_at,
                    "cancelledAt": override.cancelled_at,
                    "active": override.active,
                    "reason": override.reason,
                }
                for override in inputs.overrides
            ],
        },
        "policies": {
            "resourcePolicy": {
                "version": inputs.resource_policy.version,
                "resources": [
                    {
                        "resourceId": resource.resource_id,
                        "kind": resource.kind,
                        "capacity": resource.capacity,
                        "allocated": resource.allocated,
                        "health": resource.health,
                        "attributes": resource.attributes.to_dict(),
                    }
                    for resource in inputs.resource_policy.resources
                ],
                "policy": inputs.resource_policy.policy.to_dict(),
            }
        },
    }


def _object(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResolverReplayError(f"{path} must be an object")
    return value


def _revision_from_document(value: object, path: str) -> ResolverGraphRevisionInput:
    item = _object(value, path)
    return ResolverGraphRevisionInput(
        definition_id=item["definitionId"],
        revision_id=item["revisionId"],
        revision_number=item["revisionNumber"],
        schema_version=item["schemaVersion"],
        content_digest=item["contentDigest"],
        document=_object(item["document"], f"{path}.document"),
    )


def _observed_audio_value(value: object, path: str) -> ObservedAudioValue:
    item = _object(value, path)
    return ObservedAudioValue(
        value=freeze_json(item.get("value")),
        known=item["known"],
        choices=tuple(freeze_json(choice) for choice in item.get("choices", ())),
    )


def _format_from_document(value: object, path: str) -> EndpointFormatSummary:
    item = _object(value, path)
    return EndpointFormatSummary(
        content=item["content"],
        media_type=_observed_audio_value(item["mediaType"], f"{path}.mediaType"),
        media_subtype=_observed_audio_value(item["mediaSubtype"], f"{path}.mediaSubtype"),
        sample_format=_observed_audio_value(item["sampleFormat"], f"{path}.sampleFormat"),
        rate=_observed_audio_value(item["rate"], f"{path}.rate"),
        channels=_observed_audio_value(item["channels"], f"{path}.channels"),
        positions=_observed_audio_value(item["positions"], f"{path}.positions"),
        codec=_observed_audio_value(item["codec"], f"{path}.codec"),
    )


def _candidate_from_document(value: object, path: str) -> RuntimeEndpointCandidate:
    item = _object(value, path)
    runtime = _object(item["runtime"], f"{path}.runtime")
    profiles = []
    for index, raw_profile in enumerate(item.get("profiles", ())):
        profile = _object(raw_profile, f"{path}.profiles[{index}]")
        reference = _object(profile["runtime"], f"{path}.profiles[{index}].runtime")
        profiles.append(
            EndpointProfileSummary(
                runtime=RuntimeProfileReference(
                    generation=reference["generation"],
                    device_id=reference["deviceId"],
                    profile_index=reference["profileIndex"],
                ),
                name=profile["name"],
                description=profile.get("description"),
                priority=profile["priority"],
                availability=profile["availability"],
                active=profile["active"],
                classes=tuple(profile.get("classes", ())),
                properties=FrozenDict(_object(profile.get("properties", {}), "properties")),
            )
        )
    routes = []
    for index, raw_route in enumerate(item.get("routes", ())):
        route = _object(raw_route, f"{path}.routes[{index}]")
        reference = _object(route["runtime"], f"{path}.routes[{index}].runtime")
        routes.append(
            EndpointRouteSummary(
                runtime=RuntimeRouteReference(
                    generation=reference["generation"],
                    device_id=reference["deviceId"],
                    route_index=reference["routeIndex"],
                ),
                name=route["name"],
                description=route.get("description"),
                direction=route["direction"],
                priority=route["priority"],
                availability=route["availability"],
                active=route["active"],
                profile_names=tuple(route.get("profileNames", ())),
                volume=route.get("volume"),
                mute=route.get("mute"),
                properties=FrozenDict(_object(route.get("properties", {}), "properties")),
            )
        )
    latency = _object(item["latency"], f"{path}.latency")
    return RuntimeEndpointCandidate(
        runtime=RuntimeEndpointReference(
            generation=runtime["generation"],
            node_id=runtime["nodeId"],
            device_id=runtime.get("deviceId"),
        ),
        direction=EndpointDirection(item["direction"]),
        name=item.get("name"),
        description=item.get("description"),
        media_class=item["mediaClass"],
        node_state=item["nodeState"],
        node_error=item.get("nodeError"),
        node_properties=FrozenDict(_object(item.get("nodeProperties", {}), "nodeProperties")),
        device_name=item.get("deviceName"),
        device_description=item.get("deviceDescription"),
        device_media_class=item.get("deviceMediaClass"),
        device_properties=FrozenDict(_object(item.get("deviceProperties", {}), "deviceProperties")),
        ports=tuple(
            EndpointPortSummary(
                name=port.get("name"),
                direction=port["direction"],
                channel=port.get("channel"),
                properties=FrozenDict(_object(port.get("properties", {}), "properties")),
            )
            for port in (
                _object(raw_port, f"{path}.ports[{index}]")
                for index, raw_port in enumerate(item.get("ports", ()))
            )
        ),
        profiles=tuple(profiles),
        routes=tuple(routes),
        formats=tuple(
            _format_from_document(raw_format, f"{path}.formats[{index}]")
            for index, raw_format in enumerate(item.get("formats", ()))
        ),
        volume=item.get("volume"),
        mute=item.get("mute"),
        latency=EndpointLatencySummary(
            milliseconds=latency.get("milliseconds"),
            raw=latency.get("raw"),
            known=latency["known"],
        ),
        is_default=item["isDefault"],
        is_linked=item["isLinked"],
        has_active_signal=item["hasActiveSignal"],
    )


def resolver_inputs_from_document(document: Mapping[str, object]) -> ResolverInputs:
    root = _object(document, "$")
    desired = _object(root.get("desired"), "$.desired")
    world = _object(root.get("world"), "$.world")
    policies = _object(root.get("policies"), "$.policies")
    activation = _object(desired.get("activation"), "$.desired.activation")
    inventory = _object(world.get("endpointInventory"), "$.world.endpointInventory")
    signal_facts = _object(world.get("signalFacts"), "$.world.signalFacts")
    version = _object(world.get("version"), "$.world.version")
    resource_policy = _object(policies.get("resourcePolicy"), "$.policies.resourcePolicy")
    inputs = ResolverInputs(
        graph=_revision_from_document(desired.get("graphRevision"), "$.desired.graphRevision"),
        subgraph_revisions=tuple(
            _revision_from_document(item, f"$.desired.subgraphRevisions[{index}]")
            for index, item in enumerate(desired.get("subgraphRevisions", ()))
        ),
        activation=ResolverActivationInput(
            activation_id=activation["activationId"],
            definition_id=activation["definitionId"],
            revision_id=activation["revisionId"],
            desired_state_version=activation["desiredStateVersion"],
            parameter_bindings=_object(
                activation.get("parameterBindings", {}), "parameterBindings"
            ),
            scene_bindings=_object(activation.get("sceneBindings", {}), "sceneBindings"),
        ),
        logical_endpoints=tuple(
            ResolverLogicalEndpointInput(
                endpoint_id=endpoint["endpointId"],
                name=endpoint["name"],
                direction=endpoint["direction"],
                selector=_object(endpoint["selector"], "selector"),
                tags=tuple(endpoint.get("tags", ())),
                groups=tuple(endpoint.get("groups", ())),
                policy_metadata=_object(endpoint.get("policyMetadata", {}), "policyMetadata"),
                explicit_binding=(
                    _object(endpoint["explicitBinding"], "explicitBinding")
                    if endpoint.get("explicitBinding") is not None
                    else None
                ),
                update_version=endpoint.get("updateVersion", 1),
            )
            for endpoint in (
                _object(item, f"$.desired.logicalEndpoints[{index}]")
                for index, item in enumerate(desired.get("logicalEndpoints", ()))
            )
        ),
        runtime_inventory=EndpointInventorySnapshot(
            generation=inventory["generation"],
            sequence=inventory["sequence"],
            captured_at=inventory["capturedAt"],
            candidates=tuple(
                _candidate_from_document(item, f"$.world.endpointInventory.candidates[{index}]")
                for index, item in enumerate(inventory.get("candidates", ()))
            ),
        ),
        signal_facts=ResolverSignalFactsInput(
            version=signal_facts["version"],
            facts=_object(signal_facts.get("facts", {}), "signalFacts.facts"),
        ),
        processors=tuple(
            ResolverProcessorHealthInput(
                processor_id=processor["processorId"],
                health=processor["health"],
                ready=processor["ready"],
                facts=_object(processor.get("facts", {}), "processor.facts"),
            )
            for processor in (
                _object(item, f"$.world.processors[{index}]")
                for index, item in enumerate(world.get("processors", ()))
            )
        ),
        overrides=tuple(
            ResolverOverrideInput(
                override_id=override["overrideId"],
                scope_type=override["scopeType"],
                scope_id=override["scopeId"],
                value=override.get("value"),
                priority=override["priority"],
                starts_at=override["startsAt"],
                expires_at=override.get("expiresAt"),
                cancelled_at=override.get("cancelledAt"),
                active=override["active"],
                reason=override["reason"],
            )
            for override in (
                _object(item, f"$.world.overrides[{index}]")
                for index, item in enumerate(world.get("overrides", ()))
            )
        ),
        resource_policy=ResolverResourcePolicyInput(
            version=resource_policy["version"],
            resources=tuple(
                ResolverResourceInput(
                    resource_id=resource["resourceId"],
                    kind=resource["kind"],
                    capacity=resource["capacity"],
                    allocated=resource["allocated"],
                    health=resource["health"],
                    attributes=_object(resource.get("attributes", {}), "resource.attributes"),
                )
                for resource in (
                    _object(item, f"$.policies.resourcePolicy.resources[{index}]")
                    for index, item in enumerate(resource_policy.get("resources", ()))
                )
            ),
            policy=_object(resource_policy.get("policy", {}), "resourcePolicy.policy"),
        ),
        world_version=ResolverWorldVersion(
            runtime_generation=version["runtimeGeneration"],
            runtime_sequence=version["runtimeSequence"],
            endpoint_version=version["endpointVersion"],
            signal_version=version["signalVersion"],
            processor_version=version["processorVersion"],
            override_version=version["overrideVersion"],
            resource_policy_version=version["resourcePolicyVersion"],
        ),
        evaluated_at=world["evaluatedAt"],
    )
    expected_token = version.get("token")
    if expected_token is not None and expected_token != inputs.world_version.token:
        raise ResolverReplayError("$.world.version.token does not match its components")
    return inputs


def create_resolver_replay_bundle(
    inputs: ResolverInputs,
    *,
    registry: NodeTypeRegistry | None = None,
) -> dict[str, object]:
    plan = resolve_plan(inputs, registry=registry)
    return {
        "format": RESOLVER_REPLAY_FORMAT,
        "schemaVersion": RESOLVER_REPLAY_SCHEMA_VERSION,
        "versions": {
            "resolverInput": 1,
            "resolvedPlan": RESOLVED_PLAN_SCHEMA_VERSION,
            "desiredGraph": inputs.graph.schema_version,
            "desiredState": inputs.activation.desired_state_version,
            "world": inputs.world_version.token,
        },
        **resolver_inputs_to_document(inputs),
        "outputPlan": {
            "status": plan.status.value,
            "digest": plan.digest,
            "document": plan.document.to_dict(),
            "explanation": plan.explanation.to_dict(),
        },
    }


def replay_resolver_bundle(
    bundle: Mapping[str, object],
    *,
    registry: NodeTypeRegistry | None = None,
    verify_expected: bool = True,
) -> ResolverReplayResult:
    root = _object(bundle, "$")
    if root.get("format") != RESOLVER_REPLAY_FORMAT:
        raise ResolverReplayError(f"$.format must be {RESOLVER_REPLAY_FORMAT!r}")
    if root.get("schemaVersion") != RESOLVER_REPLAY_SCHEMA_VERSION:
        raise ResolverReplayError(f"$.schemaVersion must be {RESOLVER_REPLAY_SCHEMA_VERSION}")
    inputs = resolver_inputs_from_document(root)
    plan = resolve_plan(inputs, registry=registry)
    expected = root.get("outputPlan")
    expected_digest = None
    matches_expected = None
    if expected is not None:
        expected_plan = _object(expected, "$.outputPlan")
        expected_digest = expected_plan.get("digest")
        matches_expected = bool(
            expected_digest == plan.digest
            and expected_plan.get("status") == plan.status.value
            and expected_plan.get("document") == plan.document.to_dict()
            and expected_plan.get("explanation") == plan.explanation.to_dict()
        )
        if verify_expected and not matches_expected:
            raise ResolverReplayMismatch(
                "Replayed output does not match the bundle's expected plan"
            )
    return ResolverReplayResult(
        inputs=inputs,
        plan=plan,
        expected_digest=expected_digest,
        matches_expected=matches_expected,
    )
