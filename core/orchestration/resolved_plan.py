from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import FrozenDict

from .explanation_presentation import build_explanation_presentation
from .graph_documents import graph_content_digest
from .resolver_inputs import ResolverInputs
from .resolver_pipeline import (
    ResolutionIssue,
    ResolutionStage,
    ResolverPipelineResult,
    run_resolution_pipeline,
)

RESOLVED_PLAN_SCHEMA_VERSION = 1


class ResolverPlanStatus(StrEnum):
    RESOLVED = "resolved"
    WAITING = "waiting"
    DEGRADED = "degraded"
    CONFLICTED = "conflicted"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ResolvedPlanOutput:
    status: ResolverPlanStatus
    document: FrozenDict
    explanation: FrozenDict
    digest: str


@dataclass(frozen=True, slots=True)
class CurrentPlanPolicy:
    """Whether a resolver result is safe to expose as the applied current plan."""

    may_become_current: bool
    may_remain_current: bool
    may_execute_actions: bool
    retain_last_safe_plan: bool
    reason: str

    def to_document(self) -> dict[str, object]:
        return {
            "mayBecomeCurrent": self.may_become_current,
            "mayRemainCurrent": self.may_remain_current,
            "mayExecuteActions": self.may_execute_actions,
            "retainLastSafePlan": self.retain_last_safe_plan,
            "reason": self.reason,
        }


_INVALID_ISSUE_CODES = {
    "candidate_condition_invalid",
    "condition_invalid",
    "condition_reference_unresolved",
    "endpoint_invalid_selector",
    "logical_selector_invalid",
    "resource_requirement_invalid",
    "selector_invalid",
    "unknown_policy_invalid",
}
_CONFLICT_ISSUE_CODES = {
    "condition_error",
    "endpoint_ambiguous",
    "selector_conflicted",
}
_WAITING_ISSUE_CODES = {
    "condition_waiting",
    "endpoint_no_match",
    "resource_unavailable",
    "selector_unavailable",
    "selector_waiting",
}


def _issue_is_invalid(issue: ResolutionIssue) -> bool:
    return (
        issue.stage
        in {
            ResolutionStage.STRUCTURE,
            ResolutionStage.SUBGRAPHS,
            ResolutionStage.PARAMETERS,
            ResolutionStage.SIGNALS,
        }
        or issue.code in _INVALID_ISSUE_CODES
    )


def _issue_is_conflict(issue: ResolutionIssue) -> bool:
    return issue.code in _CONFLICT_ISSUE_CODES


def _is_warning(issue: ResolutionIssue) -> bool:
    return not _issue_is_invalid(issue) and not _issue_is_conflict(issue)


def classify_plan_status(
    pipeline: ResolverPipelineResult,
) -> ResolverPlanStatus:
    if any(_issue_is_invalid(issue) for issue in pipeline.issues):
        return ResolverPlanStatus.INVALID
    if any(_issue_is_conflict(issue) for issue in pipeline.issues):
        return ResolverPlanStatus.CONFLICTED
    if not pipeline.selected_edge_ids and any(
        issue.code in _WAITING_ISSUE_CODES for issue in pipeline.issues
    ):
        return ResolverPlanStatus.WAITING
    if any(_is_warning(issue) for issue in pipeline.issues):
        return ResolverPlanStatus.DEGRADED
    return ResolverPlanStatus.RESOLVED


def current_plan_policy(
    pipeline: ResolverPipelineResult,
    status: ResolverPlanStatus | None = None,
) -> CurrentPlanPolicy:
    """Describe current/applied-plan eligibility without performing mutations."""

    status = status or classify_plan_status(pipeline)
    if status is ResolverPlanStatus.RESOLVED:
        return CurrentPlanPolicy(
            may_become_current=True,
            may_remain_current=True,
            may_execute_actions=True,
            retain_last_safe_plan=False,
            reason="The plan is complete and has no resolution diagnostics.",
        )
    if status is ResolverPlanStatus.DEGRADED:
        has_declared_edges = bool(pipeline.expanded_document.get("edges", ()))
        has_complete_path = bool(pipeline.selected_edge_ids) or not has_declared_edges
        has_blocking_resource = any(
            issue.stage is ResolutionStage.RESOURCES for issue in pipeline.issues
        )
        executable = has_complete_path and not has_blocking_resource
        return CurrentPlanPolicy(
            may_become_current=executable,
            may_remain_current=executable,
            may_execute_actions=executable,
            retain_last_safe_plan=not executable,
            reason=(
                "A complete safe fallback remains selected despite degraded inputs."
                if executable
                else "No complete executable fallback is available; retain the last safe plan."
            ),
        )
    if status is ResolverPlanStatus.WAITING:
        reason = (
            "Required runtime facts or dependencies are not yet available; "
            "retain the last safe plan without executing this action intent."
        )
    elif status is ResolverPlanStatus.CONFLICTED:
        reason = (
            "The desired and observed inputs do not select one deterministic plan; "
            "retain the last safe plan."
        )
    else:
        reason = "The desired graph or expanded plan is invalid; retain the last safe plan."
    return CurrentPlanPolicy(
        may_become_current=False,
        may_remain_current=False,
        may_execute_actions=False,
        retain_last_safe_plan=True,
        reason=reason,
    )


