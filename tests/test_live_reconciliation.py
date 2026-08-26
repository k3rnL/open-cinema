from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from django.contrib.auth import get_user_model
from django.test import override_settings

import pytest
from wyreplumber.runtime import (
    FrozenDict,
    LinkValue,
    NodeState,
    NodeValue,
    PortDirection,
    PortValue,
)

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    LogicalEndpoint,
    OrchestrationEvent,
    TransitionJournal,
    TransitionStatus,
)
from core.orchestration.activations import activate_graph, deactivate_graph
from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from core.orchestration.decoder_driver import DecoderInstanceConfiguration
from core.orchestration.live_reconciliation import (
    IncompleteProcessorTopology,
    LiveGraphReconciler,
    _pair_audio_ports,
    _require_complete_processor_port_coverage,
)
from core.orchestration.runtime_world import InMemoryWorldStore
from core.orchestration.resolver_inputs import ResolverSignalFactsInput
from core.orchestration.transition_journal import TransitionJournalStore
from core.plugin_system.contracts import ProcessingDriverRequest
from tests.test_endpoint_inventory_mapping import _snapshot

pytestmark = pytest.mark.django_db


FEATURES = {
    "orchestration_api": True,
    "runtime_observation": True,
    "shadow_resolution": True,
    "processor_management": True,
    "live_reconciliation": True,
}


def _selector(node_name: str):
    return {
        "version": 1,
        "match": "all",
        "predicates": [{"path": "node.name", "operator": "exact", "value": node_name}],
    }


def test_declared_layout_maps_unlabelled_processor_ports_by_natural_index() -> None:
    channels = ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")
    output_ids = (71, 12, 93, 24, 85, 36, 67, 48)
    input_ids = (19, 82, 33, 74, 45, 96, 57, 68)
    runtime = type(
        "Runtime",
        (),
        {
            "ports": tuple(
                PortValue(
                    port_id,
                    10,
                    PortDirection.OUTPUT,
                    name=f"output_{index}",
                    channel="UNK",
                )
                for index, port_id in enumerate(output_ids, start=1)
            )
            + tuple(
                PortValue(
                    port_id,
                    20,
                    PortDirection.INPUT,
                    name=f"playback_{channel}",
                    channel=channel,
                )
                for channel, port_id in zip(channels, input_ids, strict=True)
            )
        },
    )()

    pairs = _pair_audio_ports(runtime, 10, 20, channel_order=channels)

    assert [channel for channel, _output, _input in pairs] == list(channels)
    assert [output.name for _channel, output, _input in pairs] == [
        f"output_{index}" for index in range(1, 9)
    ]
    assert [input_.name for _channel, _output, input_ in pairs] == [
        f"playback_{channel}" for channel in channels
    ]


def test_endpoint_route_can_select_stereo_subset_from_declared_processor_bus() -> None:
    channels = ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")
    runtime = type(
        "Runtime",
        (),
        {
            "ports": tuple(
                PortValue(
                    100 + index,
                    10,
                    PortDirection.OUTPUT,
                    name=f"output_{index}",
                    channel="UNK",
                )
                for index in range(1, 9)
            )
            + (
                PortValue(201, 20, PortDirection.INPUT, name="playback_FL", channel="FL"),
                PortValue(202, 20, PortDirection.INPUT, name="playback_FR", channel="FR"),
            )
        },
    )()

    pairs = _pair_audio_ports(
        runtime,
        10,
        20,
        channel_order=channels,
        allow_channel_subset=True,
    )

    assert [channel for channel, _output, _input in pairs] == ["FL", "FR"]
    assert [output.name for _channel, output, _input in pairs] == [
        "output_1",
        "output_2",
    ]


