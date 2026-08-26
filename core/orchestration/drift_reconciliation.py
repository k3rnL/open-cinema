from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import FrozenDict, freeze_json

from .action_planning import (
    PhasedDriverAction,
    ReconciliationPhase,
    evaluate_action_verification,
)
from .graph_documents import graph_content_digest


class RuntimeResourceOwnership(StrEnum):
    OPEN_CINEMA_MANAGED = "open-cinema-managed"
    MOVABLE_STREAM = "movable-stream"
    UNMANAGED = "unmanaged"


class MovableStreamRoutingPolicy(StrEnum):
    FOLLOW_DEFAULT = "follow-default"
    EXPLICIT_TARGET = "explicit-target"
    OBSERVE_ONLY = "observe-only"


class DriftDisposition(StrEnum):
    RESTORE_MANAGED = "restore-managed"
    RESTORE_STREAM_POLICY = "restore-stream-policy"
    SATISFIED = "satisfied"
    OBSERVE_ONLY = "observe-only"


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ObservedRuntimeResource:
    driver: str
    resource_kind: str
    resource_id: str
    ownership: RuntimeResourceOwnership
    state: FrozenDict

    def __post_init__(self) -> None:
        for field in ("driver", "resource_kind", "resource_id"):
            _text(getattr(self, field), field=field)
        object.__setattr__(self, "ownership", RuntimeResourceOwnership(self.ownership))
        if not isinstance(self.state, Mapping):
            raise TypeError("runtime resource state must be a mapping")
        frozen = freeze_json(dict(self.state))
        if not isinstance(frozen, FrozenDict):  # pragma: no cover
            raise TypeError("runtime resource state must be a mapping")
        object.__setattr__(self, "state", frozen)

    @property
    def key(self) -> str:
        return graph_content_digest(
            {
                "driver": self.driver,
                "resourceKind": self.resource_kind,
                "resourceId": self.resource_id,
            }
        )


@dataclass(frozen=True, slots=True)
class MovableStreamIntent:
    stream_id: str
    policy: MovableStreamRoutingPolicy
    current_target: str | None
    default_target: str | None
    desired_target: str | None
    has_explicit_target: bool
    clear_target_action: PhasedDriverAction | None = None
    set_target_action: PhasedDriverAction | None = None

    def __post_init__(self) -> None:
        _text(self.stream_id, field="stream_id")
        object.__setattr__(self, "policy", MovableStreamRoutingPolicy(self.policy))
        for field in ("current_target", "default_target", "desired_target"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field=field)
        if not isinstance(self.has_explicit_target, bool):
            raise TypeError("has_explicit_target must be a boolean")
        for field in ("clear_target_action", "set_target_action"):
            action = getattr(self, field)
            if action is not None:
                if not isinstance(action, PhasedDriverAction):
                    raise TypeError(f"{field} must be a PhasedDriverAction or null")
                if action.phase is not ReconciliationPhase.ROUTE:
                    raise ValueError(f"{field} must be a route-phase action")
                if action.action.identity.resource_id != self.stream_id:
                    raise ValueError(f"{field} must target the movable stream")
        if self.policy is MovableStreamRoutingPolicy.FOLLOW_DEFAULT:
            if self.clear_target_action is None:
                raise ValueError("follow-default policy requires clear_target_action")
            if self.desired_target is not None:
                raise ValueError("follow-default policy cannot declare desired_target")
        elif self.policy is MovableStreamRoutingPolicy.EXPLICIT_TARGET:
            if self.set_target_action is None or self.desired_target is None:
                raise ValueError(
                    "explicit-target policy requires desired_target and set_target_action"
                )


