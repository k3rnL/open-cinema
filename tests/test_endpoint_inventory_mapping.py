import json
from dataclasses import FrozenInstanceError, replace

import pytest
from wyreplumber.runtime import (
    Availability,
    ConnectionHealthValue,
    ConnectionState,
    DefaultTargetValue,
    DefaultsValue,
    DeviceValue,
    FrozenDict,
    LinkValue,
    NodeState,
    NodeValue,
    PortDirection,
    PortValue,
    ProfileValue,
    RouteValue,
    RuntimeSnapshot,
)

from core.orchestration.endpoint_inventory import (
    EndpointDirection,
    map_runtime_endpoints,
)


def _snapshot(*, generation=3, source_id=20, sink_id=10):
    return RuntimeSnapshot(
        generation=generation,
        sequence=9,
        captured_at="2026-08-22T12:00:00+00:00",
        health=ConnectionHealthValue(ConnectionState.CONNECTED, generation),
        devices=(
            DeviceValue(
                id=1,
                name="alsa_card.usb-room",
                description="USB room interface",
                properties=FrozenDict(
                    {"device.serial": "ROOM-123", "api.alsa.path": "hw:Room"}
                ),
                profile_ids=(2,),
                route_ids=(4,),
            ),
        ),
        nodes=(
            NodeValue(
                id=sink_id,
                device_id=1,
                name="alsa_output.usb-room",
                description="Main speakers",
                media_class="Audio/Sink",
                state=NodeState.RUNNING,
                input_port_ids=(101,),
                properties=FrozenDict({"node.name": "alsa_output.usb-room"}),
            ),
            NodeValue(
                id=source_id,
                name="bluez_input.phone",
                description="Phone",
                media_class="Audio/Source",
                state=NodeState.IDLE,
                output_port_ids=(102,),
                properties=FrozenDict({"api.bluez5.address": "AA:BB:CC:DD:EE:FF"}),
            ),
            NodeValue(
                id=30,
                name="application-stream",
                media_class="Stream/Output/Audio",
            ),
        ),
        ports=(
            PortValue(
                id=101,
                node_id=sink_id,
                direction=PortDirection.INPUT,
                name="playback_FL",
                channel="FL",
            ),
            PortValue(
                id=102,
                node_id=source_id,
                direction=PortDirection.OUTPUT,
                name="capture_FL",
                channel="FL",
            ),
        ),
        links=(
            LinkValue(
                id=55,
                output_node_id=source_id,
                output_port_id=102,
                input_node_id=sink_id,
                input_port_id=101,
            ),
        ),
        profiles=(
            ProfileValue(
                device_id=1,
                index=2,
                name="output:analog-stereo",
                priority=100,
                available=Availability.YES,
                active=True,
            ),
        ),
        routes=(
            RouteValue(
                device_id=1,
                index=4,
                direction=PortDirection.OUTPUT,
                name="analog-output-speaker",
                priority=200,
                available=Availability.YES,
                active=True,
                profile_ids=(2,),
                volume=0.6,
                mute=False,
            ),
        ),
        defaults=DefaultsValue(
            audio_sink=DefaultTargetValue(
                media_class="Audio/Sink",
                configured_name="alsa_output.usb-room",
                resolved_node_id=sink_id,
            )
        ),
    )


def test_snapshot_maps_only_endpoint_nodes_and_joins_runtime_context() -> None:
    inventory = map_runtime_endpoints(_snapshot())

    assert inventory.generation == 3
    assert inventory.sequence == 9
    assert len(inventory.candidates) == 2
    source, sink = inventory.candidates
    assert source.direction == EndpointDirection.INPUT
    assert source.name == "bluez_input.phone"
    assert source.is_default is False
    assert source.is_linked is True
    assert sink.direction == EndpointDirection.OUTPUT
    assert sink.is_default is True
    assert sink.has_active_signal is True
    assert sink.routes[0].name == "analog-output-speaker"
    assert sink.routes[0].profile_names == ("output:analog-stereo",)
    assert sink.profiles[0].active is True
    assert sink.ports[0].channel == "FL"


