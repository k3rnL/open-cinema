from dataclasses import FrozenInstanceError

import pytest

from core.orchestration.endpoint_inventory import EndpointInventorySnapshot
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.resolver_inputs import (
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


def _document():
    return {
        "schemaVersion": 1,
        "id": "graph:test",
        "kind": "graph",
        "metadata": {"name": "Test"},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [],
        "edges": [],
        "layout": {},
    }


def _inputs():
    document = _document()
    graph = ResolverGraphRevisionInput(
        definition_id="graph:test",
        revision_id="revision:test:1",
        revision_number=1,
        schema_version=1,
        content_digest=graph_content_digest(document),
        document=document,
    )
    activation = ResolverActivationInput(
        activation_id="activation:test",
        definition_id="graph:test",
        revision_id="revision:test:1",
        desired_state_version=3,
        parameter_bindings={"volume": {"value": 0.5}},
        scene_bindings={"scene": "cinema"},
    )
    endpoints = (
        ResolverLogicalEndpointInput(
            endpoint_id="endpoint:speakers",
            name="Speakers",
            direction="output",
            selector={"version": 1, "match": "all", "predicates": []},
            tags=["preferred-output", "speaker"],
            groups=["room-speakers"],
            policy_metadata={"priority": 100},
        ),
        ResolverLogicalEndpointInput(
            endpoint_id="endpoint:headset",
            name="Headset",
            direction="output",
            selector={"version": 1, "match": "all", "predicates": []},
            tags=["preferred-output", "headset"],
            groups=["headsets"],
            policy_metadata={"priority": 200},
        ),
    )
    inventory = EndpointInventorySnapshot(
        generation=8,
        sequence=21,
        captured_at="2026-08-22T15:00:00Z",
        candidates=(),
    )
    signals = ResolverSignalFactsInput(
        version=4,
        facts={"signal.input.content.codec": "pcm"},
    )
    processors = (
        ResolverProcessorHealthInput(
            processor_id="processor:camilladsp",
            health="ready",
            ready=True,
            facts={"activeProfile": "cinema"},
        ),
    )
    overrides = (
        ResolverOverrideInput(
            override_id="override:low",
            scope_type="mute",
            scope_id="endpoint:speakers",
            value=False,
            priority=100,
            starts_at="2026-08-22T14:00:00+00:00",
            expires_at=None,
            cancelled_at=None,
            active=True,
            reason="Resume playback",
        ),
        ResolverOverrideInput(
            override_id="override:high",
            scope_type="endpoint",
            scope_id="primary-output",
            value="endpoint:headset",
            priority=300,
            starts_at="2026-08-22T14:30:00+00:00",
            expires_at="2026-08-22T16:00:00+00:00",
            cancelled_at=None,
            active=True,
            reason="Temporary headset",
        ),
    )
    resources = ResolverResourcePolicyInput(
        version=2,
        resources=(
            ResolverResourceInput(
                resource_id="camilladsp:0",
                kind="camilladsp",
                capacity=1,
                allocated=0,
                health="ready",
                attributes={"rates": [48000, 96000]},
            ),
        ),
        policy={"conflict": "priority"},
    )
    world = ResolverWorldVersion(
        runtime_generation=8,
        runtime_sequence=21,
        endpoint_version=7,
        signal_version=4,
        processor_version=5,
        override_version=6,
        resource_policy_version=2,
    )
    return ResolverInputs(
        graph=graph,
        subgraph_revisions=(),
        activation=activation,
        logical_endpoints=reversed(endpoints),
        runtime_inventory=inventory,
        signal_facts=signals,
        processors=processors,
        overrides=overrides,
        resource_policy=resources,
        world_version=world,
        evaluated_at="2026-08-22T15:00:00+00:00",
    )


def test_resolver_input_boundary_is_deeply_immutable_and_canonical() -> None:
    inputs = _inputs()

    assert [endpoint.endpoint_id for endpoint in inputs.logical_endpoints] == [
        "endpoint:headset",
        "endpoint:speakers",
    ]
    assert [override.override_id for override in inputs.overrides] == [
        "override:high",
        "override:low",
    ]
    assert inputs.world_version.token == "8:21:7:4:5:6:2"
    assert inputs.graph.document["metadata"]["name"] == "Test"

    with pytest.raises(FrozenInstanceError):
        inputs.evaluated_at = "changed"
    with pytest.raises(TypeError):
        inputs.graph.document["metadata"]["name"] = "Changed"
    with pytest.raises(TypeError):
        inputs.activation.parameter_bindings["volume"] = 1
    with pytest.raises(TypeError):
        inputs.resource_policy.resources[0].attributes["rates"] = []


def test_constructor_detaches_from_mutable_source_documents() -> None:
    document = _document()
    digest = graph_content_digest(document)
    graph = ResolverGraphRevisionInput(
        definition_id="graph:test",
        revision_id="revision:test:1",
        revision_number=1,
        schema_version=1,
        content_digest=digest,
        document=document,
    )

    document["metadata"]["name"] = "Mutated outside"

    assert graph.document["metadata"]["name"] == "Test"


def test_graph_digest_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="content_digest"):
        ResolverGraphRevisionInput(
            definition_id="graph:test",
            revision_id="revision:test:1",
            revision_number=1,
            schema_version=1,
            content_digest="0" * 64,
            document=_document(),
        )


