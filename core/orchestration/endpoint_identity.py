from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .endpoint_inventory import RuntimeEndpointCandidate


class IdentityEvidenceTier(IntEnum):
    MANAGED_ID = 0
    HARDWARE = 1
    ROUTE_PROFILE = 2
    STABLE_NAME = 3
    DESCRIPTIVE = 4


class IdentityEvidenceKind(StrEnum):
    MANAGED_ID = "managed_id"
    HARDWARE_SERIAL = "hardware_serial"
    HARDWARE_ADDRESS = "hardware_address"
    HARDWARE_PATH = "hardware_path"
    ROUTE = "route"
    PROFILE = "profile"
    NODE_NAME = "node_name"
    DEVICE_NAME = "device_name"
    DESCRIPTION = "description"
    MEDIA_CLASS = "media_class"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    tier: IdentityEvidenceTier
    kind: IdentityEvidenceKind
    path: str
    value: str


_HARDWARE_PROPERTIES = (
    ("device.serial", IdentityEvidenceKind.HARDWARE_SERIAL),
    ("api.bluez5.address", IdentityEvidenceKind.HARDWARE_ADDRESS),
    ("device.bus-id", IdentityEvidenceKind.HARDWARE_PATH),
    ("object.path", IdentityEvidenceKind.HARDWARE_PATH),
)


def _property(candidate, key):
    node_value = candidate.node_properties.get(key)
    if isinstance(node_value, str) and node_value:
        return f"node.properties.{key}", node_value
    device_value = candidate.device_properties.get(key)
    if isinstance(device_value, str) and device_value:
        return f"device.properties.{key}", device_value
    return None


def rank_stable_identity_evidence(
    candidate: RuntimeEndpointCandidate,
) -> tuple[IdentityEvidence, ...]:
    """Rank stable evidence without ever treating runtime IDs as identity."""

    evidence: list[IdentityEvidence] = []
    managed = _property(candidate, "open-cinema.endpoint-id") or _property(
        candidate, "open-cinema.adapter.id"
    )
    if managed:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.MANAGED_ID,
                IdentityEvidenceKind.MANAGED_ID,
                managed[0],
                managed[1],
            )
        )
    for property_name, kind in _HARDWARE_PROPERTIES:
        found = _property(candidate, property_name)
        if found:
            evidence.append(
                IdentityEvidence(
                    IdentityEvidenceTier.HARDWARE,
                    kind,
                    found[0],
                    found[1],
                )
            )
    for route in candidate.routes:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.ROUTE_PROFILE,
                IdentityEvidenceKind.ROUTE,
                "route.name",
                route.name,
            )
        )
    for profile in candidate.profiles:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.ROUTE_PROFILE,
                IdentityEvidenceKind.PROFILE,
                "profile.name",
                profile.name,
            )
        )
    if candidate.name:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.STABLE_NAME,
                IdentityEvidenceKind.NODE_NAME,
                "node.name",
                candidate.name,
            )
        )
    if candidate.device_name:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.STABLE_NAME,
                IdentityEvidenceKind.DEVICE_NAME,
                "device.name",
                candidate.device_name,
            )
        )
    description = candidate.description or candidate.device_description
    if description:
        evidence.append(
            IdentityEvidence(
                IdentityEvidenceTier.DESCRIPTIVE,
                IdentityEvidenceKind.DESCRIPTION,
                "node.description" if candidate.description else "device.description",
                description,
            )
        )
    evidence.append(
        IdentityEvidence(
            IdentityEvidenceTier.DESCRIPTIVE,
            IdentityEvidenceKind.MEDIA_CLASS,
            "mediaClass",
            candidate.media_class,
        )
    )
    return tuple(
        sorted(
            set(evidence),
            key=lambda item: (item.tier, item.kind.value, item.path, item.value),
        )
    )
