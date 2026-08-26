from dataclasses import replace

from wyreplumber.runtime import FrozenDict

from core.orchestration.endpoint_identity import (
    IdentityEvidenceKind,
    IdentityEvidenceTier,
    rank_stable_identity_evidence,
)
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from tests.test_endpoint_inventory_mapping import _snapshot


def _candidate(name, **snapshot_kwargs):
    inventory = map_runtime_endpoints(_snapshot(**snapshot_kwargs))
    return next(candidate for candidate in inventory.candidates if candidate.name == name)


def test_managed_identity_outranks_hardware_route_and_names() -> None:
    candidate = _candidate("alsa_output.usb-room")
    candidate = replace(
        candidate,
        node_properties=FrozenDict(
            {
                **candidate.node_properties.to_dict(),
                "open-cinema.endpoint-id": "endpoint:living-room",
            }
        ),
    )

    evidence = rank_stable_identity_evidence(candidate)

    assert evidence[0].tier == IdentityEvidenceTier.MANAGED_ID
    assert evidence[0].kind == IdentityEvidenceKind.MANAGED_ID
    assert evidence[0].value == "endpoint:living-room"
    tiers = [item.tier for item in evidence]
    assert tiers == sorted(tiers)


def test_bluetooth_address_is_hardware_evidence_before_node_name() -> None:
    evidence = rank_stable_identity_evidence(_candidate("bluez_input.phone"))

    assert evidence[0].kind == IdentityEvidenceKind.HARDWARE_ADDRESS
    assert evidence[0].value == "AA:BB:CC:DD:EE:FF"
    assert next(item for item in evidence if item.kind == IdentityEvidenceKind.NODE_NAME)


def test_runtime_numeric_id_changes_do_not_change_identity_evidence() -> None:
    before = rank_stable_identity_evidence(
        _candidate("bluez_input.phone", generation=3, source_id=20)
    )
    after = rank_stable_identity_evidence(
        _candidate("bluez_input.phone", generation=4, source_id=220)
    )

    assert before == after
    assert all("runtime" not in item.path.lower() for item in before)
    assert all(item.value not in {"20", "220"} for item in before)


def test_descriptive_media_class_is_always_the_last_fallback() -> None:
    evidence = rank_stable_identity_evidence(_candidate("bluez_input.phone"))

    assert evidence[-1].tier == IdentityEvidenceTier.DESCRIPTIVE
    assert any(item.kind == IdentityEvidenceKind.MEDIA_CLASS for item in evidence)