class MemoryAdapter:
    def __init__(self):
        self.present = set()
        self.arguments = {}
        self.performed = []
        self.refresh_count = 0
        self.hidden_from_refresh = set()
        self.extra_links = ()

    def perform(self, action):
        if action.command.operation == "remove-managed-link":
            self.present.discard(action.identity.resource_id)
            self.arguments.pop(action.identity.resource_id, None)
        else:
            self.present.add(action.identity.resource_id)
            self.arguments[action.identity.resource_id] = action.command.arguments.to_dict()
        self.performed.append(action)
        return {"status": "confirmed"}

    def refreshed_world(self, initial_world):
        self.refresh_count += 1

        def runtime_id(runtime_key):
            return int(str(runtime_key).rsplit(":", 1)[1])

        links = tuple(
            LinkValue(
                id=index,
                output_node_id=runtime_id(arguments["outputNodeRuntimeKey"]),
                output_port_id=runtime_id(arguments["outputPortRuntimeKey"]),
                input_node_id=runtime_id(arguments["inputNodeRuntimeKey"]),
                input_port_id=runtime_id(arguments["inputPortRuntimeKey"]),
                owner="open-cinema.orchestrator",
                desired_id=desired_id,
                properties=FrozenDict(
                    {
                        **dict(arguments.get("properties", {})),
                        "open-cinema.owner": "open-cinema.orchestrator",
                        "open-cinema.desired-id": desired_id,
                    }
                ),
            )
            for index, (desired_id, arguments) in enumerate(
                sorted(self.arguments.items()),
                start=1,
            )
            if desired_id in self.present and desired_id not in self.hidden_from_refresh
        ) + tuple(self.extra_links)
        runtime = replace(
            initial_world.runtime,
            sequence=initial_world.runtime.sequence + self.refresh_count,
            links=links,
        )
        return InMemoryWorldStore().install_runtime_snapshot(runtime)