@pytest.mark.parametrize(
    "change",
    (
        {"runtime_generation": 9},
        {"runtime_sequence": 22},
        {"signal_version": 5},
        {"resource_policy_version": 3},
    ),
)
def test_inconsistent_world_components_are_rejected(change) -> None:
    inputs = _inputs()
    values = {
        "runtime_generation": 8,
        "runtime_sequence": 21,
        "endpoint_version": 7,
        "signal_version": 4,
        "processor_version": 5,
        "override_version": 6,
        "resource_policy_version": 2,
        **change,
    }

    with pytest.raises(ValueError, match="do not match"):
        ResolverInputs(
            graph=inputs.graph,
            subgraph_revisions=inputs.subgraph_revisions,
            activation=inputs.activation,
            logical_endpoints=inputs.logical_endpoints,
            runtime_inventory=inputs.runtime_inventory,
            signal_facts=inputs.signal_facts,
            processors=inputs.processors,
            overrides=inputs.overrides,
            resource_policy=inputs.resource_policy,
            world_version=ResolverWorldVersion(**values),
            evaluated_at=inputs.evaluated_at,
        )


def test_activation_must_reference_exact_graph_revision() -> None:
    inputs = _inputs()
    activation = ResolverActivationInput(
        activation_id="activation:test",
        definition_id="graph:test",
        revision_id="revision:test:other",
        desired_state_version=1,
    )

    with pytest.raises(ValueError, match="graph revision"):
        ResolverInputs(
            graph=inputs.graph,
            subgraph_revisions=inputs.subgraph_revisions,
            activation=activation,
            logical_endpoints=inputs.logical_endpoints,
            runtime_inventory=inputs.runtime_inventory,
            signal_facts=inputs.signal_facts,
            processors=inputs.processors,
            overrides=inputs.overrides,
            resource_policy=inputs.resource_policy,
            world_version=inputs.world_version,
            evaluated_at=inputs.evaluated_at,
        )


def test_duplicate_scope_identifiers_are_rejected() -> None:
    inputs = _inputs()

    with pytest.raises(ValueError, match="logical_endpoints identifiers"):
        ResolverInputs(
            graph=inputs.graph,
            subgraph_revisions=inputs.subgraph_revisions,
            activation=inputs.activation,
            logical_endpoints=(inputs.logical_endpoints[0], inputs.logical_endpoints[0]),
            runtime_inventory=inputs.runtime_inventory,
            signal_facts=inputs.signal_facts,
            processors=inputs.processors,
            overrides=inputs.overrides,
            resource_policy=inputs.resource_policy,
            world_version=inputs.world_version,
            evaluated_at=inputs.evaluated_at,
        )


def test_resource_allocation_cannot_exceed_capacity() -> None:
    with pytest.raises(ValueError, match="exceed capacity"):
        ResolverResourceInput(
            resource_id="decoder:0",
            kind="decoder",
            capacity=1,
            allocated=2,
            health="ready",
        )