def test_managed_plugin_playback_stream_is_an_input_endpoint() -> None:
    snapshot = _snapshot()
    stream = replace(
        snapshot.nodes[-1],
        properties=FrozenDict(
            {
                "node.name": "open-cinema-librespot-test",
                "open-cinema.plugin.id": "open-cinema.librespot",
                "open-cinema.instance.id": "test-instance",
                "open-cinema.generation": "generation-1",
            }
        ),
    )

    inventory = map_runtime_endpoints(replace(snapshot, nodes=(*snapshot.nodes[:-1], stream)))

    managed = next(item for item in inventory.candidates if item.name == "application-stream")
    assert managed.direction is EndpointDirection.INPUT
    assert managed.selector_facts()["nodeProperties"] == {
        "node.name": "open-cinema-librespot-test",
        "open-cinema.plugin.id": "open-cinema.librespot",
        "open-cinema.instance.id": "test-instance",
        "open-cinema.generation": "generation-1",
    }


def test_runtime_ids_are_ephemeral_and_absent_from_selector_facts() -> None:
    before = map_runtime_endpoints(_snapshot(source_id=20, sink_id=10))
    after = map_runtime_endpoints(_snapshot(generation=4, source_id=220, sink_id=110))
    before_by_name = {candidate.name: candidate for candidate in before.candidates}
    after_by_name = {candidate.name: candidate for candidate in after.candidates}

    assert before_by_name["bluez_input.phone"].runtime_key != after_by_name[
        "bluez_input.phone"
    ].runtime_key
    assert before_by_name["bluez_input.phone"].selector_facts() == after_by_name[
        "bluez_input.phone"
    ].selector_facts()
    facts = json.dumps(before_by_name["alsa_output.usb-room"].selector_facts())
    assert "nodeId" not in facts
    assert "deviceId" not in facts
    assert '"id"' not in facts


def test_candidates_and_nested_properties_are_immutable() -> None:
    candidate = map_runtime_endpoints(_snapshot()).candidates[0]

    with pytest.raises(FrozenInstanceError):
        candidate.name = "changed"
    with pytest.raises(TypeError):
        candidate.node_properties["new"] = "value"


def test_projection_labels_runtime_key_as_ephemeral_and_hides_raw_ids() -> None:
    projection = map_runtime_endpoints(_snapshot()).candidates[1].projection_document()

    assert projection["runtimeKey"].startswith("runtime:3:node:")
    assert "nodeId" not in projection
    assert "deviceId" not in projection


def test_managed_adapter_projection_is_bindable_and_distinct_from_hardware() -> None:
    candidate = map_runtime_endpoints(_snapshot()).candidates[1]
    candidate = replace(
        candidate,
        node_properties=FrozenDict(
            {
                **candidate.node_properties.to_dict(),
                "open-cinema.owner": "open-cinema.adapter-supervisor.v1",
                "open-cinema.adapter.id": "adapter-1",
                "open-cinema.adapter.kind": "roc-sender",
                "open-cinema.adapter.direction": "output",
            }
        ),
    )

    projection = candidate.projection_document()

    assert projection["origin"] == "managed-adapter"
    assert projection["managed"] is True
    assert projection["managedAdapter"]["id"] == "adapter-1"
    assert candidate.selector_facts()["nodeProperties"]["open-cinema.adapter.id"] == "adapter-1"


def test_processor_resources_are_not_endpoint_candidates() -> None:
    snapshot = _snapshot()
    processor = NodeValue(
        id=40,
        name="opencinema.camilladsp.0.input",
        description="Open Cinema CamillaDSP 0 Input",
        media_class="Audio/Sink",
        properties=FrozenDict(
            {
                "node.name": "opencinema.camilladsp.0.input",
                "open-cinema.endpoint-id": "processor:camilladsp:0:input",
                "opencinema.processor.kind": "camilladsp",
                "opencinema.processor.instance": "0",
                "opencinema.processor.port": "input",
            }
        ),
    )

    inventory = map_runtime_endpoints(
        replace(snapshot, nodes=(*snapshot.nodes, processor))
    )

    assert {candidate.name for candidate in inventory.candidates} == {
        "alsa_output.usb-room",
        "bluez_input.phone",
    }
