from dataclasses import replace

import pytest
from wyreplumber.runtime import (
    DefaultsValue,
    DefaultTargetValue,
    FrozenDict,
    MetadataEntryValue,
    MetadataValue,
)

from core.orchestration.driver_actions import (
    ActionFailureClassification,
    DriverActionError,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.wireplumber_driver import (
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_clear_default_node_action,
    build_clear_stream_target_action,
    build_default_node_action,
    build_stream_target_action,
    register_routing_controls,
)
from tests.test_endpoint_inventory_mapping import _snapshot
from tests.test_wireplumber_driver import _confirmed_outcome


def _candidate(runtime):
    return next(
        item
        for item in map_runtime_endpoints(runtime).candidates
        if item.name == "alsa_output.usb-room"
    )


def _runtime(*, target_value=None, target_type="Spa:String"):
    snapshot = _snapshot()
    entries = ()
    if target_value is not None:
        entries = (
            MetadataEntryValue(
                subject=30,
                key="target.object",
                type_name=target_type,
                value=target_value,
            ),
        )
    return replace(
        snapshot,
        metadata=(MetadataValue(50, "default", FrozenDict(), entries),),
        defaults=replace(snapshot.defaults, metadata_id=50),
    )


def _adapter(runtime, calls):
    def control(name):
        def invoke(connection, **kwargs):
            calls.append((name, connection, kwargs))
            return _confirmed_outcome()

        return invoke

    registry = WirePlumberControlRegistry()
    register_routing_controls(
        registry,
        set_default=control("set-default"),
        clear_default=control("clear-default"),
        set_stream=control("set-stream"),
        clear_stream=control("clear-stream"),
    )
    return WirePlumberDriverAdapter(
        lambda: "connection",
        registry=registry,
        snapshot_capture=lambda _connection: runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )


def test_default_node_action_uses_configured_default_metadata_without_links() -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    calls = []
    action = build_default_node_action(
        target_logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        previous_candidate=None,
        intent_scope="plan:default",
        timeout_seconds=1.5,
    )

    outcome = _adapter(runtime, calls).perform(action)

    assert calls == [
        (
            "set-default",
            "connection",
            {
                "node_id": 10,
                "media_class": "Audio/Sink",
                "expected_generation": 3,
                "expected_sequence": 9,
                "timeout": 1.5,
                "request_id": action.idempotency_key,
            },
        )
    ]
    assert action.metadata["routingMechanism"] == "wireplumber-default-metadata"
    assert action.metadata["explicitLinks"] is False
    assert action.recovery.inverse.command.operation == "clear-default-node"
    assert action.recovery.inverse.verification[0].subject.endswith(".configuredName")
    assert outcome["status"] == "confirmed"


def test_clear_default_node_restores_previous_logical_endpoint() -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    calls = []
    action = build_clear_default_node_action(
        media_class="Audio/Sink",
        previous_logical_endpoint_id="endpoint:main-speakers",
        previous_candidate=candidate,
        intent_scope="plan:clear-default",
        timeout_seconds=2,
    )

    _adapter(runtime, calls).perform(action)

    assert calls[0][0] == "clear-default"
    assert calls[0][2]["media_class"] == "Audio/Sink"
    assert action.recovery.inverse.command.operation == "set-default-node"
    assert action.recovery.inverse.command.arguments["targetRuntimeKey"] == candidate.runtime_key


def test_default_observation_exposes_detached_resolved_target() -> None:
    facts = _adapter(_runtime(), []).observe_default_node("Audio/Sink")

    assert facts == {
        "routing.default.audio-sink.runtimeKey": "runtime:3:node:10",
        "routing.default.audio-sink.configuredName": "alsa_output.usb-room",
        "runtime.generation": 3,
        "runtime.sequence": 9,
    }


def test_stream_target_action_resolves_both_generation_scoped_nodes() -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    calls = []
    action = build_stream_target_action(
        logical_stream_id="stream:programme",
        stream_runtime_key="runtime:3:node:30",
        target_logical_endpoint_id="endpoint:main-speakers",
        target_candidate=candidate,
        previous_target_candidate=None,
        runtime_generation=3,
        intent_scope="plan:target",
        timeout_seconds=1,
    )

    _adapter(runtime, calls).perform(action)

    assert calls == [
        (
            "set-stream",
            "connection",
            {
                "target_node_id": 10,
                "stream_node_id": 30,
                "expected_generation": 3,
                "expected_sequence": 9,
                "timeout": 1.0,
                "request_id": action.idempotency_key,
            },
        )
    ]
    assert action.metadata["routingMechanism"] == "wireplumber-stream-target-metadata"
    assert action.metadata["explicitLinks"] is False
    assert action.recovery.inverse.command.operation == "clear-stream-target"
    assert action.verification[0].subject.endswith(".targetRuntimeKey")
    assert action.recovery.inverse.verification[0].subject.endswith(".targetConfiguredValue")


def test_clear_stream_target_restores_previous_target() -> None:
    runtime = _runtime(target_value="alsa_output.usb-room")
    candidate = _candidate(runtime)
    calls = []
    action = build_clear_stream_target_action(
        logical_stream_id="stream:programme",
        stream_runtime_key="runtime:3:node:30",
        previous_target_candidate=candidate,
        runtime_generation=3,
        intent_scope="plan:follow-default",
        timeout_seconds=1,
    )

    _adapter(runtime, calls).perform(action)

    assert calls[0][0] == "clear-stream"
    assert calls[0][2]["stream_node_id"] == 30
    assert action.verification[0].subject.endswith(".targetConfiguredValue")
    assert action.recovery.inverse.command.operation == "set-stream-target"


@pytest.mark.parametrize(
    ("target_value", "target_type"),
    (("alsa_output.usb-room", "Spa:String"), ("4242", "Spa:Id")),
)
def test_stream_target_observation_resolves_name_or_serial(target_value, target_type) -> None:
    runtime = _runtime(target_value=target_value, target_type=target_type)
    if target_type == "Spa:Id":
        sink = replace(
            runtime.nodes_by_id[10],
            properties=FrozenDict({"node.name": "alsa_output.usb-room", "object.serial": 4242}),
        )
        runtime = replace(
            runtime,
            nodes=(sink, *tuple(node for node in runtime.nodes if node.id != 10)),
        )

    facts = _adapter(runtime, []).observe_stream_target(
        "stream:programme",
        "runtime:3:node:30",
    )

    assert facts["routing.stream.stream:programme.targetRuntimeKey"] == "runtime:3:node:10"
    assert facts["routing.stream.stream:programme.targetConfiguredValue"] == target_value


def test_stale_stream_runtime_key_requests_fresh_resolution() -> None:
    runtime = _runtime()
    action = build_stream_target_action(
        logical_stream_id="stream:programme",
        stream_runtime_key="runtime:2:node:30",
        target_logical_endpoint_id="endpoint:main-speakers",
        target_candidate=_candidate(runtime),
        previous_target_candidate=None,
        runtime_generation=3,
        intent_scope="plan:stale-stream",
        timeout_seconds=1,
    )

    with pytest.raises(DriverActionError) as caught:
        _adapter(runtime, []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert caught.value.failure.code == "wireplumber:routing-runtime-key-stale"


def test_default_observation_handles_no_configured_target() -> None:
    runtime = replace(
        _runtime(),
        defaults=DefaultsValue(metadata_id=50),
    )

    facts = _adapter(runtime, []).observe_default_node("Audio/Sink")

    assert facts["routing.default.audio-sink.runtimeKey"] is None
    assert facts["routing.default.audio-sink.configuredName"] is None


def test_unresolved_default_is_not_mistaken_for_cleared_metadata() -> None:
    runtime = replace(
        _runtime(),
        defaults=DefaultsValue(
            metadata_id=50,
            audio_sink=DefaultTargetValue(
                media_class="Audio/Sink",
                configured_name="temporarily-missing-sink",
                resolved_node_id=None,
            ),
        ),
    )

    facts = _adapter(runtime, []).observe_default_node("Audio/Sink")

    assert facts["routing.default.audio-sink.runtimeKey"] is None
    assert facts["routing.default.audio-sink.configuredName"] == "temporarily-missing-sink"


def test_unresolved_stream_target_is_not_mistaken_for_cleared_metadata() -> None:
    facts = _adapter(
        _runtime(target_value="temporarily-missing-sink"),
        [],
    ).observe_stream_target("stream:programme", "runtime:3:node:30")

    assert facts["routing.stream.stream:programme.targetRuntimeKey"] is None
    assert (
        facts["routing.stream.stream:programme.targetConfiguredValue"] == "temporarily-missing-sink"
    )
