from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import FrozenDict

from .condition_evaluation import (
    EligibilityStatus,
    TruthValue,
    UnknownResult,
    evaluate_condition_ast,
)
from .endpoint_matching import EndpointMatchStatus, match_endpoint_candidates
from .logical_endpoint_selection import (
    LogicalEndpointSummary,
    parse_logical_endpoint_selector,
    select_logical_endpoints,
)
from .manual_override_resolution import (
    ManualOverrideResolution,
    resolve_manual_overrides,
)
from .endpoint_projection import (
    EndpointProjectionState,
    LogicalEndpointIntent,
    project_logical_endpoint,
)
from .endpoint_selectors import parse_endpoint_selector
from .graph_documents import normalize_graph_document
from .graph_validation import validate_graph_structure
from .node_catalogue import NodeTypeRegistry
from .path_selection import (
    PathCandidate,
    PathSelectionStatus,
    SelectionTieBreak,
    resolve_exclusive_selection,
)
from .resource_allocation import allocate_graph_resources
from .resolver_inputs import ResolverInputs
from .signal_negotiation import propagate_graph_signal_contracts
from .subgraph_expansion import expand_subgraphs


class ResolutionStage(StrEnum):
    STRUCTURE = "structure"
    SUBGRAPHS = "subgraphs"
    PARAMETERS = "parameters"
    ENDPOINTS = "endpoints"
    CONDITIONS = "conditions"
    PATHS = "paths"
    SIGNALS = "signals"
    RESOURCES = "resources"


@dataclass(frozen=True, slots=True)
class ResolutionIssue:
    stage: ResolutionStage
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ResolvedEndpointBinding:
    logical_endpoint_id: str
    status: str
    runtime_key: str | None
    tied_runtime_keys: tuple[str, ...]
    projection_state: str


@dataclass(frozen=True, slots=True)
class ResolverPipelineResult:
    valid: bool
    expanded_document: FrozenDict
    parameters: FrozenDict
    endpoint_bindings: tuple[ResolvedEndpointBinding, ...]
    facts: FrozenDict
    override_resolution: FrozenDict
    condition_results: FrozenDict
    selector_decisions: FrozenDict
    eligible_node_ids: tuple[str, ...]
    selected_edge_ids: tuple[str, ...]
    signal_contracts: FrozenDict
    resource_assignments: FrozenDict
    resource_decisions: FrozenDict
    issues: tuple[ResolutionIssue, ...]


def _status_for_truth(truth: TruthValue, policy: object) -> EligibilityStatus:
    if truth is TruthValue.TRUE:
        return EligibilityStatus.ELIGIBLE
    if truth is TruthValue.FALSE:
        return EligibilityStatus.INELIGIBLE
    return EligibilityStatus(UnknownResult(policy).value)


def _logical_endpoint_matches(inputs: ResolverInputs):
    bindings: list[ResolvedEndpointBinding] = []
    matches = {}
    projections = {}
    for endpoint in inputs.logical_endpoints:
        selector_document = (
            endpoint.explicit_binding.to_dict()
            if endpoint.explicit_binding is not None
            else endpoint.selector.to_dict()
        )
        validation = parse_endpoint_selector(selector_document)
        direction_candidates = tuple(
            candidate
            for candidate in inputs.runtime_inventory.candidates
            if candidate.direction.value == endpoint.direction
        )
        if validation.valid:
            match = match_endpoint_candidates(validation.selector, direction_candidates)
            matches[endpoint.endpoint_id] = match
            intent = LogicalEndpointIntent(
                id=endpoint.endpoint_id,
                name=endpoint.name,
                direction=endpoint.direction,
                selector=selector_document,
                last_known_summary={},
            )
            projection = project_logical_endpoint(intent, inputs.runtime_inventory)
            projections[endpoint.endpoint_id] = projection
            bindings.append(
                ResolvedEndpointBinding(
                    logical_endpoint_id=endpoint.endpoint_id,
                    status=match.status.value,
                    runtime_key=(
                        match.selected.runtime_key if match.selected is not None else None
                    ),
                    tied_runtime_keys=tuple(candidate.runtime_key for candidate in match.tied),
                    projection_state=projection.primary_state.value,
                )
            )
        else:
            matches[endpoint.endpoint_id] = None
            bindings.append(
                ResolvedEndpointBinding(
                    logical_endpoint_id=endpoint.endpoint_id,
                    status="invalid_selector",
                    runtime_key=None,
                    tied_runtime_keys=(),
                    projection_state="error",
                )
            )
    return tuple(bindings), matches, projections


