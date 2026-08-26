import json
from dataclasses import replace

import pytest
from wyreplumber.runtime import FrozenDict

from core.orchestration.endpoint_binding import (
    SelectorDerivationConfidence,
    UnstableEndpointIdentityError,
    derive_reviewable_selector,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from tests.test_endpoint_inventory_mapping import _snapshot


def _candidate(name, **snapshot_kwargs):
    return next(
        candidate
        for candidate in map_runtime_endpoints(_snapshot(**snapshot_kwargs)).candidates
        if candidate.name == name
    )


def test_bluetooth_binding_uses_address_and_never_runtime_id() -> None:
    candidate = _candidate("bluez_input.phone")

    derived = derive_reviewable_selector(candidate)

    assert derived.confidence == SelectorDerivationConfidence.HIGH
    assert derived.selector.matches(candidate) is True
    predicates = {item["path"]: item["value"] for item in derived.document["predicates"]}
    assert predicates["node.properties.api.bluez5.address"] == "AA:BB:CC:DD:EE:FF"
    serialized = json.dumps(derived.document)
    assert "runtime" not in serialized.lower()
    assert str(candidate.runtime.node_id) not in serialized


def test_numeric_id_change_produces_the_same_reviewable_selector() -> None:
    before = derive_reviewable_selector(
        _candidate("bluez_input.phone", generation=3, source_id=20)
    )
    after = derive_reviewable_selector(
        _candidate("bluez_input.phone", generation=4, source_id=220)
    )

    assert before.document == after.document


def test_alsa_card_index_is_not_part_of_reviewable_selector() -> None:
    before_candidate = _candidate("alsa_output.usb-room")
    after_candidate = replace(
        before_candidate,
        node_properties=FrozenDict(
            {
                **before_candidate.node_properties.to_dict(),
                "api.alsa.path": "surround71:2",
            }
        ),
        device_properties=FrozenDict(
            {
                **before_candidate.device_properties.to_dict(),
                "api.alsa.path": "hw:2",
            }
        ),
    )

    before = derive_reviewable_selector(before_candidate)
    after = derive_reviewable_selector(after_candidate)

    assert before.document == after.document
    assert all(
        predicate["path"]
        not in {
            "node.properties.api.alsa.path",
            "device.properties.api.alsa.path",
        }
        for predicate in before.document["predicates"]
    )


def test_managed_id_produces_exact_confidence() -> None:
    candidate = _candidate("alsa_output.usb-room")
    candidate = replace(
        candidate,
        node_properties=FrozenDict(
            {
                **candidate.node_properties.to_dict(),
                "open-cinema.endpoint-id": "endpoint:main",
            }
        ),
    )

    derived = derive_reviewable_selector(candidate)

    assert derived.confidence == SelectorDerivationConfidence.EXACT
    assert any(
        predicate["value"] == "endpoint:main"
        for predicate in derived.document["predicates"]
    )


def test_managed_adapter_id_produces_bindable_exact_selector() -> None:
    candidate = _candidate("alsa_output.usb-room")
    candidate = replace(
        candidate,
        node_properties=FrozenDict(
            {
                **candidate.node_properties.to_dict(),
                "open-cinema.owner": "open-cinema.adapter-supervisor.v1",
                "open-cinema.adapter.id": "adapter:recorder",
                "open-cinema.adapter.kind": "debug-file-recorder",
                "open-cinema.adapter.direction": "output",
            }
        ),
    )

    derived = derive_reviewable_selector(candidate)

    assert derived.confidence == SelectorDerivationConfidence.EXACT
    assert derived.selector.matches(candidate) is True
    assert any(
        predicate["path"] == "node.properties.open-cinema.adapter.id"
        and predicate["value"] == "adapter:recorder"
        for predicate in derived.document["predicates"]
    )


def test_description_only_binding_is_low_confidence_and_reviewable() -> None:
    candidate = _candidate("bluez_input.phone")
    candidate = replace(
        candidate,
        name=None,
        device_name=None,
        node_properties=FrozenDict(),
        device_properties=FrozenDict(),
        profiles=(),
        routes=(),
    )

    derived = derive_reviewable_selector(candidate)

    assert derived.confidence == SelectorDerivationConfidence.LOW
    assert derived.warnings
    assert derived.selector.matches(candidate) is True


def test_media_class_only_endpoint_requires_managed_identity() -> None:
    candidate = _candidate("bluez_input.phone")
    candidate = replace(
        candidate,
        name=None,
        description=None,
        device_name=None,
        device_description=None,
        node_properties=FrozenDict(),
        device_properties=FrozenDict(),
        profiles=(),
        routes=(),
    )

    with pytest.raises(UnstableEndpointIdentityError, match="managed ID"):
        derive_reviewable_selector(candidate)


def test_explicit_binding_selector_cannot_depend_on_transient_id() -> None:
    validation = parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [
                {"path": "runtime.nodeId", "operator": "exact", "value": 42}
            ],
        }
    )

    assert validation.valid is False
    assert validation.issues[0].code == "unsafe_path"
