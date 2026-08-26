from __future__ import annotations

from dataclasses import dataclass

from wyreplumber.runtime import FrozenDict

from .graph_documents import graph_content_digest
from .runtime_world import OrchestratorWorldSnapshot


class StateCorrelationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrchestrationStateCorrelation:
    schema_version: int
    document: FrozenDict
    digest: str

    @property
    def graph_definition_id(self) -> str:
        return self.document["desired"]["definitionId"]

    @property
    def transition_generation(self) -> int:
        return self.document["transition"]["generation"]


def _position_is_older(candidate: tuple[int, int], baseline: tuple[int, int]) -> bool:
    return candidate[0] < baseline[0] or (
        candidate[0] == baseline[0] and candidate[1] < baseline[1]
    )


def correlate_orchestration_state(
    *,
    activation,
    resolution_world: OrchestratorWorldSnapshot,
    resolved_plan,
    applied_state=None,
    latest_runtime_world: OrchestratorWorldSnapshot | None = None,
) -> OrchestrationStateCorrelation:
    """Build one validated view across desired, resolved, applied, and runtime state."""

    from api.models import AppliedPlanState, GraphActivation, ResolvedPlan

    if not isinstance(activation, GraphActivation):
        raise TypeError("activation must be a GraphActivation")
    if not isinstance(resolution_world, OrchestratorWorldSnapshot):
        raise TypeError("resolution_world must be an OrchestratorWorldSnapshot")
    if not isinstance(resolved_plan, ResolvedPlan):
        raise TypeError("resolved_plan must be a ResolvedPlan")
    if applied_state is not None and not isinstance(applied_state, AppliedPlanState):
        raise TypeError("applied_state must be an AppliedPlanState or null")
    latest = latest_runtime_world or resolution_world
    if not isinstance(latest, OrchestratorWorldSnapshot):
        raise TypeError("latest_runtime_world must be an OrchestratorWorldSnapshot or null")

    errors = []
    if resolved_plan.graph_definition_id != activation.definition_id:
        errors.append("resolved plan and activation belong to different graphs")
    if resolved_plan.graph_revision_id != activation.revision_id:
        errors.append("resolved plan does not use the activated revision")
    if resolved_plan.desired_state_version != activation.desired_state_version:
        errors.append("resolved plan desired-state version does not match activation")
    if (
        resolved_plan.world_generation,
        resolved_plan.world_sequence,
    ) != resolution_world.position:
        errors.append("resolved plan does not use the supplied resolution world")
    if _position_is_older(latest.position, resolution_world.position):
        errors.append("latest runtime world precedes the resolution world")
    if applied_state is not None and applied_state.graph_definition_id != activation.definition_id:
        errors.append("applied state and activation belong to different graphs")
    if errors:
        raise StateCorrelationError("; ".join(errors))

    applied_plan = applied_state.current_plan if applied_state is not None else None
    transition_generation = applied_state.transition_generation if applied_state is not None else 0
    applied_matches_resolved = bool(
        applied_plan is not None and applied_plan.pk == resolved_plan.pk
    )
    document = {
        "schemaVersion": 1,
        "desired": {
            "definitionId": str(activation.definition_id),
            "revisionId": str(activation.revision_id),
            "revisionNumber": activation.revision.revision_number,
            "revisionDigest": activation.revision.content_digest,
            "activationId": str(activation.pk),
            "desiredStateVersion": activation.desired_state_version,
        },
        "resolutionWorld": {
            "worldVersion": resolution_world.version,
            "runtimeGeneration": resolution_world.runtime.generation,
            "runtimeSequence": resolution_world.runtime.sequence,
        },
        "resolvedPlan": {
            "id": str(resolved_plan.pk),
            "digest": resolved_plan.plan_digest,
            "status": resolved_plan.status,
            "correlationId": str(resolved_plan.correlation_id),
        },
        "transition": {
            "generation": transition_generation,
            "status": applied_state.status if applied_state is not None else "not-started",
            "correlationId": (
                str(applied_state.correlation_id) if applied_state is not None else None
            ),
        },
        "appliedPlan": (
            {
                "id": str(applied_plan.pk),
                "digest": applied_plan.plan_digest,
                "desiredStateVersion": applied_plan.desired_state_version,
                "runtimeGeneration": applied_plan.world_generation,
                "runtimeSequence": applied_plan.world_sequence,
                "correlationId": str(applied_plan.correlation_id),
            }
            if applied_plan is not None
            else None
        ),
        "runtime": {
            "worldVersion": latest.version,
            "runtimeGeneration": latest.runtime.generation,
            "runtimeSequence": latest.runtime.sequence,
            "connectionState": latest.runtime.health.state.value,
        },
        "state": {
            "appliedMatchesResolved": applied_matches_resolved,
            "newerRuntimeObserved": latest.position != resolution_world.position,
            "converged": bool(
                applied_matches_resolved
                and applied_state is not None
                and applied_state.status == "converged"
                and latest.position == resolution_world.position
            ),
        },
    }
    digest = graph_content_digest(document)
    return OrchestrationStateCorrelation(1, FrozenDict(document), digest)