def _graph_logical_endpoint_ids(document, inputs: ResolverInputs) -> set[str]:
    """Return endpoint identities that contribute to this graph's route intent.

    The resolver keeps every owned endpoint available as a condition fact and as
    input to tag/group selectors.  Only endpoints actually referenced by this
    expanded graph, however, may contribute bindings, diagnostics, and actions.
    Otherwise an unavailable endpoint saved for another graph degrades every
    active graph owned by the same user.
    """

    endpoint_ids = {endpoint.endpoint_id for endpoint in inputs.logical_endpoints}
    summaries = tuple(
        LogicalEndpointSummary(
            endpoint_id=endpoint.endpoint_id,
            name=endpoint.name,
            direction=endpoint.direction,
            tags=endpoint.tags,
            groups=endpoint.groups,
            update_version=endpoint.update_version,
        )
        for endpoint in inputs.logical_endpoints
    )
    referenced: set[str] = set()
    for node in document.get("nodes", ()):
        if not isinstance(node, Mapping):
            continue
        configuration = node.get("configuration")
        if not isinstance(configuration, Mapping):
            continue
        logical_endpoint_id = configuration.get("logicalEndpointId")
        if isinstance(logical_endpoint_id, str):
            referenced.add(logical_endpoint_id)
        for candidate in configuration.get("candidates", ()):
            if not isinstance(candidate, Mapping):
                continue
            endpoint_id = candidate.get("endpoint")
            if isinstance(endpoint_id, str):
                referenced.add(endpoint_id)
            selector_document = candidate.get("endpointSelector")
            if isinstance(selector_document, Mapping):
                validation = parse_logical_endpoint_selector(selector_document)
                if validation.valid:
                    selection = select_logical_endpoints(validation.selector, summaries)
                    referenced.update(item.endpoint_id for item in selection.selected)
        for profile in configuration.get("profiles", ()):
            if not isinstance(profile, Mapping):
                continue
            output = profile.get("output")
            if isinstance(output, str) and output in endpoint_ids:
                referenced.add(output)
    return referenced


