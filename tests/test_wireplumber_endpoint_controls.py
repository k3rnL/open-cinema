from dataclasses import replace

import pytest
from wyreplumber.runtime import AudioPropertiesValue, ParameterValue

from core.orchestration.driver_actions import (
    ActionFailureClassification,
    DriverActionError,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.wireplumber_driver import (
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_endpoint_mute_action,
    build_endpoint_volume_action,
    register_endpoint_audio_controls,
)
from tests.test_endpoint_inventory_mapping import _snapshot
from tests.test_wireplumber_driver import _confirmed_outcome


def _runtime(*, permissions="rw", generation=3, sink_id=10):
    snapshot = _snapshot(generation=generation, sink_id=sink_id)
    return replace(
        snapshot,
        parameters=(
            ParameterValue(
                "node",
                sink_id,
                "Props",
                permissions,
                (AudioPropertiesValue(volume=0.6, mute=False),),
            ),
        ),
    )


def _candidate(runtime):
    return next(
        item
        for item in map_runtime_endpoints(runtime).candidates
        if item.name == "alsa_output.usb-room"
    )


def _adapter(runtime, *, volume_control=None, mute_control=None):
    registry = WirePlumberControlRegistry()
    register_endpoint_audio_controls(
        registry,
        set_volume=volume_control or (lambda *_args, **_kwargs: _confirmed_outcome()),
        set_mute=mute_control or (lambda *_args, **_kwargs: _confirmed_outcome()),
    )
    return WirePlumberDriverAdapter(
        lambda: "connection",
        registry=registry,
        snapshot_capture=lambda _connection: runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )


@pytest.mark.parametrize(
    ("kind", "value", "operation", "argument"),
    (
        ("volume", 0.25, "set-endpoint-volume", "volume"),
        ("mute", True, "set-endpoint-mute", "mute"),
    ),
)
def test_logical_endpoint_control_resolves_current_node_and_confirms(
    kind,
    value,
    operation,
    argument,
) -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    calls = []

    def control(connection, **kwargs):
        calls.append((connection, kwargs))
        return _confirmed_outcome()

    adapter = _adapter(
        runtime,
        volume_control=control if kind == "volume" else None,
        mute_control=control if kind == "mute" else None,
    )
    builder = build_endpoint_volume_action if kind == "volume" else build_endpoint_mute_action
    action = builder(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        **{argument: value},
        intent_scope="plan:endpoint-control",
        timeout_seconds=1.5,
    )

    outcome = adapter.perform(action)

    assert action.identity.resource_id == "endpoint:main-speakers"
    assert action.command.operation == operation
    assert action.command.arguments["runtimeKey"] == "runtime:3:node:10"
    assert calls == [
        (
            "connection",
            {
                "node_id": 10,
                "expected_generation": 3,
                "expected_sequence": 9,
                "timeout": 1.5,
                "request_id": action.idempotency_key,
                argument: value,
            },
        )
    ]
    assert outcome["status"] == "confirmed"


def test_observation_reports_values_and_writable_capabilities_by_logical_id() -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)

    facts = _adapter(runtime).observe_endpoint_controls(
        "endpoint:main-speakers",
        candidate.runtime_key,
    )

    assert facts == {
        "endpoint.endpoint:main-speakers.runtimeKey": "runtime:3:node:10",
        "endpoint.endpoint:main-speakers.volume": 0.6,
        "endpoint.endpoint:main-speakers.mute": False,
        "endpoint.endpoint:main-speakers.volumeSupported": True,
        "endpoint.endpoint:main-speakers.muteSupported": True,
        "runtime.generation": 3,
        "runtime.sequence": 9,
    }


def test_read_only_control_is_permanent_and_desired_action_remains_unchanged() -> None:
    runtime = _runtime(permissions="r")
    candidate = _candidate(runtime)
    action = build_endpoint_mute_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        mute=True,
        intent_scope="plan:read-only",
        timeout_seconds=1,
    )
    original = action.to_document()

    with pytest.raises(DriverActionError) as caught:
        _adapter(runtime).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.PERMANENT
    assert caught.value.failure.code == "wireplumber:endpoint-control-read-only"
    assert action.to_document() == original


def test_disappeared_runtime_key_requires_fresh_resolution() -> None:
    previous = _candidate(_runtime())
    restarted = _runtime(generation=4, sink_id=110)
    action = build_endpoint_volume_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=previous,
        volume=0.3,
        intent_scope="plan:stale",
        timeout_seconds=1,
    )

    with pytest.raises(DriverActionError) as caught:
        _adapter(restarted).perform(action)

    assert caught.value.failure.classification is (ActionFailureClassification.STALE_PRECONDITION)
    assert caught.value.failure.code == "wireplumber:endpoint-runtime-key-stale"


@pytest.mark.parametrize("volume", (-0.01, 1.01, True, "0.5"))
def test_volume_action_rejects_values_outside_normalized_range(volume) -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        build_endpoint_volume_action(
            logical_endpoint_id="endpoint:main-speakers",
            candidate=_candidate(_runtime()),
            volume=volume,
            intent_scope="plan:invalid-volume",
            timeout_seconds=1,
        )


def test_mute_action_requires_a_boolean() -> None:
    with pytest.raises(TypeError, match="boolean"):
        build_endpoint_mute_action(
            logical_endpoint_id="endpoint:main-speakers",
            candidate=_candidate(_runtime()),
            mute=1,
            intent_scope="plan:invalid-mute",
            timeout_seconds=1,
        )