class MemoryLiveGraphReconciler(LiveGraphReconciler):
    def _observe(self, action):
        desired_id = action.identity.resource_id
        arguments = action.command.arguments
        prefix = f"managedLink.open-cinema.orchestrator.{desired_id}"
        present = desired_id in self.adapter.present
        observed = self.adapter.arguments.get(desired_id, arguments)
        return {
            f"{prefix}.present": present,
            f"{prefix}.conflict": False,
            f"{prefix}.tagged": present,
            f"{prefix}.outputNodeRuntimeKey": (
                observed.get("outputNodeRuntimeKey") if present else None
            ),
            f"{prefix}.outputPortRuntimeKey": (
                observed.get("outputPortRuntimeKey") if present else None
            ),
            f"{prefix}.inputNodeRuntimeKey": (
                observed.get("inputNodeRuntimeKey") if present else None
            ),
            f"{prefix}.inputPortRuntimeKey": (
                observed.get("inputPortRuntimeKey") if present else None
            ),
        }


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_live_endpoint_route_resolves_executes_and_becomes_current() -> None:
    owner = get_user_model().objects.create_user(username="live-route-owner")
    source = LogicalEndpoint.objects.create(
        name="Programme source",
        owner=owner,
        direction="input",
        selector=_selector("bluez_input.phone"),
    )
    sink = LogicalEndpoint.objects.create(
        name="Main output",
        owner=owner,
        direction="output",
        selector=_selector("alsa_output.usb-room"),
    )
    graph = GraphDefinition.objects.create(name="Live route", owner=owner)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={
            "schemaVersion": 1,
            "id": "graph:live-route",
            "kind": "graph",
            "metadata": {"name": "Live route", "labels": {}},
            "parameters": [],
            "publicPorts": [],
            "conditions": [],
            "nodes": [
                {
                    "id": "source",
                    "type": "core.endpoint-reference",
                    "version": 1,
                    "configuration": {
                        "logicalEndpointId": str(source.pk),
                        "direction": "input",
                    },
                },
                {
                    "id": "sink",
                    "type": "core.endpoint-reference",
                    "version": 1,
                    "configuration": {
                        "logicalEndpointId": str(sink.pk),
                        "direction": "output",
                    },
                },
            ],
            "edges": [
                {
                    "id": "programme-to-main",
                    "from": {"node": "source", "port": "output"},
                    "to": {"node": "sink", "port": "input"},
                }
            ],
            "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
        },
    )
    activate_graph(definition=graph, revision=revision, expected_version=0)
    world = InMemoryWorldStore().install_runtime_snapshot(_snapshot())
    adapter = MemoryAdapter()
    signal = [
        ResolverSignalFactsInput(
            1,
            {
                "signal.decoder-main.content.codec": "ac3",
                "signal.decoder-main.decoded.channels": 6,
                "signal.decoder-main.emitted.channels": 8,
            },
        )
    ]
    reconciler = MemoryLiveGraphReconciler(
        lambda: None,
        adapter=adapter,
        journal_store=TransitionJournalStore(),
        signal_facts_provider=lambda: signal[0],
    )

    result = reconciler.reconcile(str(graph.pk), world)

    assert result.applied is True, result.plan.document["errors"]
    assert result.action_count == 1
    assert result.plan.status == "resolved"
    assert adapter.performed[0].command.arguments["shape"] == "endpoint-route"
    assert adapter.performed[0].command.arguments["properties"]["audio.channel"] == "FL"
    state = AppliedPlanState.objects.get(graph_definition=graph)
    assert state.status == AppliedPlanStatus.CONVERGED
    assert state.current_plan == result.plan
    journal = TransitionJournal.objects.get(graph_definition=graph)
    assert journal.status == TransitionStatus.SUCCEEDED
    assert journal.entries[0]["status"] == "succeeded"

    signal[0] = ResolverSignalFactsInput(
        2,
        {
            "signal.decoder-main.content.codec": None,
            "signal.decoder-main.decoded.channels": None,
            "signal.decoder-main.emitted.channels": 8,
        },
    )
    menu = reconciler.reconcile(str(graph.pk), world)
    signal[0] = ResolverSignalFactsInput(
        3,
        {
            "signal.decoder-main.content.codec": "dts",
            "signal.decoder-main.decoded.channels": 8,
            "signal.decoder-main.emitted.channels": 8,
        },
    )
    movie = reconciler.reconcile(str(graph.pk), world)

    assert menu.applied is False and menu.action_count == 0
    assert movie.applied is False and movie.action_count == 0
    assert menu.plan.plan_digest != movie.plan.plan_digest
    assert (
        menu.plan.document["effectivePlanDigest"]
        == movie.plan.document["effectivePlanDigest"]
        == result.plan.document["effectivePlanDigest"]
    )
    assert len(adapter.performed) == 1
    state.refresh_from_db()
    assert state.transition_generation == 1
    assert state.current_plan == movie.plan
    assert OrchestrationEvent.objects.filter(event_type="reconciliation-noop").count() == 2


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_live_route_replaces_obsolete_identity_before_recreating_same_topology() -> None:
    owner = get_user_model().objects.create_user(username="live-route-rename-owner")
    source = LogicalEndpoint.objects.create(
        name="Programme source",
        owner=owner,
        direction="input",
        selector=_selector("bluez_input.phone"),
    )
    sink = LogicalEndpoint.objects.create(
        name="Main output",
        owner=owner,
        direction="output",
        selector=_selector("alsa_output.usb-room"),
    )
    graph = GraphDefinition.objects.create(name="Renamed live route", owner=owner)
    content = {
        "schemaVersion": 1,
        "id": "graph:renamed-live-route",
        "kind": "graph",
        "metadata": {"name": "Renamed live route", "labels": {}},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": str(source.pk),
                    "direction": "input",
                },
            },
            {
                "id": "sink",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": str(sink.pk),
                    "direction": "output",
                },
            },
        ],
        "edges": [
            {
                "id": "old-route",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "sink", "port": "input"},
            }
        ],
        "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
    }
    first_revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=content,
    )
    activate_graph(definition=graph, revision=first_revision, expected_version=0)
    runtime = _snapshot()
    adapter = MemoryAdapter()
    reconciler = MemoryLiveGraphReconciler(
        lambda: None,
        adapter=adapter,
        journal_store=TransitionJournalStore(),
    )

    first = reconciler.reconcile(
        str(graph.pk), InMemoryWorldStore().install_runtime_snapshot(runtime)
    )
    first_action = adapter.performed[-1]
    first_arguments = first_action.command.arguments
    old_desired_id = first_action.identity.resource_id
    existing = LinkValue(
        id=56,
        output_node_id=int(first_arguments["outputNodeRuntimeKey"].rsplit(":", 1)[1]),
        output_port_id=int(first_arguments["outputPortRuntimeKey"].rsplit(":", 1)[1]),
        input_node_id=int(first_arguments["inputNodeRuntimeKey"].rsplit(":", 1)[1]),
        input_port_id=int(first_arguments["inputPortRuntimeKey"].rsplit(":", 1)[1]),
        owner="open-cinema.orchestrator",
        desired_id=old_desired_id,
        properties=FrozenDict(
            {
                **first_arguments["properties"].to_dict(),
                "open-cinema.owner": "open-cinema.orchestrator",
                "open-cinema.desired-id": old_desired_id,
            }
        ),
    )
    renamed_content = deepcopy(content)
    renamed_content["edges"][0]["id"] = "new-route"
    second_revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=2,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=renamed_content,
    )
    activate_graph(
        definition=graph,
        revision=second_revision,
        expected_version=1,
    )
    world = InMemoryWorldStore().install_runtime_snapshot(
        replace(runtime, sequence=runtime.sequence + 1, links=(existing,))
    )

    renamed = reconciler.reconcile(str(graph.pk), world)

    assert first.applied is True
    assert renamed.applied is True, renamed.reason
    assert renamed.action_count == 2
    assert [action.command.operation for action in adapter.performed[-2:]] == [
        "remove-managed-link",
        "create-managed-link",
    ]
    assert adapter.performed[-2].identity.resource_id == old_desired_id
    assert adapter.performed[-1].identity.resource_id.endswith(":new-route:FL")
    state = AppliedPlanState.objects.get(graph_definition=graph)
    assert state.status == AppliedPlanStatus.CONVERGED
    assert state.current_plan == renamed.plan


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_live_selectors_replace_route_when_preferred_endpoints_change() -> None:
    owner = get_user_model().objects.create_user(username="live-selector-owner")
    endpoints = {
        "phone": LogicalEndpoint.objects.create(
            name="Bluetooth programme",
            owner=owner,
            direction="input",
            selector=_selector("bluez_input.phone"),
        ),
        "fallback": LogicalEndpoint.objects.create(
            name="Fallback programme",
            owner=owner,
            direction="input",
            selector=_selector("debug_input.fallback"),
        ),
        "headset": LogicalEndpoint.objects.create(
            name="Headset",
            owner=owner,
            direction="output",
            selector=_selector("bluez_output.headset"),
        ),
        "speakers": LogicalEndpoint.objects.create(
            name="Main speakers",
            owner=owner,
            direction="output",
            selector=_selector("alsa_output.usb-room"),
        ),
    }
    graph = GraphDefinition.objects.create(name="Live selector route", owner=owner)

    def conditional_candidate(endpoint, priority, fact=None):
        candidate = {"endpoint": str(endpoint.pk), "priority": priority}
        if fact is not None:
            candidate.update(
                {
                    "eligibleWhen": {"op": "eq", "fact": fact, "value": True},
                    "unknownResult": "ineligible",
                }
            )
        return candidate

    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={
            "schemaVersion": 1,
            "id": "graph:live-selector-route",
            "kind": "graph",
            "metadata": {"name": "Live selector route", "labels": {}},
            "parameters": [],
            "publicPorts": [],
            "conditions": [],
            "nodes": [
                {
                    "id": "programme-selector",
                    "type": "core.ordered-selector",
                    "version": 1,
                    "configuration": {
                        "mode": "first-available",
                        "tieBreak": "declaration-order",
                        "candidates": [
                            conditional_candidate(endpoints["phone"], 200, "mode.phone"),
                            conditional_candidate(endpoints["fallback"], 100),
                        ],
                    },
                },
                {
                    "id": "output-selector",
                    "type": "core.ordered-selector",
                    "version": 1,
                    "configuration": {
                        "mode": "first-available",
                        "tieBreak": "declaration-order",
                        "candidates": [
                            conditional_candidate(endpoints["headset"], 200, "mode.headset"),
                            conditional_candidate(endpoints["speakers"], 100),
                        ],
                    },
                },
            ],
            "edges": [
                {
                    "id": "selected-programme-to-output",
                    "from": {"node": "programme-selector", "port": "audio"},
                    "to": {"node": "output-selector", "port": "input"},
                }
            ],
            "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
        },
    )
    activate_graph(
        definition=graph,
        revision=revision,
        expected_version=0,
        scene_bindings={"phone": True, "headset": True},
    )

    runtime = _snapshot()
    runtime = replace(
        runtime,
        nodes=(
            *runtime.nodes,
            NodeValue(
                id=21,
                name="debug_input.fallback",
                description="Fallback programme",
                media_class="Audio/Source",
                state=NodeState.RUNNING,
                output_port_ids=(103,),
            ),
            NodeValue(
                id=11,
                name="bluez_output.headset",
                description="Headset",
                media_class="Audio/Sink",
                state=NodeState.IDLE,
                input_port_ids=(104,),
            ),
        ),
        ports=(
            *runtime.ports,
            PortValue(103, 21, PortDirection.OUTPUT, name="capture_FL", channel="FL"),
            PortValue(104, 11, PortDirection.INPUT, name="playback_FL", channel="FL"),
        ),
        links=(),
    )
    world = InMemoryWorldStore().install_runtime_snapshot(runtime)
    adapter = MemoryAdapter()
    reconciler = MemoryLiveGraphReconciler(
        lambda: None,
        adapter=adapter,
        journal_store=TransitionJournalStore(),
    )

    preferred = reconciler.reconcile(str(graph.pk), world)

    assert preferred.applied is True, preferred.plan.document["errors"]
    assert preferred.action_count == 1
    assert preferred.plan.document["selections"]["programme-selector"]["selected"][0][
        "referenceId"
    ] == str(endpoints["phone"].pk)
    assert preferred.plan.document["selections"]["output-selector"]["selected"][0][
        "referenceId"
    ] == str(endpoints["headset"].pk)
    first_action = adapter.performed[-1]
    first_arguments = first_action.command.arguments
    assert first_arguments["outputNodeRuntimeKey"].endswith(":node:20")
    assert first_arguments["inputNodeRuntimeKey"].endswith(":node:11")

    desired_id = first_action.identity.resource_id
    existing = LinkValue(
        id=56,
        output_node_id=20,
        output_port_id=102,
        input_node_id=11,
        input_port_id=104,
        owner="open-cinema.orchestrator",
        desired_id=desired_id,
        properties=FrozenDict(
            {
                **first_arguments["properties"].to_dict(),
                "open-cinema.owner": "open-cinema.orchestrator",
                "open-cinema.desired-id": desired_id,
            }
        ),
    )
    fallback_world = InMemoryWorldStore().install_runtime_snapshot(
        replace(runtime, sequence=runtime.sequence + 1, links=(existing,))
    )
    activate_graph(
        definition=graph,
        revision=revision,
        expected_version=1,
        scene_bindings={"phone": False, "headset": False},
    )

    fallback = reconciler.reconcile(str(graph.pk), fallback_world)

    assert fallback.applied is True, fallback.plan.document["errors"]
    assert fallback.action_count == 2
    assert [action.command.operation for action in adapter.performed[-2:]] == [
        "remove-managed-link",
        "create-managed-link",
    ]
    fallback_arguments = adapter.performed[-1].command.arguments
    assert fallback_arguments["outputNodeRuntimeKey"].endswith(":node:21")
    assert fallback_arguments["inputNodeRuntimeKey"].endswith(":node:10")
    state = AppliedPlanState.objects.get(graph_definition=graph)
    assert state.status == AppliedPlanStatus.CONVERGED