def _world_facts(inputs, override_resolution, matches, projections):
    facts = inputs.signal_facts.facts.to_dict()
    for name, value in override_resolution.parameter_values.items():
        facts[f"parameter.{name}"] = value
    for name, value in override_resolution.modes.items():
        facts[f"mode.{name}"] = value
    endpoint_by_id = {endpoint.endpoint_id: endpoint for endpoint in inputs.logical_endpoints}
    for endpoint_id, endpoint in endpoint_by_id.items():
        projection = projections.get(endpoint_id)
        match = matches.get(endpoint_id)
        selected = match.selected if match is not None else None
        facts[f"endpoint.{endpoint_id}.availability"] = (
            (
                EndpointProjectionState.ROUTE_AVAILABLE.value
                if EndpointProjectionState.ROUTE_AVAILABLE in projection.states
                else projection.primary_state.value
            )
            if projection is not None
            else "error"
        )
        facts[f"endpoint.{endpoint_id}.activeSignal"] = bool(
            selected is not None and selected.has_active_signal
        )
        facts[f"endpoint.{endpoint_id}.direction"] = endpoint.direction
        facts[f"endpoint.{endpoint_id}.volume"] = selected.volume if selected is not None else None
        facts[f"endpoint.{endpoint_id}.mute"] = selected.mute if selected is not None else None
        facts[f"endpoint.{endpoint_id}.capabilities"] = (
            selected.projection_document()["audioCapabilities"] if selected is not None else {}
        )
    for processor in inputs.processors:
        prefix = f"processor.{processor.processor_id}"
        facts[f"{prefix}.health"] = processor.health
        facts[f"{prefix}.ready"] = processor.ready
        for name, value in processor.facts.items():
            path = name if "." in name else f"{prefix}.{name}"
            facts[path] = value
    for override in inputs.overrides:
        prefix = f"override.{override.scope_id}"
        facts[f"{prefix}.active"] = False
        facts[f"{prefix}.value"] = None
        facts[f"{prefix}.expiresAt"] = override.expires_at
    for override in override_resolution.winners:
        prefix = f"override.{override.scope_id}"
        facts[f"{prefix}.active"] = True
        facts[f"{prefix}.value"] = override.value
        facts[f"{prefix}.expiresAt"] = override.expires_at
    for resource in inputs.resource_policy.resources:
        prefix = f"resource.{resource.resource_id}"
        facts[f"{prefix}.availability"] = (
            "available" if resource.health in {"ready", "available", "healthy"} else "unavailable"
        )
        facts[f"{prefix}.capacity"] = resource.capacity
        facts[f"{prefix}.allocated"] = resource.allocated
    return facts


def _evaluate_conditions(document, facts, issues):
    named: dict[str, TruthValue] = {}
    results: dict[str, str] = {}
    for index, condition in enumerate(document.get("conditions", [])):
        if not isinstance(condition, Mapping):
            continue
        condition_id = condition.get("id")
        expression = condition.get("expression")
        if not isinstance(condition_id, str) or not isinstance(expression, Mapping):
            continue
        try:
            truth = evaluate_condition_ast({"version": 1, "expression": expression}, facts)
        except ValueError as error:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.CONDITIONS,
                    f"$.conditions[{index}].expression",
                    "condition_invalid",
                    str(error),
                )
            )
            continue
        named[condition_id] = truth
        results[f"condition:{condition_id}"] = truth.value
    return named, results


