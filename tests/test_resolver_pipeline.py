from copy import deepcopy
from dataclasses import replace

from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.node_catalogue import (
    NodePortDefinition,
    NodeTypeDefinition,
    NodeTypeRegistry,
    core_node_type_definitions,
)
from core.orchestration.resolver_inputs import (
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
from core.orchestration.resolver_pipeline import (
    ResolutionStage,
    run_resolution_pipeline,
)
from core.orchestration.signal_contracts import (
    AudioContent,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from tests.test_endpoint_inventory_mapping import _snapshot


def _port(name, direction, content=AudioContent.ANY):
    return NodePortDefinition(
        PortContract(
            name=name,
            direction=direction,
            signal=SignalContract(media_kind=MediaKind.AUDIO, content=content),
        )
    )


def _registry():
    registry = NodeTypeRegistry()
    for definition in core_node_type_definitions():
        registry.register(definition)
    registry.register(
        NodeTypeDefinition(
            type_id="test.processor",
            version=1,
            display_name="Test processor",
            category="test",
            description="Pure resolver pipeline test processor.",
            ports=(
                _port("input", PortDirection.INPUT),
                _port("output", PortDirection.OUTPUT, AudioContent.PCM),
            ),
            configuration_schema={"type": "object"},
        )
    )
    return registry


def _root_document():
    return {
        "schemaVersion": 1,
        "id": "graph:pipeline",
        "kind": "graph",
        "metadata": {"name": "Pipeline"},
        "parameters": [
            {
                "name": "gain",
                "type": "number",
                "required": False,
                "default": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
            }
        ],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": "endpoint:phone",
                    "direction": "input",
                },
            },
            {
                "id": "processing",
                "type": "core.subgraph-instance",
                "version": 1,
                "configuration": {},
                "subgraph": {
                    "definitionId": "subgraph:processing",
                    "revisionId": "revision:processing:1",
                    "parameterBindings": {"gain": {"parameter": "gain"}},
                    "portBindings": {"input": "input", "output": "output"},
                },
            },
            {
                "id": "sink",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": "endpoint:speakers",
                    "direction": "output",
                },
            },
        ],
        "edges": [
            {
                "id": "edge:in",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "processing", "port": "input"},
                "condition": {
                    "expression": {
                        "op": "eq",
                        "fact": "mode.cinema",
                        "value": True,
                    },
                    "unknownResult": "waiting",
                },
            },
            {
                "id": "edge:out",
                "from": {"node": "processing", "port": "output"},
                "to": {"node": "sink", "port": "input"},
            },
        ],
        "layout": {},
    }


def _subgraph_document():
    return {
        "schemaVersion": 1,
        "id": "subgraph:processing",
        "kind": "subgraph",
        "metadata": {"name": "Processing"},
        "parameters": [{"name": "gain", "type": "number", "required": True}],
        "publicPorts": [
            {
                "name": "input",
                "direction": "input",
                "contract": {"mediaKind": "audio", "content": "any"},
                "internalBinding": {"node": "process", "port": "input"},
            },
            {
                "name": "output",
                "direction": "output",
                "contract": {"mediaKind": "audio", "content": "pcm"},
                "internalBinding": {"node": "process", "port": "output"},
            },
        ],
        "conditions": [],
        "nodes": [
            {
                "id": "process",
                "type": "test.processor",
                "version": 1,
                "configuration": {"resourceRequirement": {"kind": "decoder", "units": 1}},
            }
        ],
        "edges": [],
        "layout": {},
    }


def _selector(path, value):
    return {
        "version": 1,
        "match": "all",
        "predicates": [{"path": path, "operator": "exact", "value": value}],
    }