def _issue_document(issue: ResolutionIssue) -> dict[str, str]:
    return {
        "stage": issue.stage.value,
        "path": issue.path,
        "code": issue.code,
        "message": issue.message,
    }


def _active_nodes(pipeline: ResolverPipelineResult) -> tuple[str, ...]:
    selected = set(pipeline.selected_edge_ids)
    nodes = set()
    for edge in pipeline.expanded_document["edges"]:
        if edge["id"] not in selected:
            continue
        nodes.add(edge["from"]["node"])
        nodes.add(edge["to"]["node"])
    return tuple(sorted(nodes))


def _action_intent(pipeline: ResolverPipelineResult) -> list[dict[str, object]]:
    actions = []
    bindings_by_id = {
        binding.logical_endpoint_id: binding for binding in pipeline.endpoint_bindings
    }
    for binding in pipeline.endpoint_bindings:
        if binding.runtime_key is not None:
            actions.append(
                {
                    "kind": "endpoint-target",
                    "identity": binding.logical_endpoint_id,
                    "logicalEndpointId": binding.logical_endpoint_id,
                    "runtimeKey": binding.runtime_key,
                }
            )
    for node_id, decision in pipeline.selector_decisions.items():
        for selected in decision["selected"]:
            endpoint_id = selected["referenceId"]
            binding = bindings_by_id.get(endpoint_id)
            actions.append(
                {
                    "kind": "select-endpoint",
                    "identity": node_id,
                    "selectorNodeId": node_id,
                    "logicalEndpointId": endpoint_id,
                    "runtimeKey": binding.runtime_key if binding is not None else None,
                }
            )
    for edge_id in pipeline.selected_edge_ids:
        actions.append({"kind": "connect-path", "identity": edge_id, "edgeId": edge_id})
    for node_id, assignment in pipeline.resource_assignments.items():
        actions.append(
            {
                "kind": "reserve-resource",
                "identity": node_id,
                "nodeId": node_id,
                **assignment.to_dict(),
            }
        )
    controls = pipeline.override_resolution["controls"]
    for scope, value in controls.items():
        actions.append(
            {
                "kind": "manual-control",
                "identity": scope,
                "scope": scope,
                "value": value,
            }
        )
    return sorted(actions, key=lambda action: (action["kind"], action["identity"]))


def _effective_runtime_intent(
    pipeline: ResolverPipelineResult,
    action_intent: list[dict[str, object]],
) -> dict[str, object]:
    """Describe only runtime-affecting intent, excluding observations and explanations."""

    active_node_ids = set(_active_nodes(pipeline))
    selected_edge_ids = set(pipeline.selected_edge_ids)
    expanded = pipeline.expanded_document.to_dict()
    override_resolution = pipeline.override_resolution.to_dict()
    return {
        "activeNodes": [
            {key: node[key] for key in ("id", "type", "version", "configuration") if key in node}
            for node in expanded["nodes"]
            if node["id"] in active_node_ids
        ],
        "selectedEdges": [
            {key: edge[key] for key in ("id", "from", "to") if key in edge}
            for edge in expanded["edges"]
            if edge["id"] in selected_edge_ids
        ],
        "endpointBindings": [
            {
                "logicalEndpointId": binding.logical_endpoint_id,
                "runtimeKey": binding.runtime_key,
            }
            for binding in pipeline.endpoint_bindings
            if binding.runtime_key is not None
        ],
        "signalContracts": pipeline.signal_contracts.to_dict(),
        "resourceAssignments": pipeline.resource_assignments.to_dict(),
        "controls": override_resolution["controls"],
        "actionIntent": action_intent,
    }


