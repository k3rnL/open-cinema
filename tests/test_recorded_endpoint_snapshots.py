import json
from pathlib import Path

import pytest
from wyreplumber.runtime import runtime_snapshot_from_payload

from core.orchestration.endpoint_continuity import (
    InventoryContinuityAction,
    RuntimeInventoryContinuity,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.endpoint_matching import (
    EndpointMatchStatus,
    match_endpoint_candidates,
)
from core.orchestration.endpoint_projection import (
    EndpointProjectionState,
    LogicalEndpointIntent,
    project_logical_endpoint,
)
from core.orchestration.endpoint_selectors import parse_endpoint_selector


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "orchestration"
    / "runtime_endpoint_snapshots.json"
)


@pytest.fixture(scope="module")
def recorded_snapshots():
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert document["fixtureVersion"] == "open-cinema.runtime-endpoints/v1"
    return {
        name: runtime_snapshot_from_payload(payload)
        for name, payload in document["snapshots"].items()
    }


def _selector(path: str, value: object):
    validation = parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [
                {"path": path, "operator": "exact", "value": value}
            ],
        }
    )
    assert validation.valid
    return validation.selector


@pytest.mark.parametrize(
    ("case", "path", "value", "expected_name", "direction"),
    (
        (
            "USB",
            "device.properties.device.serial",
            "USB-DAC-001",
            "alsa_output.usb-room-dac",
            "output",
        ),
        (
            "HDMI",
            "device.properties.api.alsa.path",
            "hdmi:0,0",
            "alsa_output.hdmi-avr",
            "output",
        ),
        (
            "ALSA",
            "device.properties.device.bus-id",
            "platform-fe203000.i2s",
            "alsa_input.tv-spdif",
            "input",
        ),
        (
            "Bluetooth",
            "device.properties.api.bluez5.address",
            "AA:BB:CC:00:00:01",
            "bluez_input.phone",
            "input",
        ),
        (
            "headset",
            "device.properties.api.bluez5.address",
            "AA:BB:CC:00:00:02",
            "bluez_output.headset",
            "output",
        ),
    ),
)
def test_recorded_endpoint_kinds_match_stable_properties(
    recorded_snapshots,
    case,
    path,
    value,
    expected_name,
    direction,
) -> None:
    inventory = map_runtime_endpoints(recorded_snapshots["connected"])

    result = match_endpoint_candidates(_selector(path, value), inventory.candidates)

    assert result.status is EndpointMatchStatus.MATCHED, case
    assert result.selected.name == expected_name
    assert result.selected.direction.value == direction


def test_recorded_processor_resources_are_not_endpoint_candidates(
    recorded_snapshots,
) -> None:
    inventory = map_runtime_endpoints(recorded_snapshots["connected"])

    assert "opencinema.camilladsp.room.input" not in {
        candidate.name for candidate in inventory.candidates
    }


def test_recorded_equal_generic_devices_are_explicitly_ambiguous(
    recorded_snapshots,
) -> None:
    inventory = map_runtime_endpoints(recorded_snapshots["connected"])

    result = match_endpoint_candidates(
        _selector("node.description", "Generic USB Audio"),
        inventory.candidates,
    )

    assert result.status is EndpointMatchStatus.AMBIGUOUS
    assert [candidate.name for candidate in result.tied] == [
        "alsa_output.generic-a",
        "alsa_output.generic-b",
    ]
    assert all(
        any("equal-best-score" in item for item in diagnostic.rejected_evidence)
        for diagnostic in result.diagnostics
        if diagnostic.matched_selector
    )


def test_recorded_disconnect_preserves_last_seen_and_projects_unavailable(
    recorded_snapshots,
) -> None:
    connected = map_runtime_endpoints(recorded_snapshots["connected"])
    selector_document = {
        "version": 1,
        "match": "all",
        "predicates": [
            {
                "path": "device.properties.api.bluez5.address",
                "operator": "exact",
                "value": "AA:BB:CC:00:00:02",
            }
        ],
    }
    initial = project_logical_endpoint(
        LogicalEndpointIntent(
            id="endpoint:headset",
            name="Headset",
            direction="output",
            selector=selector_document,
            last_known_summary={},
        ),
        connected,
    )
    disconnected = map_runtime_endpoints(recorded_snapshots["headset_disconnected"])

    absent = project_logical_endpoint(
        LogicalEndpointIntent(
            id="endpoint:headset",
            name="Headset",
            direction="output",
            selector=selector_document,
            last_known_summary=initial.summary,
        ),
        disconnected,
    )

    assert initial.primary_state is EndpointProjectionState.ROUTE_AVAILABLE
    assert absent.primary_state is EndpointProjectionState.UNAVAILABLE
    assert absent.last_seen == connected.captured_at
    assert absent.summary["name"] == "bluez_output.headset"


def test_recorded_restart_rematches_stable_identity_with_new_runtime_ids(
    recorded_snapshots,
) -> None:
    before = map_runtime_endpoints(recorded_snapshots["connected"])
    after = map_runtime_endpoints(recorded_snapshots["headset_after_restart"])
    selector = _selector(
        "device.properties.api.bluez5.address",
        "AA:BB:CC:00:00:02",
    )

    before_match = match_endpoint_candidates(selector, before.candidates)
    after_match = match_endpoint_candidates(selector, after.candidates)

    assert before_match.status is EndpointMatchStatus.MATCHED
    assert after_match.status is EndpointMatchStatus.MATCHED
    assert before_match.selected.runtime_key != after_match.selected.runtime_key
    assert before_match.selected.selector_facts() == after_match.selected.selector_facts()


def test_recorded_snapshot_sequence_is_accepted_monotonically_across_restart(
    recorded_snapshots,
) -> None:
    continuity = RuntimeInventoryContinuity()

    connected = continuity.accept_snapshot(recorded_snapshots["connected"])
    disconnected = continuity.accept_snapshot(recorded_snapshots["headset_disconnected"])
    restarted = continuity.accept_snapshot(recorded_snapshots["headset_after_restart"])

    assert connected.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert disconnected.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert restarted.action is InventoryContinuityAction.SNAPSHOT_ACCEPTED
    assert continuity.generation == 42
    assert continuity.sequence == 4