def _resolver_inputs(*, cinema=True, resources=True, inventory=None):
    root = _root_document()
    subgraph = _subgraph_document()
    root_revision = ResolverGraphRevisionInput(
        definition_id="graph:pipeline",
        revision_id="revision:pipeline:1",
        revision_number=1,
        schema_version=1,
        content_digest=graph_content_digest(root),
        document=root,
    )
    subgraph_revision = ResolverGraphRevisionInput(
        definition_id="subgraph:processing",
        revision_id="revision:processing:1",
        revision_number=1,
        schema_version=1,
        content_digest=graph_content_digest(subgraph),
        document=subgraph,
    )
    runtime_inventory = inventory or map_runtime_endpoints(_snapshot())
    world = ResolverWorldVersion(
        runtime_generation=runtime_inventory.generation,
        runtime_sequence=runtime_inventory.sequence,
        endpoint_version=1,
        signal_version=1,
        processor_version=1,
        override_version=1,
        resource_policy_version=1,
    )
    resource_values = (
        (
            ResolverResourceInput(
                resource_id="decoder:0",
                kind="decoder",
                capacity=1,
                allocated=0,
                health="ready",
            ),
        )
        if resources
        else ()
    )
    return ResolverInputs(
        graph=root_revision,
        subgraph_revisions=(subgraph_revision,),
        activation=ResolverActivationInput(
            activation_id="activation:pipeline",
            definition_id="graph:pipeline",
            revision_id="revision:pipeline:1",
            desired_state_version=1,
            parameter_bindings={"gain": 0.7},
            scene_bindings={"cinema": cinema},
        ),
        logical_endpoints=(
            ResolverLogicalEndpointInput(
                endpoint_id="endpoint:phone",
                name="Phone",
                direction="input",
                selector=_selector(
                    "node.properties.api.bluez5.address",
                    "AA:BB:CC:DD:EE:FF",
                ),
            ),
            ResolverLogicalEndpointInput(
                endpoint_id="endpoint:speakers",
                name="Speakers",
                direction="output",
                selector=_selector(
                    "device.properties.device.serial",
                    "ROOM-123",
                ),
            ),
        ),
        runtime_inventory=runtime_inventory,
        signal_facts=ResolverSignalFactsInput(
            version=1,
            facts={"signal.source.content.codec": "pcm"},
        ),
        processors=(),
        overrides=(),
        resource_policy=ResolverResourcePolicyInput(
            version=1,
            resources=resource_values,
            policy={"conflict": "priority"},
        ),
        world_version=world,
        evaluated_at="2026-08-22T15:00:00+00:00",
    )


def test_pipeline_composes_all_pure_resolution_stages() -> None:
    result = run_resolution_pipeline(_resolver_inputs(), registry=_registry())

    assert result.valid
    assert result.issues == ()
    assert [node["id"] for node in result.expanded_document["nodes"]] == [
        "processing/process",
        "sink",
        "source",
    ]
    assert result.parameters["$root.gain"]["value"] == 0.7
    assert result.parameters["processing.gain"]["value"] == 0.7
    assert {
        binding.logical_endpoint_id: binding.status for binding in result.endpoint_bindings
    } == {
        "endpoint:phone": "matched",
        "endpoint:speakers": "matched",
    }
    assert result.facts["parameter.gain"] == 0.7
    assert result.facts["endpoint.endpoint:phone.availability"] == "route-available"
    assert result.facts["endpoint.endpoint:speakers.availability"] == "route-available"
    assert result.condition_results["$.edges[0].condition"] == "true"
    assert result.selected_edge_ids == ("edge:in", "edge:out")
    assert result.resource_assignments["processing/process"] == {
        "resourceId": "decoder:0",
        "units": 1,
    }
    assert result.resource_decisions["processing/process"] == {
        "status": "allocated",
        "kind": "decoder",
        "units": 1,
        "priority": 0,
        "resourceId": "decoder:0",
        "tieBreak": None,
        "competingNodeIds": (),
    }


def test_unrelated_unavailable_endpoint_does_not_degrade_graph() -> None:
    inputs = _resolver_inputs()
    unrelated = ResolverLogicalEndpointInput(
        endpoint_id="endpoint:unused-headset",
        name="Unused headset",
        direction="output",
        selector=_selector("node.name", "missing-headset"),
    )
    scoped = replace(
        inputs,
        logical_endpoints=(*inputs.logical_endpoints, unrelated),
    )

    result = run_resolution_pipeline(scoped, registry=_registry())

    assert result.valid
    assert result.issues == ()
    assert {binding.logical_endpoint_id for binding in result.endpoint_bindings} == {
        "endpoint:phone",
        "endpoint:speakers",
    }
    assert result.facts["endpoint.endpoint:unused-headset.availability"] == "unavailable"


def test_false_condition_prunes_incomplete_path_and_unused_resource() -> None:
    result = run_resolution_pipeline(_resolver_inputs(cinema=False), registry=_registry())

    assert result.condition_results["$.edges[0].condition"] == "false"
    assert result.selected_edge_ids == ()
    assert result.resource_assignments == {}
    assert result.resource_decisions == {}


def test_missing_resource_is_classified_at_resource_stage() -> None:
    result = run_resolution_pipeline(_resolver_inputs(resources=False), registry=_registry())

    assert not result.valid
    resource_issues = [issue for issue in result.issues if issue.stage is ResolutionStage.RESOURCES]
    assert len(resource_issues) == 1
    assert resource_issues[0].code == "resource_unavailable"