def build_resolved_plan(
    inputs: ResolverInputs,
    pipeline: ResolverPipelineResult,
) -> ResolvedPlanOutput:
    if not isinstance(inputs, ResolverInputs):
        raise TypeError("inputs must be ResolverInputs")
    if not isinstance(pipeline, ResolverPipelineResult):
        raise TypeError("pipeline must be ResolverPipelineResult")
    status = classify_plan_status(pipeline)
    retention = current_plan_policy(pipeline, status)
    warnings = sorted(
        (_issue_document(issue) for issue in pipeline.issues if _is_warning(issue)),
        key=lambda item: (item["stage"], item["path"], item["code"]),
    )
    errors = sorted(
        (_issue_document(issue) for issue in pipeline.issues if not _is_warning(issue)),
        key=lambda item: (item["stage"], item["path"], item["code"]),
    )
    all_edge_ids = {
        edge["id"]
        for edge in pipeline.expanded_document["edges"]
        if isinstance(edge, FrozenDict) and isinstance(edge.get("id"), str)
    }
    action_intent = _action_intent(pipeline)
    effective_runtime_intent = _effective_runtime_intent(pipeline, action_intent)
    effective_plan_digest = graph_content_digest(effective_runtime_intent)
    document = {
        "schemaVersion": RESOLVED_PLAN_SCHEMA_VERSION,
        "status": status.value,
        "currentPlanPolicy": retention.to_document(),
        "desired": {
            "definitionId": inputs.graph.definition_id,
            "revisionId": inputs.graph.revision_id,
            "revisionNumber": inputs.graph.revision_number,
            "contentDigest": inputs.graph.content_digest,
            "activationId": inputs.activation.activation_id,
            "desiredStateVersion": inputs.activation.desired_state_version,
        },
        "world": {
            "version": inputs.world_version.token,
            "runtimeGeneration": inputs.world_version.runtime_generation,
            "runtimeSequence": inputs.world_version.runtime_sequence,
            "evaluatedAt": inputs.evaluated_at,
        },
        "expandedGraph": pipeline.expanded_document.to_dict(),
        "parameters": pipeline.parameters.to_dict(),
        "endpointBindings": [
            {
                "logicalEndpointId": binding.logical_endpoint_id,
                "status": binding.status,
                "runtimeKey": binding.runtime_key,
                "tiedRuntimeKeys": list(binding.tied_runtime_keys),
                "projectionState": binding.projection_state,
            }
            for binding in pipeline.endpoint_bindings
        ],
        "selections": pipeline.selector_decisions.to_dict(),
        "paths": {
            "activeNodeIds": list(_active_nodes(pipeline)),
            "selectedEdgeIds": list(pipeline.selected_edge_ids),
            "rejectedEdgeIds": sorted(all_edge_ids - set(pipeline.selected_edge_ids)),
        },
        "signalContracts": pipeline.signal_contracts.to_dict(),
        "resourceAssignments": pipeline.resource_assignments.to_dict(),
        "resourceDecisions": pipeline.resource_decisions.to_dict(),
        "overrides": pipeline.override_resolution.to_dict(),
        "actionIntent": action_intent,
        "effectiveRuntimeIntent": effective_runtime_intent,
        "effectivePlanDigest": effective_plan_digest,
        "warnings": warnings,
        "errors": errors,
    }
    stage_counts = {
        stage.value: {
            "warnings": sum(
                1 for issue in pipeline.issues if issue.stage is stage and _is_warning(issue)
            ),
            "errors": sum(
                1 for issue in pipeline.issues if issue.stage is stage and not _is_warning(issue)
            ),
        }
        for stage in ResolutionStage
    }
    explanation = {
        "kind": "audio-resolution",
        "status": status.value,
        "summary": {
            "selectedEndpoints": sorted(
                binding.logical_endpoint_id
                for binding in pipeline.endpoint_bindings
                if binding.runtime_key is not None
            ),
            "selectedEdges": list(pipeline.selected_edge_ids),
            "warningCount": len(warnings),
            "errorCount": len(errors),
        },
        "stages": [
            {"stage": stage.value, **stage_counts[stage.value]} for stage in ResolutionStage
        ],
        "selectionDecisions": pipeline.selector_decisions.to_dict(),
        "conditionResults": pipeline.condition_results.to_dict(),
        "overrideDecisions": pipeline.override_resolution.to_dict(),
        "presentation": build_explanation_presentation(
            inputs,
            pipeline,
            status=status.value,
            warnings=warnings,
            errors=errors,
        ),
    }
    digest_input = {
        "schemaVersion": RESOLVED_PLAN_SCHEMA_VERSION,
        "status": status.value,
        "document": document,
        "explanation": explanation,
    }
    return ResolvedPlanOutput(
        status=status,
        document=FrozenDict(document),
        explanation=FrozenDict(explanation),
        digest=graph_content_digest(digest_input),
    )


def effective_plan_digest(document: Mapping[str, object]) -> str:
    if not isinstance(document, Mapping):
        raise TypeError("resolved plan document must be an object")
    digest = document.get("effectivePlanDigest")
    if not isinstance(digest, str) or not digest:
        raise ValueError("resolved plan document has no effectivePlanDigest")
    return digest


def resolve_plan(inputs: ResolverInputs, *, registry=None) -> ResolvedPlanOutput:
    return build_resolved_plan(
        inputs,
        run_resolution_pipeline(inputs, registry=registry),
    )
