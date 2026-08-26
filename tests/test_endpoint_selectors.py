import pytest

from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from tests.test_endpoint_inventory_mapping import _snapshot


def _candidate(name):
    inventory = map_runtime_endpoints(_snapshot())
    return next(candidate for candidate in inventory.candidates if candidate.name == name)


def test_exact_set_and_safe_pattern_predicates_match_catalogued_fields() -> None:
    validation = parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [
                {"path": "direction", "operator": "exact", "value": "output"},
                {
                    "path": "device.properties.device.serial",
                    "operator": "oneOf",
                    "value": ["ROOM-123", "ROOM-456"],
                },
                {
                    "path": "route.name",
                    "operator": "pattern",
                    "value": "analog-output-*",
                },
                {"path": "profile.active", "operator": "exact", "value": True},
                {
                    "path": "node.name",
                    "operator": "pattern",
                    "value": "ALSA_OUTPUT.*",
                    "caseSensitive": False,
                },
            ],
        }
    )

    assert validation.valid is True
    assert validation.selector.matches(_candidate("alsa_output.usb-room")) is True
    assert validation.selector.matches(_candidate("bluez_input.phone")) is False


def test_any_selector_accepts_one_matching_stable_property() -> None:
    validation = parse_endpoint_selector(
        {
            "version": 1,
            "match": "any",
            "predicates": [
                {
                    "path": "device.properties.device.serial",
                    "operator": "exact",
                    "value": "not-this-device",
                },
                {
                    "path": "node.properties.api.bluez5.address",
                    "operator": "exact",
                    "value": "AA:BB:CC:DD:EE:FF",
                },
            ],
        }
    )

    assert validation.selector.matches(_candidate("bluez_input.phone")) is True


@pytest.mark.parametrize(
    ("predicate", "code"),
    (
        (
            {"path": "runtime.nodeId", "operator": "exact", "value": 10},
            "unsafe_path",
        ),
        (
            {"path": "node.properties.arbitrary", "operator": "exact", "value": "x"},
            "unsafe_path",
        ),
        (
            {"path": "node.name", "operator": "regex", "value": ".*"},
            "invalid_operator",
        ),
        (
            {"path": "node.name", "operator": "pattern", "value": "(a+)+[x]"},
            "unsafe_pattern",
        ),
        (
            {"path": "direction", "operator": "oneOf", "value": []},
            "invalid_set",
        ),
    ),
)
def test_unsafe_selector_shapes_are_rejected(predicate, code) -> None:
    validation = parse_endpoint_selector(
        {"version": 1, "match": "all", "predicates": [predicate]}
    )

    assert validation.valid is False
    assert code in {issue.code for issue in validation.issues}


def test_matching_is_type_strict_for_booleans_and_numbers() -> None:
    validation = parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [
                {"path": "profile.active", "operator": "exact", "value": 1}
            ],
        }
    )

    assert validation.valid is True
    assert validation.selector.matches(_candidate("alsa_output.usb-room")) is False
