from dataclasses import replace

from core.orchestration.endpoint_inventory import (
    EndpointInventorySnapshot,
    RuntimeEndpointReference,
    map_runtime_endpoints,
)
from core.orchestration.endpoint_projection import (
    EndpointProjectionState,
    LogicalEndpointIntent,
    project_logical_endpoint,
)
from tests.test_endpoint_binding import _candidate
from tests.test_endpoint_inventory_mapping import _snapshot


def _intent(selector, *, direction="output", previous=None):
    return LogicalEndpointIntent(
        id="endpoint:test",
        name="Test endpoint",
        direction=direction,
        selector=selector,
        last_known_summary=previous or {},
    )


def _selector(path, value):
    return {
        "version": 1,
        "match": "all",
        "predicates": [{"path": path, "operator": "exact", "value": value}],
    }


def test_projection_combines_discovery_route_selection_link_and_signal_states() -> None:
    inventory = map_runtime_endpoints(_snapshot())
    sink = next(candidate for candidate in inventory.candidates if candidate.direction.value == "output")
    projection = project_logical_endpoint(
        _intent(_selector("device.properties.device.serial", "ROOM-123")),
        inventory,
        selected_runtime_keys={sink.runtime_key},
    )

    assert projection.primary_state == EndpointProjectionState.ACTIVE_SIGNAL
    assert set(projection.states) == {
        EndpointProjectionState.DISCOVERED,
        EndpointProjectionState.ROUTE_AVAILABLE,
        EndpointProjectionState.SELECTED,
        EndpointProjectionState.LINKED,
        EndpointProjectionState.ACTIVE_SIGNAL,
    }
    assert projection.last_seen == inventory.captured_at
    assert projection.summary["name"] == "alsa_output.usb-room"


def test_suspended_and_error_states_take_visible_precedence() -> None:
    candidate = _candidate("alsa_output.usb-room")
    suspended = replace(candidate, node_state="suspended", has_active_signal=False)
    errored = replace(candidate, node_state="error", node_error="device failed")
    base = map_runtime_endpoints(_snapshot())
    selector = _selector("device.properties.device.serial", "ROOM-123")

    suspended_projection = project_logical_endpoint(
        _intent(selector),
        replace(base, candidates=(suspended,)),
    )
    error_projection = project_logical_endpoint(
        _intent(selector),
        replace(base, candidates=(errored,)),
    )

    assert suspended_projection.primary_state == EndpointProjectionState.SUSPENDED
    assert error_projection.primary_state == EndpointProjectionState.ERROR


def test_unavailable_endpoint_keeps_last_seen_summary() -> None:
    inventory = replace(map_runtime_endpoints(_snapshot()), candidates=())
    projection = project_logical_endpoint(
        _intent(
            _selector("node.name", "missing"),
            previous={"lastSeen": "2026-08-20T10:00:00+00:00", "name": "Old name"},
        ),
        inventory,
    )

    assert projection.primary_state == EndpointProjectionState.UNAVAILABLE
    assert projection.last_seen == "2026-08-20T10:00:00+00:00"
    assert projection.summary["name"] == "Old name"


def test_equal_candidates_project_as_ambiguous_without_selection() -> None:
    first = _candidate("alsa_output.usb-room")
    second = replace(first, runtime=RuntimeEndpointReference(3, 999, 1))
    inventory = EndpointInventorySnapshot(
        generation=3,
        sequence=1,
        captured_at="2026-08-22T12:00:00+00:00",
        candidates=(first, second),
    )

    projection = project_logical_endpoint(
        _intent(_selector("direction", "output")),
        inventory,
    )

    assert projection.primary_state == EndpointProjectionState.AMBIGUOUS
    assert projection.runtime_key is None
    assert projection.matched_candidates == 2


def test_invalid_selector_projects_error_instead_of_disappearing() -> None:
    projection = project_logical_endpoint(
        _intent(_selector("runtime.nodeId", 10)),
        map_runtime_endpoints(_snapshot()),
    )

    assert projection.primary_state == EndpointProjectionState.ERROR
    assert projection.diagnostics[0]["code"] == "unsafe_path"