def _selector_node_decisions(
    document,
    inputs,
    matches,
    facts,
    override_resolution: ManualOverrideResolution,
    issues,
):
    decisions = {}
    summaries = tuple(
        LogicalEndpointSummary(
            endpoint_id=endpoint.endpoint_id,
            name=endpoint.name,
            direction=endpoint.direction,
            tags=endpoint.tags,
            groups=endpoint.groups,
            update_version=endpoint.update_version,
        )
        for endpoint in inputs.logical_endpoints
    )
    supported = {
        "core.ordered-selector",
        "core.fallback-selector",
        "core.exclusive-choice",
    }
    for node_index, node in enumerate(document.get("nodes", [])):
        if not isinstance(node, Mapping) or node.get("type") not in supported:
            continue
        configuration = node.get("configuration")
        if not isinstance(configuration, Mapping):
            continue
        candidates: list[PathCandidate] = []
        next_order = 0
        for candidate_index, raw in enumerate(configuration.get("candidates", [])):
            if not isinstance(raw, Mapping):
                continue
            endpoint_ids = []
            if isinstance(raw.get("endpoint"), str):
                endpoint_ids = [raw["endpoint"]]
            elif isinstance(raw.get("endpointSelector"), Mapping):
                validation = parse_logical_endpoint_selector(raw["endpointSelector"])
                if validation.valid:
                    selection = select_logical_endpoints(validation.selector, summaries)
                    endpoint_ids = [item.endpoint_id for item in selection.selected]
                else:
                    issues.append(
                        ResolutionIssue(
                            ResolutionStage.PATHS,
                            f"$.nodes[{node_index}].configuration.candidates"
                            f"[{candidate_index}].endpointSelector",
                            "logical_selector_invalid",
                            "; ".join(issue.message for issue in validation.issues),
                        )
                    )
            if not endpoint_ids:
                endpoint_ids = [f"unresolved:{candidate_index}"]
            for endpoint_id in endpoint_ids:
                match = matches.get(endpoint_id)
                eligibility = EligibilityStatus.INELIGIBLE
                evidence = []
                if match is not None and match.status is EndpointMatchStatus.MATCHED:
                    eligibility = EligibilityStatus.ELIGIBLE
                    evidence.append("endpoint:matched")
                elif match is not None and match.status is EndpointMatchStatus.AMBIGUOUS:
                    eligibility = EligibilityStatus.ERROR
                    evidence.append("endpoint:ambiguous")
                else:
                    evidence.append("endpoint:unavailable")
                eligible_when = raw.get("eligibleWhen")
                if isinstance(eligible_when, Mapping):
                    try:
                        truth = evaluate_condition_ast(
                            {"version": 1, "expression": eligible_when},
                            facts,
                        )
                        condition_status = _status_for_truth(
                            truth,
                            raw.get("unknownResult"),
                        )
                        evidence.append(f"condition:{truth.value}")
                        if condition_status is not EligibilityStatus.ELIGIBLE:
                            eligibility = condition_status
                    except (TypeError, ValueError) as error:
                        eligibility = EligibilityStatus.ERROR
                        evidence.append("condition:error")
                        issues.append(
                            ResolutionIssue(
                                ResolutionStage.CONDITIONS,
                                f"$.nodes[{node_index}].configuration.candidates"
                                f"[{candidate_index}].eligibleWhen",
                                "candidate_condition_invalid",
                                str(error),
                            )
                        )
                candidates.append(
                    PathCandidate(
                        reference_id=endpoint_id,
                        priority=raw.get("priority", 0),
                        declaration_order=next_order,
                        eligibility=eligibility,
                        evidence=tuple(evidence),
                    )
                )
                next_order += 1
        locked_target = override_resolution.endpoint_selections.get(node.get("id"))
        if isinstance(locked_target, str):
            if all(candidate.reference_id != locked_target for candidate in candidates):
                match = matches.get(locked_target)
                candidates.append(
                    PathCandidate(
                        reference_id=locked_target,
                        priority=max(
                            (candidate.priority for candidate in candidates),
                            default=0,
                        )
                        + 1,
                        declaration_order=next_order,
                        eligibility=(
                            EligibilityStatus.ELIGIBLE
                            if match is not None and match.status is EndpointMatchStatus.MATCHED
                            else EligibilityStatus.WAITING
                        ),
                        evidence=("manual_override:locked",),
                    )
                )
            candidates = [
                PathCandidate(
                    reference_id=candidate.reference_id,
                    priority=candidate.priority,
                    declaration_order=candidate.declaration_order,
                    eligibility=(
                        candidate.eligibility
                        if candidate.reference_id == locked_target
                        and candidate.eligibility is EligibilityStatus.ELIGIBLE
                        else (
                            EligibilityStatus.WAITING
                            if candidate.reference_id == locked_target
                            else EligibilityStatus.INELIGIBLE
                        )
                    ),
                    evidence=(*candidate.evidence, "manual_override:locked"),
                )
                for candidate in candidates
            ]
        default_tie_break = (
            SelectionTieBreak.CONFLICT
            if node.get("type") == "core.exclusive-choice"
            else SelectionTieBreak.DECLARATION_ORDER
        )
        try:
            decision = resolve_exclusive_selection(
                candidates,
                mode=configuration.get("mode", "exclusive"),
                tie_break=configuration.get("tieBreak", default_tie_break),
            )
        except (TypeError, ValueError) as error:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.PATHS,
                    f"$.nodes[{node_index}].configuration",
                    "selector_invalid",
                    str(error),
                )
            )
            continue
        decisions[node["id"]] = decision.to_document()
        if decision.status is not PathSelectionStatus.RESOLVED:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.PATHS,
                    f"$.nodes[{node_index}]",
                    f"selector_{decision.status.value}",
                    f"Selector resolved to {decision.status.value}.",
                )
            )
    return decisions