def test_missing_endpoint_removes_complete_path_with_endpoint_diagnostic() -> None:
    inventory = map_runtime_endpoints(_snapshot())
    without_sink = type(inventory)(
        generation=inventory.generation,
        sequence=inventory.sequence,
        captured_at=inventory.captured_at,
        candidates=tuple(
            candidate for candidate in inventory.candidates if candidate.direction.value == "input"
        ),
    )

    result = run_resolution_pipeline(_resolver_inputs(inventory=without_sink), registry=_registry())

    assert result.selected_edge_ids == ()
    assert any(
        issue.stage is ResolutionStage.ENDPOINTS and issue.code == "endpoint_no_match"
        for issue in result.issues
    )


def test_saved_subgraph_survives_missing_dependencies_and_reconciles_on_return() -> None:
    available_inputs = _resolver_inputs()
    original_graph = available_inputs.graph.document.to_dict()
    original_subgraph = available_inputs.subgraph_revisions[0].document.to_dict()
    first = run_resolution_pipeline(available_inputs, registry=_registry())
    inventory = available_inputs.runtime_inventory
    without_sink = type(inventory)(
        generation=inventory.generation,
        sequence=inventory.sequence + 1,
        captured_at=inventory.captured_at,
        candidates=tuple(
            candidate for candidate in inventory.candidates if candidate.direction.value == "input"
        ),
    )

    absent = run_resolution_pipeline(
        _resolver_inputs(inventory=without_sink, resources=False),
        registry=_registry(),
    )
    returned = run_resolution_pipeline(_resolver_inputs(), registry=_registry())

    assert first.valid
    assert not absent.valid
    assert {issue.stage for issue in absent.issues}.issubset(
        {ResolutionStage.ENDPOINTS, ResolutionStage.RESOURCES}
    )
    assert available_inputs.graph.document.to_dict() == original_graph
    assert available_inputs.subgraph_revisions[0].document.to_dict() == original_subgraph
    assert returned.valid
    assert returned.expanded_document == first.expanded_document
    assert returned.selected_edge_ids == first.selected_edge_ids
    assert returned.resource_assignments == first.resource_assignments


def test_pipeline_does_not_mutate_input_documents() -> None:
    root = _root_document()
    original = deepcopy(root)
    inputs = _resolver_inputs()

    run_resolution_pipeline(inputs, registry=_registry())

    assert root == original
    assert inputs.graph.document["nodes"][1]["id"] == "processing"


def test_pipeline_exposes_deterministic_selector_decision() -> None:
    inputs = _resolver_inputs()
    document = inputs.graph.document.to_dict()
    document["nodes"].append(
        {
            "id": "preferred-output",
            "type": "core.ordered-selector",
            "version": 1,
            "configuration": {
                "mode": "exclusive",
                "tieBreak": "declaration-order",
                "candidates": [
                    {"endpoint": "endpoint:speakers", "priority": 100},
                    {"endpoint": "endpoint:phone", "priority": 100},
                ],
            },
        }
    )
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=graph_content_digest(document),
        document=document,
    )

    result = run_resolution_pipeline(
        replace(inputs, graph=graph),
        registry=_registry(),
    )

    decision = result.selector_decisions["preferred-output"]
    assert decision["status"] == "resolved"
    assert decision["selected"][0]["referenceId"] == "endpoint:speakers"
    assert decision["rejected"][0]["reason"] == "declaration_order_tie_break"


def test_temporary_parameter_override_changes_resolution_without_editing_activation() -> None:
    inputs = _resolver_inputs()
    document = inputs.graph.document.to_dict()
    document["edges"][0]["condition"]["expression"] = {
        "op": "gt",
        "fact": "parameter.gain",
        "value": 0.6,
    }
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=graph_content_digest(document),
        document=document,
    )
    temporary = ResolverOverrideInput(
        override_id="override:gain",
        scope_type="graph_parameter",
        scope_id="gain",
        value={"value": 0.2},
        priority=200,
        starts_at="2026-08-22T14:00:00+00:00",
        expires_at="2026-08-22T16:00:00+00:00",
        cancelled_at=None,
        active=True,
        reason="Quiet temporary profile",
    )

    result = run_resolution_pipeline(
        replace(inputs, graph=graph, overrides=(temporary,)),
        registry=_registry(),
    )

    assert result.facts["parameter.gain"] == 0.2
    assert result.condition_results["$.edges[0].condition"] == "false"
    assert result.selected_edge_ids == ()
    assert result.override_resolution["provenance"]["parameter.gain"]["source"] == (
        "temporary_override"
    )
    assert inputs.activation.parameter_bindings["gain"] == 0.7