def _processor_chain_world():
    runtime = _snapshot()
    channels = ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")
    source_ports = (102, 103)
    sink_ports = (101, *range(104, 111))
    decoder = DecoderInstanceConfiguration.from_request(
        ProcessingDriverRequest(
            node_instance_id="decoder",
            idempotency_key="test",
            configuration={"instanceId": "decoder-0"},
            plan={},
        )
    )
    decoder_capture, decoder_output = decoder.runtime_identities
    camilla_capture, camilla_playback = CamillaDSPDeploymentPolicy().runtime_identities(0)

    def node(identity, node_id, port_id, direction):
        return NodeValue(
            id=node_id,
            name=identity.node_name,
            media_class=(
                "Stream/Input/Audio" if direction is PortDirection.INPUT else "Stream/Output/Audio"
            ),
            state=NodeState.IDLE,
            input_port_ids=(port_id,) if direction is PortDirection.INPUT else (),
            output_port_ids=(port_id,) if direction is PortDirection.OUTPUT else (),
            properties=FrozenDict(
                {
                    "node.name": identity.node_name,
                    "node.group": identity.node_group_name,
                    **identity.required_properties.to_dict(),
                }
            ),
        )

    processor_nodes = (
        replace(
            node(decoder_capture, 40, 401, PortDirection.INPUT),
            input_port_ids=(401, 402),
        ),
        replace(
            node(decoder_output, 41, 411, PortDirection.OUTPUT),
            output_port_ids=tuple(range(411, 419)),
        ),
        replace(
            node(camilla_capture, 42, 421, PortDirection.INPUT),
            input_port_ids=tuple(range(421, 429)),
        ),
        replace(
            node(camilla_playback, 43, 431, PortDirection.OUTPUT),
            output_port_ids=tuple(range(431, 439)),
        ),
    )
    processor_ports = (
        PortValue(401, 40, PortDirection.INPUT, channel="FL"),
        PortValue(402, 40, PortDirection.INPUT, channel="FR"),
        *(
            PortValue(port_id, 41, PortDirection.OUTPUT, channel=channel)
            for port_id, channel in zip(range(411, 419), channels, strict=True)
        ),
        *(
            PortValue(port_id, 42, PortDirection.INPUT, channel=channel)
            for port_id, channel in zip(range(421, 429), channels, strict=True)
        ),
        *(
            PortValue(port_id, 43, PortDirection.OUTPUT, channel=channel)
            for port_id, channel in zip(range(431, 439), channels, strict=True)
        ),
    )
    endpoint_nodes = tuple(
        (
            replace(runtime_node, output_port_ids=source_ports)
            if runtime_node.id == 20
            else (
                replace(runtime_node, input_port_ids=sink_ports)
                if runtime_node.id == 10
                else runtime_node
            )
        )
        for runtime_node in runtime.nodes
    )
    endpoint_ports = (
        *runtime.ports,
        PortValue(103, 20, PortDirection.OUTPUT, channel="FR"),
        *(
            PortValue(port_id, 10, PortDirection.INPUT, channel=channel)
            for port_id, channel in zip(sink_ports[1:], channels[1:], strict=True)
        ),
    )
    return InMemoryWorldStore().install_runtime_snapshot(
        replace(
            runtime,
            nodes=(*endpoint_nodes, *processor_nodes),
            ports=(*endpoint_ports, *processor_ports),
            links=(),
        )
    )


