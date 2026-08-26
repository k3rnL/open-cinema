from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .endpoint_identity import (
    IdentityEvidence,
    IdentityEvidenceKind,
    IdentityEvidenceTier,
    rank_stable_identity_evidence,
)
from .endpoint_inventory import RuntimeEndpointCandidate
from .endpoint_selectors import EndpointSelector, parse_endpoint_selector


class SelectorDerivationConfidence(StrEnum):
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class UnstableEndpointIdentityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewableEndpointSelector:
    document: dict[str, object]
    selector: EndpointSelector
    confidence: SelectorDerivationConfidence
    evidence: tuple[IdentityEvidence, ...]
    warnings: tuple[str, ...]


def _predicate(evidence: IdentityEvidence):
    return {
        "path": evidence.path,
        "operator": "exact",
        "value": evidence.value,
    }


def derive_reviewable_selector(
    candidate: RuntimeEndpointCandidate,
) -> ReviewableEndpointSelector:
    """Derive durable intent from an explicit click, never from a runtime ID."""

    evidence = rank_stable_identity_evidence(candidate)
    by_tier = {
        tier: tuple(item for item in evidence if item.tier == tier) for tier in IdentityEvidenceTier
    }
    selected: tuple[IdentityEvidence, ...]
    warnings: tuple[str, ...] = ()
    if by_tier[IdentityEvidenceTier.MANAGED_ID]:
        selected = by_tier[IdentityEvidenceTier.MANAGED_ID]
        confidence = SelectorDerivationConfidence.EXACT
    elif by_tier[IdentityEvidenceTier.HARDWARE]:
        selected = by_tier[IdentityEvidenceTier.HARDWARE]
        confidence = SelectorDerivationConfidence.HIGH
    elif by_tier[IdentityEvidenceTier.ROUTE_PROFILE]:
        selected = (
            *by_tier[IdentityEvidenceTier.ROUTE_PROFILE],
            *by_tier[IdentityEvidenceTier.STABLE_NAME],
        )
        confidence = SelectorDerivationConfidence.MEDIUM
        warnings = (
            "Route/profile identity can change when the device profile changes; review the selector.",
        )
    elif by_tier[IdentityEvidenceTier.STABLE_NAME]:
        selected = by_tier[IdentityEvidenceTier.STABLE_NAME]
        confidence = SelectorDerivationConfidence.MEDIUM
        warnings = (
            "Node/device names are software identity and should be reviewed after upgrades.",
        )
    else:
        descriptions = tuple(
            item
            for item in by_tier[IdentityEvidenceTier.DESCRIPTIVE]
            if item.kind == IdentityEvidenceKind.DESCRIPTION
        )
        if not descriptions:
            raise UnstableEndpointIdentityError(
                "Endpoint exposes only a media class; assign a managed ID before binding."
            )
        selected = descriptions
        confidence = SelectorDerivationConfidence.LOW
        warnings = (
            "This selector uses descriptive text and may become ambiguous; assign a managed ID.",
        )
    predicates = [
        {"path": "direction", "operator": "exact", "value": candidate.direction.value},
        {"path": "mediaClass", "operator": "exact", "value": candidate.media_class},
        *(_predicate(item) for item in selected),
    ]
    deduplicated = []
    seen = set()
    for predicate in predicates:
        key = (predicate["path"], predicate["operator"], predicate["value"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(predicate)
    document = {
        "version": 1,
        "match": "all",
        "predicates": deduplicated,
    }
    validation = parse_endpoint_selector(document)
    if not validation.valid:
        message = "; ".join(issue.message for issue in validation.issues)
        raise UnstableEndpointIdentityError(message)
    return ReviewableEndpointSelector(
        document=document,
        selector=validation.selector,
        confidence=confidence,
        evidence=selected,
        warnings=warnings,
    )