def _condition_use_status(condition_use, *, facts, named, path, results, issues):
    if not isinstance(condition_use, Mapping):
        return EligibilityStatus.ELIGIBLE
    truth = None
    if isinstance(condition_use.get("reference"), str):
        truth = named.get(condition_use["reference"])
        if truth is None:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.CONDITIONS,
                    f"{path}.reference",
                    "condition_reference_unresolved",
                    f"Condition {condition_use['reference']!r} is unavailable.",
                )
            )
            truth = TruthValue.UNKNOWN
    elif isinstance(condition_use.get("expression"), Mapping):
        try:
            truth = evaluate_condition_ast(
                {"version": 1, "expression": condition_use["expression"]},
                facts,
            )
        except ValueError as error:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.CONDITIONS,
                    f"{path}.expression",
                    "condition_invalid",
                    str(error),
                )
            )
            truth = TruthValue.UNKNOWN
    else:
        return EligibilityStatus.ELIGIBLE
    results[path] = truth.value
    try:
        status = _status_for_truth(truth, condition_use.get("unknownResult"))
    except (TypeError, ValueError) as error:
        issues.append(
            ResolutionIssue(
                ResolutionStage.CONDITIONS,
                f"{path}.unknownResult",
                "unknown_policy_invalid",
                str(error),
            )
        )
        return EligibilityStatus.ERROR
    if status in {EligibilityStatus.WAITING, EligibilityStatus.ERROR}:
        issues.append(
            ResolutionIssue(
                ResolutionStage.CONDITIONS,
                path,
                f"condition_{status.value}",
                f"Condition resolved to {truth.value} with {status.value} policy.",
            )
        )
    return status


def _complete_path_edges(document, candidate_edge_ids, eligible_nodes):
    edges = [
        edge
        for edge in document.get("edges", [])
        if isinstance(edge, Mapping) and edge.get("id") in candidate_edge_ids
    ]
    declared_source_ids = set()
    declared_sink_ids = set()
    for node in document.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        configuration = node.get("configuration")
        if node.get("type") != "core.endpoint-reference" or not isinstance(configuration, Mapping):
            continue
        if configuration.get("direction") == "input":
            declared_source_ids.add(node["id"])
        elif configuration.get("direction") == "output":
            declared_sink_ids.add(node["id"])
    if not declared_source_ids or not declared_sink_ids:
        return set(candidate_edge_ids)
    source_ids = declared_source_ids.intersection(eligible_nodes)
    sink_ids = declared_sink_ids.intersection(eligible_nodes)
    if not source_ids or not sink_ids:
        return set()

    forward = set(source_ids)
    changed = True
    while changed:
        changed = False
        for edge in edges:
            source = edge.get("from")
            target = edge.get("to")
            source_id = source.get("node") if isinstance(source, Mapping) else None
            target_id = target.get("node") if isinstance(target, Mapping) else None
            if source_id in forward and target_id not in forward:
                forward.add(target_id)
                changed = True
    backward = set(sink_ids)
    changed = True
    while changed:
        changed = False
        for edge in edges:
            source = edge.get("from")
            target = edge.get("to")
            source_id = source.get("node") if isinstance(source, Mapping) else None
            target_id = target.get("node") if isinstance(target, Mapping) else None
            if target_id in backward and source_id not in backward:
                backward.add(source_id)
                changed = True
    return {
        edge["id"]
        for edge in edges
        if isinstance(edge.get("from"), Mapping)
        and isinstance(edge.get("to"), Mapping)
        and edge["from"].get("node") in forward
        and edge["to"].get("node") in backward
    }


