from dataclasses import replace

import pytest
from wyreplumber.runtime import Availability, FrozenDict, ProfileValue, RouteValue

from core.orchestration.driver_actions import (
    ActionFailureClassification,
    DriverActionError,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.wireplumber_driver import (
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_endpoint_profile_action,
    build_endpoint_route_action,
    register_endpoint_configuration_controls,
)
from tests.test_endpoint_inventory_mapping import _snapshot
from tests.test_wireplumber_driver import _confirmed_outcome


def _runtime(*, generation=3, sink_id=10, selected=False):
    snapshot = _snapshot(generation=generation, sink_id=sink_id)
    previous_profile = replace(snapshot.profiles[0], active=not selected)
    target_profile = ProfileValue(
        device_id=1,
        index=3,
        name="output:hdmi-stereo",
        priority=200,
        available=Availability.YES,
        active=selected,
    )
    previous_route = replace(
        snapshot.routes[0],
        active=not selected,
        properties=FrozenDict({"spa_device_index": 0}),
    )
    target_route = RouteValue(
        device_id=1,
        index=5,
        direction=previous_route.direction,
        name="hdmi-output",
        priority=300,
        available=Availability.YES,
        active=selected,
        profile_ids=(3,),
        properties=FrozenDict({"spa_device_index": 1}),
    )
    return replace(
        snapshot,
        profiles=(previous_profile, target_profile),
        routes=(previous_route, target_route),
    )


def _candidate(runtime):
    return next(
        item
        for item in map_runtime_endpoints(runtime).candidates
        if item.name == "alsa_output.usb-room"
    )


def _adapter(runtime, calls):
    def control(kind):
        def invoke(connection, **kwargs):
            calls.append((kind, connection, kwargs))
            return _confirmed_outcome()

        return invoke

    registry = WirePlumberControlRegistry()
    register_endpoint_configuration_controls(
        registry,
        select_profile=control("profile"),
        select_route=control("route"),
    )
    return WirePlumberDriverAdapter(
        lambda: "connection",
        registry=registry,
        snapshot_capture=lambda _connection: runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )


@pytest.mark.parametrize("kind", ("profile", "route"))
def test_profile_and_route_actions_resolve_names_in_current_endpoint_generation(kind) -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    previous = next(item for item in getattr(candidate, f"{kind}s") if item.active)
    selected = next(item for item in getattr(candidate, f"{kind}s") if not item.active)
    builder = build_endpoint_profile_action if kind == "profile" else build_endpoint_route_action
    calls = []
    action = builder(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        **{kind: selected, f"previous_{kind}": previous},
        intent_scope=f"plan:{kind}",
        timeout_seconds=1.25,
    )

    result = _adapter(runtime, calls).perform(action)

    assert len(calls) == 1
    assert calls[0][0:2] == (kind, "connection")
    assert calls[0][2][kind].name == selected.name
    assert calls[0][2][kind] is (
        runtime.profiles_by_key[(1, 3)] if kind == "profile" else runtime.routes_by_key[(1, 5)]
    )
    assert calls[0][2]["expected_generation"] == 3
    assert calls[0][2]["expected_sequence"] == 9
    assert calls[0][2]["request_id"] == action.idempotency_key
    assert action.command.arguments[f"{kind}Name"] == selected.name
    assert action.recovery.inverse.command.arguments[f"{kind}Name"] == previous.name
    assert action.metadata["inventoryVerificationRequired"] is True
    assert result["status"] == "confirmed"


def test_post_change_inventory_facts_confirm_active_profile_and_route() -> None:
    runtime = _runtime(selected=True)
    candidate = _candidate(runtime)

    facts = _adapter(runtime, []).observe_endpoint_configuration(
        "endpoint:main-speakers",
        candidate.runtime_key,
    )

    assert facts["endpoint.endpoint:main-speakers.activeProfiles"] == ("output:hdmi-stereo",)
    assert facts["endpoint.endpoint:main-speakers.activeRoutes"] == ("hdmi-output",)
    assert facts["endpoint.endpoint:main-speakers.profile.output:hdmi-stereo.active"] is True
    assert facts["endpoint.endpoint:main-speakers.route.hdmi-output.active"] is True


def test_recreated_endpoint_rejects_stale_profile_action() -> None:
    previous_runtime = _runtime()
    candidate = _candidate(previous_runtime)
    action = build_endpoint_profile_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        profile=next(item for item in candidate.profiles if not item.active),
        previous_profile=next(item for item in candidate.profiles if item.active),
        intent_scope="plan:stale-profile",
        timeout_seconds=1,
    )

    with pytest.raises(DriverActionError) as caught:
        _adapter(_runtime(generation=4, sink_id=110), []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert caught.value.failure.code == "wireplumber:routing-generation-stale"


def test_action_builder_rejects_configuration_from_another_generation() -> None:
    candidate = _candidate(_runtime())
    newer = _candidate(_runtime(generation=4, sink_id=110))

    with pytest.raises(ValueError, match="another runtime generation"):
        build_endpoint_route_action(
            logical_endpoint_id="endpoint:main-speakers",
            candidate=candidate,
            route=next(item for item in newer.routes if not item.active),
            previous_route=next(item for item in candidate.routes if item.active),
            intent_scope="plan:mixed-generation",
            timeout_seconds=1,
        )


def test_ambiguous_current_name_requests_fresh_resolution() -> None:
    runtime = _runtime()
    candidate = _candidate(runtime)
    selected = next(item for item in candidate.profiles if not item.active)
    action = build_endpoint_profile_action(
        logical_endpoint_id="endpoint:main-speakers",
        candidate=candidate,
        profile=selected,
        previous_profile=next(item for item in candidate.profiles if item.active),
        intent_scope="plan:ambiguous-profile",
        timeout_seconds=1,
    )
    duplicate = replace(runtime.profiles_by_key[(1, 3)], index=4)
    runtime = replace(runtime, profiles=(*runtime.profiles, duplicate))

    with pytest.raises(DriverActionError) as caught:
        _adapter(runtime, []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert caught.value.failure.code == "wireplumber:endpoint-profile-stale"
