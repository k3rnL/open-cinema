from dataclasses import replace

import pytest
from wyreplumber.runtime import (
    AudioPropertiesValue,
    ConnectionHealthValue,
    ConnectionState,
    DefaultTargetValue,
    DefaultsValue,
    FrozenDict,
    LinkValue,
    MetadataEntryValue,
    MetadataValue,
    MutationOperation,
    NodeState,
    NodeValue,
    ParameterValue,
    PortDirection,
    PortValue,
    RuntimeSnapshot,
)

from core.orchestration.action_planning import evaluate_action_verification
from core.orchestration.driver_actions import (
    ActionFailureClassification,
    DriverActionError,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.wireplumber_driver import (
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_default_node_action,
    build_endpoint_mute_action,
    build_endpoint_volume_action,
    build_stream_target_action,
    register_endpoint_audio_controls,
    register_routing_controls,
)
from tests.test_wireplumber_driver import _confirmed_outcome


class ContractRuntime:
    """Mutable contract fake below the detached WirePlumber adapter boundary."""

    def __init__(self, *, generation=1, main_id=10):
        self.main_id = main_id
        self.calls = []
        self.snapshot = self._base_snapshot(generation, main_id)

    @staticmethod
    def _base_snapshot(generation, main_id):
        return RuntimeSnapshot(
            generation=generation,
            sequence=1,
            captured_at="2026-08-22T12:00:00Z",
            health=ConnectionHealthValue(ConnectionState.CONNECTED, generation),
            nodes=(
                NodeValue(
                    id=main_id,
                    name="alsa_output.main-speakers",
                    description="Main speakers",
                    media_class="Audio/Sink",
                    state=NodeState.RUNNING,
                    input_port_ids=(main_id * 10 + 1,),
                    properties=FrozenDict(
                        {
                            "node.name": "alsa_output.main-speakers",
                            "device.serial": "MAIN-SPEAKERS",
                        }
                    ),
                ),
                NodeValue(
                    id=20,
                    name="alsa_input.tv",
                    description="TV",
                    media_class="Audio/Source",
                    state=NodeState.RUNNING,
                    output_port_ids=(201,),
                    properties=FrozenDict(
                        {"node.name": "alsa_input.tv", "device.serial": "TV-SPDIF"}
                    ),
                ),
                NodeValue(
                    id=31,
                    name="decoder-capture",
                    media_class="Stream/Input/Audio",
                ),
                NodeValue(
                    id=32,
                    name="camilladsp-output",
                    media_class="Stream/Output/Audio",
                ),
                NodeValue(
                    id=40,
                    name="external-player",
                    media_class="Stream/Output/Audio",
                    output_port_ids=(401,),
                ),
            ),
            ports=(
                PortValue(
                    id=main_id * 10 + 1,
                    node_id=main_id,
                    direction=PortDirection.INPUT,
                ),
                PortValue(id=201, node_id=20, direction=PortDirection.OUTPUT),
                PortValue(id=401, node_id=40, direction=PortDirection.OUTPUT),
            ),
            links=(
                LinkValue(
                    id=90,
                    output_node_id=40,
                    output_port_id=401,
                    input_node_id=main_id,
                    input_port_id=main_id * 10 + 1,
                    owner=None,
                    desired_id=None,
                ),
            ),
            metadata=(
                MetadataValue(
                    id=50,
                    name="default",
                    entries=(
                        MetadataEntryValue(
                            subject=31,
                            key="target.object",
                            type_name="Spa:String",
                            value="alsa_input.tv",
                        ),
                    ),
                ),
            ),
            parameters=(
                ParameterValue(
                    "node",
                    main_id,
                    "Props",
                    "rw",
                    (AudioPropertiesValue(volume=0.7, mute=False),),
                ),
                ParameterValue(
                    "node",
                    main_id,
                    "Mixer",
                    "rw",
                    (AudioPropertiesValue(volume=0.7, mute=False),),
                ),
            ),
            defaults=DefaultsValue(
                metadata_id=50,
                audio_sink=DefaultTargetValue(
                    "Audio/Sink",
                    "alsa_output.main-speakers",
                    main_id,
                ),
            ),
        )

    def _advance(self, **changes):
        self.snapshot = replace(
            self.snapshot,
            sequence=self.snapshot.sequence + 1,
            unresolved_relationships=(),
            **changes,
        )

    def _outcome(self, request_id, operation):
        base = _confirmed_outcome()
        confirmations = tuple(
            replace(
                confirmation,
                generation=self.snapshot.generation,
                sequence=self.snapshot.sequence,
            )
            for confirmation in base.confirmations
        )
        return replace(
            base,
            request_id=request_id,
            generation=self.snapshot.generation,
            operation=operation,
            confirmations=confirmations,
        )

    def add_headset(self):
        self._advance(
            nodes=(
                *self.snapshot.nodes,
                NodeValue(
                    id=11,
                    name="bluez_output.headset",
                    description="Headset",
                    media_class="Audio/Sink",
                    input_port_ids=(111,),
                    properties=FrozenDict(
                        {
                            "node.name": "bluez_output.headset",
                            "api.bluez5.address": "11:22:33:44:55:66",
                        }
                    ),
                ),
            ),
            ports=(
                *self.snapshot.ports,
                PortValue(id=111, node_id=11, direction=PortDirection.INPUT),
            ),
            parameters=(
                *self.snapshot.parameters,
                ParameterValue(
                    "node",
                    11,
                    "Props",
                    "rw",
                    (AudioPropertiesValue(volume=0.5, mute=False),),
                ),
                ParameterValue(
                    "node",
                    11,
                    "Mixer",
                    "rw",
                    (AudioPropertiesValue(volume=0.5, mute=False),),
                ),
            ),
        )

    def remove_headset(self):
        self._advance(
            nodes=tuple(node for node in self.snapshot.nodes if node.id != 11),
            ports=tuple(port for port in self.snapshot.ports if port.node_id != 11),
            parameters=tuple(
                parameter
                for parameter in self.snapshot.parameters
                if not (parameter.owner_type == "node" and parameter.owner_id == 11)
            ),
        )

    def add_bluetooth_source(self):
        self._advance(
            nodes=(
                *self.snapshot.nodes,
                NodeValue(
                    id=21,
                    name="bluez_input.phone",
                    description="Phone",
                    media_class="Audio/Source",
                    state=NodeState.RUNNING,
                    output_port_ids=(211,),
                    properties=FrozenDict(
                        {
                            "node.name": "bluez_input.phone",
                            "api.bluez5.address": "AA:BB:CC:DD:EE:FF",
                        }
                    ),
                ),
            ),
            ports=(
                *self.snapshot.ports,
                PortValue(id=211, node_id=21, direction=PortDirection.OUTPUT),
            ),
        )

    def restart(self):
        restarted = self._base_snapshot(self.snapshot.generation + 1, 110)
        self.main_id = 110
        self.snapshot = restarted

    def set_default(self, _connection, **kwargs):
        self.calls.append(("set-default", kwargs))
        node = self.snapshot.nodes_by_id[kwargs["node_id"]]
        self._advance(
            defaults=replace(
                self.snapshot.defaults,
                audio_sink=DefaultTargetValue(
                    "Audio/Sink",
                    node.name,
                    node.id,
                ),
            )
        )
        return self._outcome(kwargs["request_id"], MutationOperation.SET_METADATA)

    def clear_default(self, _connection, **kwargs):
        self.calls.append(("clear-default", kwargs))
        self._advance(defaults=replace(self.snapshot.defaults, audio_sink=None))
        return self._outcome(kwargs["request_id"], MutationOperation.CLEAR_METADATA)

    def set_stream(self, _connection, **kwargs):
        self.calls.append(("set-stream", kwargs))
        stream_id = kwargs["stream_node_id"]
        target = self.snapshot.nodes_by_id[kwargs["target_node_id"]]
        metadata = self.snapshot.metadata_by_id[50]
        retained = tuple(
            entry
            for entry in metadata.entries
            if not (entry.subject == stream_id and entry.key == "target.object")
        )
        entry = MetadataEntryValue(
            stream_id,
            "target.object",
            "Spa:String",
            target.name,
        )
        self._advance(metadata=(replace(metadata, entries=(*retained, entry)),))
        return self._outcome(kwargs["request_id"], MutationOperation.SET_METADATA)

    def clear_stream(self, _connection, **kwargs):
        self.calls.append(("clear-stream", kwargs))
        stream_id = kwargs["stream_node_id"]
        metadata = self.snapshot.metadata_by_id[50]
        retained = tuple(
            entry
            for entry in metadata.entries
            if not (entry.subject == stream_id and entry.key == "target.object")
        )
        self._advance(metadata=(replace(metadata, entries=retained),))
        return self._outcome(kwargs["request_id"], MutationOperation.CLEAR_METADATA)

    def set_volume(self, _connection, **kwargs):
        return self._set_audio_property("volume", kwargs)

    def set_mute(self, _connection, **kwargs):
        return self._set_audio_property("mute", kwargs)

    def _set_audio_property(self, field, kwargs):
        self.calls.append((f"set-{field}", kwargs))
        node_id = kwargs["node_id"]
        parameter = self.snapshot.parameters_by_key[("node", node_id, "Mixer")]
        current = parameter.values[0]
        updated = replace(current, **{field: kwargs[field]})
        parameters = tuple(
            replace(item, values=(updated,)) if item is parameter else item
            for item in self.snapshot.parameters
        )
        self._advance(parameters=parameters)
        return self._outcome(kwargs["request_id"], MutationOperation.SET_NODE_MIXER)


def _adapter(runtime):
    registry = WirePlumberControlRegistry()
    register_routing_controls(
        registry,
        set_default=runtime.set_default,
        clear_default=runtime.clear_default,
        set_stream=runtime.set_stream,
        clear_stream=runtime.clear_stream,
    )
    register_endpoint_audio_controls(
        registry,
        set_volume=runtime.set_volume,
        set_mute=runtime.set_mute,
    )
    return WirePlumberDriverAdapter(
        lambda: runtime,
        registry=registry,
        snapshot_capture=lambda connection: connection.snapshot,
        contract_checker=lambda _minimum, _maximum: None,
    )


def _candidate(runtime, name):
    return next(
        item for item in map_runtime_endpoints(runtime.snapshot).candidates if item.name == name
    )


def _verified(action, facts):
    satisfied, reasons = evaluate_action_verification(action, facts)
    assert satisfied, reasons


def test_headset_connect_and_disconnect_changes_default_without_claiming_external_links() -> None:
    runtime = ContractRuntime()
    adapter = _adapter(runtime)
    main = _candidate(runtime, "alsa_output.main-speakers")
    original_external = runtime.snapshot.links[0]

    runtime.add_headset()
    headset = _candidate(runtime, "bluez_output.headset")
    connect_action = build_default_node_action(
        target_logical_endpoint_id="endpoint:headset",
        candidate=headset,
        previous_candidate=main,
        intent_scope="canonical:headset-connect",
        timeout_seconds=1,
    )
    adapter.perform(connect_action)
    _verified(connect_action, adapter.observe_default_node("Audio/Sink"))

    runtime.remove_headset()
    main = _candidate(runtime, "alsa_output.main-speakers")
    disconnect_action = build_default_node_action(
        target_logical_endpoint_id="endpoint:main-speakers",
        candidate=main,
        previous_candidate=None,
        intent_scope="canonical:headset-disconnect",
        timeout_seconds=1,
    )
    adapter.perform(disconnect_action)
    _verified(disconnect_action, adapter.observe_default_node("Audio/Sink"))

    assert runtime.snapshot.links == (original_external,)
    assert runtime.snapshot.links[0].owner is None
    assert runtime.snapshot.nodes_by_id[40].name == "external-player"


def test_bluetooth_arrival_moves_only_the_managed_capture_stream() -> None:
    runtime = ContractRuntime()
    adapter = _adapter(runtime)
    tv = _candidate(runtime, "alsa_input.tv")

    runtime.add_bluetooth_source()
    bluetooth = _candidate(runtime, "bluez_input.phone")
    action = build_stream_target_action(
        logical_stream_id="stream:decoder-capture",
        stream_runtime_key="runtime:1:node:31",
        target_logical_endpoint_id="endpoint:bluetooth-programme",
        target_candidate=bluetooth,
        previous_target_candidate=tv,
        runtime_generation=1,
        intent_scope="canonical:bluetooth-arrival",
        timeout_seconds=1,
    )

    adapter.perform(action)
    _verified(
        action,
        adapter.observe_stream_target(
            "stream:decoder-capture",
            "runtime:1:node:31",
        ),
    )
    external = adapter.observe_stream_target(
        "stream:external-player",
        "runtime:1:node:40",
    )

    assert external["routing.stream.stream:external-player.targetConfiguredValue"] is None
    assert runtime.snapshot.links[0].owner is None


def test_volume_and_mute_converge_through_confirmed_logical_endpoint_actions() -> None:
    runtime = ContractRuntime()
    adapter = _adapter(runtime)
    candidate = _candidate(runtime, "alsa_output.main-speakers")
    volume = build_endpoint_volume_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        volume=0.35,
        intent_scope="canonical:volume",
        timeout_seconds=1,
    )

    adapter.perform(volume)
    _verified(
        volume,
        adapter.observe_endpoint_controls(
            "endpoint:main-speakers",
            candidate.runtime_key,
        ),
    )

    candidate = _candidate(runtime, "alsa_output.main-speakers")
    mute = build_endpoint_mute_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        mute=True,
        intent_scope="canonical:mute",
        timeout_seconds=1,
    )
    adapter.perform(mute)
    facts = adapter.observe_endpoint_controls(
        "endpoint:main-speakers",
        candidate.runtime_key,
    )
    _verified(mute, facts)

    assert facts["endpoint.endpoint:main-speakers.volume"] == 0.35
    assert facts["endpoint.endpoint:main-speakers.mute"] is True


def test_pipewire_restart_fences_old_action_then_converges_with_new_runtime_key() -> None:
    runtime = ContractRuntime()
    adapter = _adapter(runtime)
    old_candidate = _candidate(runtime, "alsa_output.main-speakers")
    stale = build_endpoint_volume_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=old_candidate,
        volume=0.4,
        intent_scope="canonical:before-restart",
        timeout_seconds=1,
    )

    runtime.restart()
    with pytest.raises(DriverActionError) as caught:
        adapter.perform(stale)

    assert caught.value.failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert runtime.calls == []

    new_candidate = _candidate(runtime, "alsa_output.main-speakers")
    replacement = build_endpoint_volume_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=new_candidate,
        volume=0.4,
        intent_scope="canonical:after-restart",
        timeout_seconds=1,
    )
    adapter.perform(replacement)
    _verified(
        replacement,
        adapter.observe_endpoint_controls(
            "endpoint:main-speakers",
            new_candidate.runtime_key,
        ),
    )

    assert old_candidate.runtime_key == "runtime:1:node:10"
    assert new_candidate.runtime_key == "runtime:2:node:110"
    assert [name for name, _kwargs in runtime.calls] == ["set-volume"]