@dataclass(frozen=True, slots=True)
class DriftDecision:
    resource_id: str
    ownership: RuntimeResourceOwnership
    disposition: DriftDisposition
    reason: str
    action: PhasedDriverAction | None

    def to_document(self) -> dict[str, object]:
        return {
            "resourceId": self.resource_id,
            "ownership": self.ownership.value,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "actionIdempotencyKey": (
                self.action.action.idempotency_key if self.action is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class DriftReconciliationPlan:
    decisions: tuple[DriftDecision, ...]
    actions: tuple[PhasedDriverAction, ...]
    unmanaged_resource_keys: tuple[str, ...]
    digest: str


def _managed_decisions(
    desired_actions: Sequence[PhasedDriverAction],
    facts: Mapping[str, object],
) -> list[DriftDecision]:
    decisions = []
    for phased in desired_actions:
        if not isinstance(phased, PhasedDriverAction):
            raise TypeError("desired managed actions must be PhasedDriverAction values")
        satisfied, reasons = evaluate_action_verification(phased.action, facts)
        decisions.append(
            DriftDecision(
                resource_id=phased.action.identity.resource_id,
                ownership=RuntimeResourceOwnership.OPEN_CINEMA_MANAGED,
                disposition=(
                    DriftDisposition.SATISFIED if satisfied else DriftDisposition.RESTORE_MANAGED
                ),
                reason=(
                    "Managed resource matches resolved intent." if satisfied else "; ".join(reasons)
                ),
                action=None if satisfied else phased,
            )
        )
    return decisions


def _stream_decision(stream: MovableStreamIntent) -> DriftDecision:
    if stream.policy is MovableStreamRoutingPolicy.OBSERVE_ONLY:
        return DriftDecision(
            stream.stream_id,
            RuntimeResourceOwnership.MOVABLE_STREAM,
            DriftDisposition.OBSERVE_ONLY,
            "The declared policy observes this stream without changing its target.",
            None,
        )
    if stream.policy is MovableStreamRoutingPolicy.FOLLOW_DEFAULT:
        satisfied = not stream.has_explicit_target
        return DriftDecision(
            stream.stream_id,
            RuntimeResourceOwnership.MOVABLE_STREAM,
            DriftDisposition.SATISFIED if satisfied else DriftDisposition.RESTORE_STREAM_POLICY,
            (
                "The stream already follows the declared default target."
                if satisfied
                else "Clear the stream's explicit target so WirePlumber default policy applies."
            ),
            None if satisfied else stream.clear_target_action,
        )
    satisfied = stream.has_explicit_target and stream.current_target == stream.desired_target
    return DriftDecision(
        stream.stream_id,
        RuntimeResourceOwnership.MOVABLE_STREAM,
        DriftDisposition.SATISFIED if satisfied else DriftDisposition.RESTORE_STREAM_POLICY,
        (
            "The stream already uses its declared explicit target."
            if satisfied
            else "Restore the stream's declared explicit target."
        ),
        None if satisfied else stream.set_target_action,
    )


def build_drift_reconciliation_plan(
    *,
    desired_managed_actions: Sequence[PhasedDriverAction],
    movable_streams: Sequence[MovableStreamIntent],
    observed_resources: Sequence[ObservedRuntimeResource],
    facts: Mapping[str, object],
) -> DriftReconciliationPlan:
    if not isinstance(facts, Mapping):
        raise TypeError("facts must be a mapping")
    decisions = _managed_decisions(tuple(desired_managed_actions), facts)
    streams = tuple(movable_streams)
    if any(not isinstance(stream, MovableStreamIntent) for stream in streams):
        raise TypeError("movable_streams must contain MovableStreamIntent values")
    decisions.extend(_stream_decision(stream) for stream in streams)

    resources = tuple(observed_resources)
    if any(not isinstance(item, ObservedRuntimeResource) for item in resources):
        raise TypeError("observed_resources must contain ObservedRuntimeResource values")
    unmanaged = []
    for resource in resources:
        if resource.ownership is not RuntimeResourceOwnership.UNMANAGED:
            continue
        unmanaged.append(resource.key)
        decisions.append(
            DriftDecision(
                resource.resource_id,
                RuntimeResourceOwnership.UNMANAGED,
                DriftDisposition.OBSERVE_ONLY,
                "Unmanaged runtime resources are observed and never mutated or deleted.",
                None,
            )
        )

    ordered = tuple(
        sorted(
            decisions,
            key=lambda decision: (
                decision.ownership.value,
                decision.resource_id,
                decision.disposition.value,
            ),
        )
    )
    actions = tuple(decision.action for decision in ordered if decision.action is not None)
    document = {
        "schemaVersion": 1,
        "decisions": [decision.to_document() for decision in ordered],
        "unmanagedResourceKeys": sorted(unmanaged),
    }
    return DriftReconciliationPlan(
        decisions=ordered,
        actions=actions,
        unmanaged_resource_keys=tuple(sorted(unmanaged)),
        digest=graph_content_digest(document),
    )