def run_resolution_pipeline(
    inputs: ResolverInputs,
    *,
    registry: NodeTypeRegistry | None = None,
) -> ResolverPipelineResult:
    """Resolve one immutable desired/world input through side-effect-free stages."""

    if not isinstance(inputs, ResolverInputs):
        raise TypeError("inputs must be ResolverInputs")
    if registry is None:
        from .audio_node_catalogue import audio_node_type_registry

        registry = audio_node_type_registry()
    issues: list[ResolutionIssue] = []
    root_document = normalize_graph_document(
        inputs.graph.document.to_dict(),
        include_layout=True,
    )
    structure = validate_graph_structure(root_document, registry=registry)
    issues.extend(
        ResolutionIssue(
            ResolutionStage.STRUCTURE,
            issue.path,
            issue.code,
            issue.message,
        )
        for issue in structure.issues
    )

    subgraphs = {
        (revision.definition_id, revision.revision_id): normalize_graph_document(
            revision.document.to_dict(),
            include_layout=True,
        )
        for revision in inputs.subgraph_revisions
    }
    expansion = expand_subgraphs(
        root_document,
        activation_bindings=inputs.activation.parameter_bindings.to_dict(),
        loader=lambda definition_id, revision_id: subgraphs.get((definition_id, revision_id)),
        registry=registry,
    )
    for issue in expansion.issues:
        stage = (
            ResolutionStage.PARAMETERS
            if issue.code.startswith("parameter_")
            else ResolutionStage.SUBGRAPHS
        )
        issues.append(ResolutionIssue(stage, issue.path, issue.code, issue.message))
    expanded_document = normalize_graph_document(
        expansion.document,
        include_layout=False,
    )
    parameter_document = {
        name: {
            "value": expanded.value,
            "provenance": expanded.provenance.to_document(),
        }
        for name, expanded in sorted(expansion.parameters.items())
    }

    all_endpoint_bindings, matches, projections = _logical_endpoint_matches(inputs)

    base_parameters = {
        name.removeprefix("$root."): expanded.value
        for name, expanded in expansion.parameters.items()
        if name.startswith("$root.")
    }
    override_resolution = resolve_manual_overrides(
        inputs.overrides,
        evaluated_at=inputs.evaluated_at,
        endpoint_ids=(endpoint.endpoint_id for endpoint in inputs.logical_endpoints),
        base_parameter_values=base_parameters,
        base_modes=inputs.activation.scene_bindings.to_dict(),
    )
    graph_endpoint_ids = _graph_logical_endpoint_ids(expanded_document, inputs)
    graph_endpoint_ids.update(
        endpoint_id
        for endpoint_id in override_resolution.endpoint_selections.values()
        if isinstance(endpoint_id, str)
    )
    endpoint_bindings = tuple(
        binding
        for binding in all_endpoint_bindings
        if binding.logical_endpoint_id in graph_endpoint_ids
    )
    for binding in endpoint_bindings:
        if binding.status in {
            EndpointMatchStatus.NO_MATCH.value,
            EndpointMatchStatus.AMBIGUOUS.value,
            "invalid_selector",
        }:
            issues.append(
                ResolutionIssue(
                    ResolutionStage.ENDPOINTS,
                    f"$.logicalEndpoints[{binding.logical_endpoint_id!r}]",
                    f"endpoint_{binding.status}",
                    f"Endpoint resolution is {binding.status}.",
                )
            )
    facts = _world_facts(inputs, override_resolution, matches, projections)
    named, condition_results = _evaluate_conditions(expanded_document, facts, issues)
    selector_decisions = _selector_node_decisions(
        expanded_document,
        inputs,
        matches,
        facts,
        override_resolution,
        issues,
    )
    eligible_nodes = set()
    for index, node in enumerate(expanded_document.get("nodes", [])):
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            continue
        status = _condition_use_status(
            node.get("condition"),
            facts=facts,
            named=named,
            path=f"$.nodes[{index}].condition",
            results=condition_results,
            issues=issues,
        )
        endpoint_available = True
        configuration = node.get("configuration")
        if (
            node.get("type") == "core.endpoint-reference"
            and isinstance(configuration, Mapping)
            and isinstance(configuration.get("logicalEndpointId"), str)
        ):
            match = matches.get(configuration["logicalEndpointId"])
            endpoint_available = bool(
                match is not None and match.status is EndpointMatchStatus.MATCHED
            )
        if status is EligibilityStatus.ELIGIBLE and endpoint_available:
            eligible_nodes.add(node["id"])

    candidate_edges = set()
    for index, edge in enumerate(expanded_document.get("edges", [])):
        if not isinstance(edge, Mapping) or not isinstance(edge.get("id"), str):
            continue
        status = _condition_use_status(
            edge.get("condition"),
            facts=facts,
            named=named,
            path=f"$.edges[{index}].condition",
            results=condition_results,
            issues=issues,
        )
        source = edge.get("from", {}).get("node") if isinstance(edge.get("from"), Mapping) else None
        target = edge.get("to", {}).get("node") if isinstance(edge.get("to"), Mapping) else None
        if (
            status is EligibilityStatus.ELIGIBLE
            and source in eligible_nodes
            and target in eligible_nodes
        ):
            candidate_edges.add(edge["id"])

    selected_edges = _complete_path_edges(
        expanded_document,
        candidate_edges,
        eligible_nodes,
    )

    propagation = propagate_graph_signal_contracts(
        expanded_document,
        registry=registry,
        edge_ids=selected_edges,
    )
    signal_contracts = propagation.edge_contracts.to_dict()
    for issue in propagation.issues:
        issues.append(
            ResolutionIssue(
                ResolutionStage.SIGNALS,
                f"$.edges[{issue.edge_id!r}]",
                "signal_incompatible",
                f"Incompatible signal contract: {', '.join(issue.reasons)}.",
            )
        )

    active_nodes = {
        endpoint.get("node")
        for edge in expanded_document.get("edges", [])
        if isinstance(edge, Mapping) and edge.get("id") in selected_edges
        for endpoint in (edge.get("from"), edge.get("to"))
        if isinstance(endpoint, Mapping)
    }
    allocation = allocate_graph_resources(
        expanded_document,
        active_nodes,
        inputs.resource_policy,
    )
    for issue in allocation.issues:
        issues.append(
            ResolutionIssue(
                ResolutionStage.RESOURCES,
                f"$.nodes[{issue.node_id!r}]",
                issue.code,
                issue.message,
            )
        )
    stage_order = {stage: index for index, stage in enumerate(ResolutionStage)}
    canonical_issues = tuple(
        sorted(
            issues,
            key=lambda issue: (
                stage_order[issue.stage],
                issue.path,
                issue.code,
                issue.message,
            ),
        )
    )
    return ResolverPipelineResult(
        valid=not issues,
        expanded_document=FrozenDict(expanded_document),
        parameters=FrozenDict(parameter_document),
        endpoint_bindings=tuple(
            sorted(endpoint_bindings, key=lambda binding: binding.logical_endpoint_id)
        ),
        facts=FrozenDict(facts),
        override_resolution=FrozenDict(override_resolution.to_document()),
        condition_results=FrozenDict(condition_results),
        selector_decisions=FrozenDict(selector_decisions),
        eligible_node_ids=tuple(sorted(eligible_nodes)),
        selected_edge_ids=tuple(sorted(selected_edges)),
        signal_contracts=FrozenDict(signal_contracts),
        resource_assignments=allocation.assignments,
        resource_decisions=allocation.decisions,
        issues=canonical_issues,
    )
