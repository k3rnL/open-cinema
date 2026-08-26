from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from wyreplumber.runtime import FrozenDict, freeze_json

from api.models import GraphDefinition

from .audit import record_orchestration_event
from .driver_actions import ActionFailure, DriverAction


class GenerationConvergenceStatus(StrEnum):
    CONVERGED = "converged"
    DEGRADED = "degraded"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class AuditedActionStatus(StrEnum):
    ALREADY_SATISFIED = "already-satisfied"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _instant(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _frozen(value: Mapping[str, object], *, field: str) -> FrozenDict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    frozen = freeze_json(dict(value))
    if not isinstance(frozen, FrozenDict):  # pragma: no cover
        raise TypeError(f"{field} must be a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class ReconciliationTriggerAudit:
    kind: str
    causes: tuple[str, ...]
    occurred_at: datetime

    def __post_init__(self) -> None:
        _text(self.kind, field="trigger kind")
        causes = tuple(dict.fromkeys(self.causes))
        if not causes or any(not isinstance(item, str) or not item for item in causes):
            raise ValueError("trigger causes must contain non-empty strings")
        object.__setattr__(self, "causes", causes)
        object.__setattr__(
            self,
            "occurred_at",
            _instant(self.occurred_at, field="trigger occurred_at"),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "causes": list(self.causes),
            "occurredAt": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationInputVersions:
    graph_revision_id: str
    graph_revision_digest: str
    desired_state_version: int
    world_version: int
    runtime_generation: int
    runtime_sequence: int
    resolved_plan_id: str
    resolved_plan_digest: str
    transition_generation: int
    applied_plan_id: str | None = None
    applied_plan_digest: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "graph_revision_id",
            "graph_revision_digest",
            "resolved_plan_id",
            "resolved_plan_digest",
        ):
            _text(getattr(self, field), field=field)
        for field, minimum in (
            ("desired_state_version", 1),
            ("world_version", 1),
            ("runtime_generation", 1),
            ("runtime_sequence", 0),
            ("transition_generation", 1),
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
        if (self.applied_plan_id is None) != (self.applied_plan_digest is None):
            raise ValueError("applied plan ID and digest must be present together")
        if self.applied_plan_id is not None:
            _text(self.applied_plan_id, field="applied_plan_id")
            _text(self.applied_plan_digest, field="applied_plan_digest")

    def to_document(self) -> dict[str, object]:
        return {
            "graphRevisionId": self.graph_revision_id,
            "graphRevisionDigest": self.graph_revision_digest,
            "desiredStateVersion": self.desired_state_version,
            "worldVersion": self.world_version,
            "runtimeGeneration": self.runtime_generation,
            "runtimeSequence": self.runtime_sequence,
            "resolvedPlanId": self.resolved_plan_id,
            "resolvedPlanDigest": self.resolved_plan_digest,
            "transitionGeneration": self.transition_generation,
            "appliedPlanId": self.applied_plan_id,
            "appliedPlanDigest": self.applied_plan_digest,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationActionAudit:
    phase: str
    action: DriverAction
    status: AuditedActionStatus
    started_at: datetime
    completed_at: datetime
    attempts: int
    observed: FrozenDict = FrozenDict()
    failure: ActionFailure | None = None

    def __post_init__(self) -> None:
        _text(self.phase, field="action phase")
        if not isinstance(self.action, DriverAction):
            raise TypeError("action must be a DriverAction")
        object.__setattr__(self, "status", AuditedActionStatus(self.status))
        started_at = _instant(self.started_at, field="action started_at")
        completed_at = _instant(self.completed_at, field="action completed_at")
        if completed_at < started_at:
            raise ValueError("action completion cannot precede action start")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        if (
            isinstance(self.attempts, bool)
            or not isinstance(self.attempts, int)
            or self.attempts < 1
        ):
            raise ValueError("action attempts must be a positive integer")
        object.__setattr__(self, "observed", _frozen(self.observed, field="action observed"))
        if self.failure is not None and not isinstance(self.failure, ActionFailure):
            raise TypeError("failure must be an ActionFailure or null")
        if (self.failure is not None) is not (self.status is AuditedActionStatus.FAILED):
            raise ValueError("failure must be present exactly for failed action audits")

    def to_document(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "identity": self.action.identity.to_document(),
            "idempotencyKey": self.action.idempotency_key,
            "status": self.status.value,
            "attempts": self.attempts,
            "startedAt": self.started_at.isoformat(),
            "completedAt": self.completed_at.isoformat(),
            "durationMs": (self.completed_at - self.started_at).total_seconds() * 1000,
            "observed": self.observed.to_dict(),
            "failure": self.failure.to_document() if self.failure is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationGenerationAudit:
    graph_definition_id: str
    correlation_id: uuid.UUID
    generation: int
    trigger: ReconciliationTriggerAudit
    inputs: ReconciliationInputVersions
    decision: FrozenDict
    actions: tuple[ReconciliationActionAudit, ...]
    started_at: datetime
    completed_at: datetime
    convergence_status: GenerationConvergenceStatus
    final_runtime_generation: int
    final_runtime_sequence: int
    errors: tuple[ActionFailure, ...] = ()

    def __post_init__(self) -> None:
        _text(self.graph_definition_id, field="graph_definition_id")
        if not isinstance(self.correlation_id, uuid.UUID):
            raise TypeError("correlation_id must be a UUID")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
        ):
            raise ValueError("generation must be a positive integer")
        if not isinstance(self.trigger, ReconciliationTriggerAudit):
            raise TypeError("trigger must be a ReconciliationTriggerAudit")
        if not isinstance(self.inputs, ReconciliationInputVersions):
            raise TypeError("inputs must be ReconciliationInputVersions")
        object.__setattr__(self, "decision", _frozen(self.decision, field="decision"))
        actions = tuple(self.actions)
        if any(not isinstance(item, ReconciliationActionAudit) for item in actions):
            raise TypeError("actions must contain ReconciliationActionAudit values")
        object.__setattr__(self, "actions", actions)
        started_at = _instant(self.started_at, field="generation started_at")
        completed_at = _instant(self.completed_at, field="generation completed_at")
        if completed_at < started_at:
            raise ValueError("generation completion cannot precede generation start")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(
            self,
            "convergence_status",
            GenerationConvergenceStatus(self.convergence_status),
        )
        for field, minimum in (
            ("final_runtime_generation", 1),
            ("final_runtime_sequence", 0),
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
        errors = tuple(self.errors)
        if any(not isinstance(item, ActionFailure) for item in errors):
            raise TypeError("errors must contain ActionFailure values")
        object.__setattr__(self, "errors", errors)

    def to_document(self) -> dict[str, object]:
        phase_timings = {}
        for action in self.actions:
            phase_timings[action.phase] = (
                phase_timings.get(action.phase, 0.0)
                + (action.completed_at - action.started_at).total_seconds() * 1000
            )
        return {
            "schemaVersion": 1,
            "graphDefinitionId": self.graph_definition_id,
            "correlationId": str(self.correlation_id),
            "generation": self.generation,
            "trigger": self.trigger.to_document(),
            "inputs": self.inputs.to_document(),
            "decision": self.decision.to_dict(),
            "actions": [action.to_document() for action in self.actions],
            "timing": {
                "startedAt": self.started_at.isoformat(),
                "completedAt": self.completed_at.isoformat(),
                "durationMs": (self.completed_at - self.started_at).total_seconds() * 1000,
                "phaseDurationMs": dict(sorted(phase_timings.items())),
            },
            "errors": [error.to_document() for error in self.errors],
            "final": {
                "convergenceStatus": self.convergence_status.value,
                "runtimeGeneration": self.final_runtime_generation,
                "runtimeSequence": self.final_runtime_sequence,
            },
        }


def persist_reconciliation_generation_audit(
    audit: ReconciliationGenerationAudit,
    *,
    graph_definition: GraphDefinition,
):
    if not isinstance(audit, ReconciliationGenerationAudit):
        raise TypeError("audit must be a ReconciliationGenerationAudit")
    if not isinstance(graph_definition, GraphDefinition):
        raise TypeError("graph_definition must be a GraphDefinition")
    if str(graph_definition.pk) != audit.graph_definition_id:
        raise ValueError("audit and graph_definition identities do not match")
    severity = {
        GenerationConvergenceStatus.CONVERGED: "info",
        GenerationConvergenceStatus.DEGRADED: "warning",
        GenerationConvergenceStatus.FAILED: "error",
        GenerationConvergenceStatus.SUPERSEDED: "info",
        GenerationConvergenceStatus.CANCELLED: "warning",
    }[audit.convergence_status]
    return record_orchestration_event(
        correlation_id=audit.correlation_id,
        graph_definition=graph_definition,
        event_type="reconciliation.generation.completed",
        severity=severity,
        payload=audit.to_document(),
    )