def test_processor_bus_rejects_a_partial_declared_channel_set_before_mutation() -> None:
    world = _processor_chain_world()
    channels = ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")
    pairs = _pair_audio_ports(
        world.runtime,
        41,
        42,
        channel_order=channels,
    )

    with pytest.raises(IncompleteProcessorTopology) as captured:
        _require_complete_processor_port_coverage(
            world.runtime,
            source={"id": "decoder", "type": "processor.pcm-auto-decoder"},
            target={
                "id": "dsp",
                "type": "processor.camilladsp-profile-selector",
            },
            edge_id="decoder-to-dsp",
            source_node_id=41,
            target_node_id=42,
            pairs=pairs[:-1],
            required_channels=channels,
        )

    assert captured.value.evidence["code"] == "processor-port-contract-incomplete"
    assert captured.value.evidence["missingChannels"] == ["RR"]


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_live_processor_chain_uses_allocated_stable_runtime_resources() -> None:
    owner = get_user_model().objects.create_user(username="live-processor-owner")
    source = LogicalEndpoint.objects.create(
        name="Controlled input",
        owner=owner,
        direction="input",
        selector=_selector("bluez_input.phone"),
    )
    sink = LogicalEndpoint.objects.create(
        name="Controlled output",
        owner=owner,
        direction="output",
        selector=_selector("alsa_output.usb-room"),
    )
    graph = GraphDefinition.objects.create(name="Limited processor chain", owner=owner)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={
            "schemaVersion": 1,
            "id": "graph:limited-processor-chain",
            "kind": "graph",
            "metadata": {"name": "Limited processor chain", "labels": {}},
            "parameters": [],
            "publicPorts": [],
            "conditions": [],
            "nodes": [
                {
                    "id": "source",
                    "type": "core.endpoint-reference",
                    "version": 1,
                    "configuration": {
                        "logicalEndpointId": str(source.pk),
                        "direction": "input",
                    },
                },
                {
                    "id": "decoder",
                    "type": "processor.pcm-auto-decoder",
                    "version": 1,
                    "configuration": {
                        "pcmBehavior": "bypass",
                        "encodedBehavior": "decode",
                        "unsupportedBehavior": "error",
                        "workingSampleFormat": "FLOAT32LE",
                        "workingRate": 48000,
                        "workingLayout": "7.1",
                    },
                },
                {
                    "id": "dsp",
                    "type": "processor.camilladsp-profile-selector",
                    "version": 1,
                    "configuration": {
                        "profileId": "11111111-1111-1111-1111-111111111111",
                        "profileVersion": 1,
                    },
                },
                {
                    "id": "sink",
                    "type": "core.endpoint-reference",
                    "version": 1,
                    "configuration": {
                        "logicalEndpointId": str(sink.pk),
                        "direction": "output",
                    },
                },
            ],
            "edges": [
                {
                    "id": "source-to-decoder",
                    "from": {"node": "source", "port": "output"},
                    "to": {"node": "decoder", "port": "input"},
                },
                {
                    "id": "decoder-to-dsp",
                    "from": {"node": "decoder", "port": "output"},
                    "to": {"node": "dsp", "port": "input"},
                },
                {
                    "id": "dsp-to-sink",
                    "from": {"node": "dsp", "port": "output"},
                    "to": {"node": "sink", "port": "input"},
                },
            ],
            "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
        },
    )
    activate_graph(definition=graph, revision=revision, expected_version=0)
    adapter = MemoryAdapter()
    world = _processor_chain_world()
    reconciler = MemoryLiveGraphReconciler(
        lambda: None,
        adapter=adapter,
        journal_store=TransitionJournalStore(),
        action_timeout_seconds=0.05,
        runtime_refresher=lambda: adapter.refreshed_world(world),
    )

    result = reconciler.reconcile(str(graph.pk), world)

    assert result.applied is True, result.plan.document["errors"]
    assert result.action_count == 18
    assert result.plan.document["resourceAssignments"] == {
        "decoder": {"resourceId": "decoder:0", "units": 1},
        "dsp": {"resourceId": "camilladsp:0", "units": 1},
    }
    edge_order = [
        action.command.arguments["properties"]["open-cinema.graph-edge"]
        for action in adapter.performed
    ]
    assert edge_order == [
        *("dsp-to-sink" for _channel in range(8)),
        *("decoder-to-dsp" for _channel in range(8)),
        *("source-to-decoder" for _channel in range(2)),
    ]
    by_edge = {
        action.command.arguments["properties"]["open-cinema.graph-edge"]: action
        for action in adapter.performed
    }
    assert (
        by_edge["source-to-decoder"].command.arguments["inputNodeRuntimeKey"].endswith(":node:40")
    )
    assert by_edge["decoder-to-dsp"].command.arguments["outputNodeRuntimeKey"].endswith(":node:41")
    assert by_edge["decoder-to-dsp"].command.arguments["inputNodeRuntimeKey"].endswith(":node:42")
    assert by_edge["dsp-to-sink"].command.arguments["outputNodeRuntimeKey"].endswith(":node:43")
    assert {action.command.arguments["shape"] for action in adapter.performed} == {
        "processor-internal"
    }
    phases = list(
        OrchestrationEvent.objects.filter(
            correlation_id=result.plan.correlation_id,
            event_type="processor-topology-transition",
        ).values_list("payload__phase", flat=True)
    )
    assert phases == [
        "verifying-downstream-topology",
        "downstream-topology-ready",
        "activating-programme-ingress",
        "verifying-complete-topology",
        "complete-topology-ready",
    ]

    hidden_id = f"{graph.pk}:dsp-to-sink:RR"
    adapter.hidden_from_refresh.add(hidden_id)
    adapter.extra_links = (
        LinkValue(
            id=1001,
            output_node_id=20,
            output_port_id=102,
            input_node_id=10,
            input_port_id=101,
            owner="open-cinema.orchestrator",
            desired_id="another-graph:route:FL",
            properties=FrozenDict(
                {
                    "open-cinema.owner": "open-cinema.orchestrator",
                    "open-cinema.desired-id": "another-graph:route:FL",
                }
            ),
        ),
        LinkValue(
            id=1002,
            output_node_id=20,
            output_port_id=103,
            input_node_id=10,
            input_port_id=104,
            owner=None,
            desired_id=None,
            properties=FrozenDict(),
        ),
    )
    partial_world = adapter.refreshed_world(world)
    performed_before_failure = len(adapter.performed)

    partial = reconciler.reconcile(str(graph.pk), partial_world)

    assert partial.applied is False
    assert "downstream topology did not converge" in partial.reason
    failed_actions = adapter.performed[performed_before_failure:]
    assert all(
        not (
            action.command.operation == "create-managed-link"
            and action.command.arguments["properties"]["open-cinema.graph-edge"]
            == "source-to-decoder"
        )
        for action in failed_actions
    )
    assert all(action.identity.resource_id != "another-graph:route:FL" for action in failed_actions)
    state = AppliedPlanState.objects.get(graph_definition=graph)
    assert state.status == AppliedPlanStatus.FAILED
    assert state.current_plan == result.plan
    assert state.last_error["code"] == "processor-downstream-topology-incomplete"
    assert "RR" in state.last_error["observations"]["missingChannels"]


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_disabled_graph_removes_only_its_links_and_becomes_idle() -> None:
    owner = get_user_model().objects.create_user(username="deactivated-route-owner")
    graph = GraphDefinition.objects.create(name="Disabled route", owner=owner)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={"nodes": [], "edges": []},
    )
    activate_graph(definition=graph, revision=revision, expected_version=0)
    activation = deactivate_graph(definition=graph, expected_version=1)
    assert activation is not None

    owned_id = f"{graph.pk}:programme-to-main:FL"
    other_id = "another-graph:route:FL"

    def managed_link(link_id: int, desired_id: str) -> LinkValue:
        return LinkValue(
            id=link_id,
            output_node_id=20,
            output_port_id=102,
            input_node_id=10,
            input_port_id=101,
            owner="open-cinema.orchestrator",
            desired_id=desired_id,
            properties=FrozenDict(
                {
                    "open-cinema.owner": "open-cinema.orchestrator",
                    "open-cinema.desired-id": desired_id,
                }
            ),
        )

    runtime = replace(
        _snapshot(),
        links=(managed_link(56, owned_id), managed_link(57, other_id)),
    )
    world = InMemoryWorldStore().install_runtime_snapshot(runtime)
    adapter = MemoryAdapter()
    adapter.present.update({owned_id, other_id})
    reconciler = MemoryLiveGraphReconciler(
        lambda: None,
        adapter=adapter,
        journal_store=TransitionJournalStore(),
    )

    result = reconciler.reconcile(str(graph.pk), world)

    assert result.applied is True
    assert result.action_count == 1
    assert result.plan.document["kind"] == "graph-deactivation"
    assert adapter.performed[0].command.operation == "remove-managed-link"
    assert owned_id not in adapter.present
    assert other_id in adapter.present
    state = AppliedPlanState.objects.get(graph_definition=graph)
    assert state.status == AppliedPlanStatus.IDLE
    assert state.current_plan is None
    journal = TransitionJournal.objects.get(graph_definition=graph)
    assert journal.status == TransitionStatus.SUCCEEDED
    assert journal.entries[0]["phase"] == "cleanup"
