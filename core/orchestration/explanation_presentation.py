from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from wyreplumber.runtime import FrozenDict

from .resolver_inputs import ResolverInputs
from .resolver_pipeline import ResolverPipelineResult

EXPLANATION_PRESENTATION_SCHEMA_VERSION = 1

_PROCESSOR_PRESENTATION = {
    "processor.pcm-auto-decoder": ("Adaptive PCM decoder", "decode"),
    "processor.camilladsp-profile-selector": ("CamillaDSP", "process"),
}
_REASON_TEXT = {
    "error": "The candidate could not be evaluated safely.",
    "equal_best_priority": "It has the same priority as another candidate.",
    "ineligible": "Its route conditions are not currently satisfied.",
    "lower_priority": "A higher-priority available output was selected.",
    "not_selected": "Another available candidate was preferred.",
    "unavailable": "The device is disconnected or unavailable.",
    "waiting": "The system is waiting for current device information.",
}


def _plain(value):
    return value.to_dict() if isinstance(value, FrozenDict) else value


def _endpoint_maps(inputs: ResolverInputs):
    by_id = {endpoint.endpoint_id: endpoint for endpoint in inputs.logical_endpoints}
    return by_id, {endpoint.endpoint_id: endpoint.name for endpoint in inputs.logical_endpoints}


def _ordered_active_node_ids(pipeline: ResolverPipelineResult) -> list[str]:
    selected = set(pipeline.selected_edge_ids)
    edges = [edge for edge in pipeline.expanded_document["edges"] if edge["id"] in selected]
    if not edges:
        return []
    successors: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    for edge in edges:
        source = edge["from"]["node"]
        target = edge["to"]["node"]
        successors[source].append(target)
        indegree.setdefault(source, 0)
        indegree[target] = indegree.get(target, 0) + 1
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        if node_id in ordered:
            continue
        ordered.append(node_id)
        for target in sorted(successors[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    ordered.extend(sorted(set(indegree) - set(ordered)))
    return ordered


def _profile_detail(configuration: Mapping[str, object], selected_endpoint_ids: set[str]):
    profiles = configuration.get("profiles", ())
    if not isinstance(profiles, (list, tuple)):
        return None
    for profile in profiles:
        if not isinstance(profile, Mapping) or profile.get("output") not in selected_endpoint_ids:
            continue
        value = profile.get("profile")
        if isinstance(value, str) and value:
            return value.rsplit(":", 1)[-1].replace("-", " ").title()
    return None


def _decoder_detail(inputs: ResolverInputs) -> str:
    facts = inputs.signal_facts.facts
    codec = facts.get("signal.source.content.codec") or facts.get("signal.source.codec")
    channels = facts.get("signal.source.channels") or facts.get("signal.decoded.channels")
    if isinstance(codec, str) and codec.lower() not in {"pcm", "raw"}:
        detail = f"Decode {codec.upper()} to PCM"
    else:
        detail = "PCM bypass when decoding is not required"
    if isinstance(channels, int) and not isinstance(channels, bool):
        detail += f" · {channels} channels"
    return detail


def _route_segments(inputs: ResolverInputs, pipeline: ResolverPipelineResult):
    endpoint_by_id, endpoint_names = _endpoint_maps(inputs)
    selected_endpoint_ids = {
        item["referenceId"]
        for decision in pipeline.selector_decisions.values()
        for item in decision["selected"]
    }
    nodes = {node["id"]: node for node in pipeline.expanded_document["nodes"]}
    segments = []
    for node_id in _ordered_active_node_ids(pipeline):
        node = nodes[node_id]
        node_type = node["type"]
        configuration = node.get("configuration", {})
        if node_type == "core.endpoint-reference":
            endpoint_id = configuration.get("logicalEndpointId")
            endpoint = endpoint_by_id.get(endpoint_id)
            direction = (
                endpoint.direction if endpoint is not None else configuration.get("direction")
            )
            segments.append(
                {
                    "kind": "endpoint",
                    "name": endpoint_names.get(endpoint_id, "Unknown endpoint"),
                    "role": "source" if direction == "input" else "output",
                    "detail": None,
                    "referenceId": endpoint_id,
                    "nodeId": node_id,
                }
            )
            continue
        decision = pipeline.selector_decisions.get(node_id)
        if decision is not None and decision["selected"]:
            endpoint_id = decision["selected"][0]["referenceId"]
            endpoint = endpoint_by_id.get(endpoint_id)
            segments.append(
                {
                    "kind": "endpoint",
                    "name": endpoint_names.get(endpoint_id, "Unknown endpoint"),
                    "role": (
                        "source"
                        if endpoint is not None and endpoint.direction == "input"
                        else "output"
                    ),
                    "detail": None,
                    "referenceId": endpoint_id,
                    "nodeId": node_id,
                }
            )
            continue
        display_name, role = _PROCESSOR_PRESENTATION.get(
            node_type,
            (node_type.replace(".", " ").replace("-", " ").title(), "process"),
        )
        detail = None
        if node_type == "processor.pcm-auto-decoder":
            detail = _decoder_detail(inputs)
        elif node_type == "processor.camilladsp-profile-selector":
            detail = _profile_detail(configuration, selected_endpoint_ids)
        segments.append(
            {
                "kind": "processor",
                "name": display_name,
                "role": role,
                "detail": detail,
                "referenceId": None,
                "nodeId": node_id,
            }
        )
    return segments


def _selection_presentation(
    inputs: ResolverInputs,
    pipeline: ResolverPipelineResult,
    route: list[dict[str, object]],
):
    endpoint_by_id, endpoint_names = _endpoint_maps(inputs)
    alternatives = []
    selected = []
    selection_node_id = None
    for node_id, decision in pipeline.selector_decisions.items():
        for candidate in decision["selected"]:
            endpoint_id = candidate["referenceId"]
            endpoint = endpoint_by_id.get(endpoint_id)
            selected.append((node_id, endpoint_id, endpoint, decision, candidate))
        for rejected in decision["rejected"]:
            candidate = rejected["candidate"]
            endpoint_id = candidate["referenceId"]
            reason = rejected["reason"]
            alternatives.append(
                {
                    "name": endpoint_names.get(endpoint_id, endpoint_id),
                    "referenceId": endpoint_id,
                    "status": (
                        "unavailable"
                        if candidate["eligibility"] in {"ineligible", "waiting"}
                        else "not-selected"
                    ),
                    "reasonCode": reason,
                    "reason": _REASON_TEXT.get(reason, reason.replace("_", " ").capitalize()),
                    "technicalEvidence": list(candidate["evidence"]),
                    "selectorNodeId": node_id,
                    "role": (
                        "source"
                        if endpoint_by_id.get(endpoint_id) is not None
                        and endpoint_by_id[endpoint_id].direction == "input"
                        else "output"
                    ),
                }
            )
    output_selected = [
        item for item in selected if item[2] is not None and item[2].direction == "output"
    ]
    winner_item = output_selected[-1] if output_selected else (selected[-1] if selected else None)
    winner = endpoint_names.get(winner_item[1], winner_item[1]) if winner_item else None
    if winner_item:
        selection_node_id = winner_item[0]
        evidence = winner_item[4]["evidence"]
        mode = winner_item[3]["mode"]
        if "manual_override:locked" in evidence:
            trigger = "Manual output override"
            reason_code = "manual-override"
            reason = "The active manual override selected this output."
        elif any(item["status"] == "unavailable" for item in alternatives):
            trigger = "Preferred device availability changed"
            reason_code = "first-available"
            reason = "The first available preferred output was selected."
        else:
            trigger = "Graph conditions and device availability"
            reason_code = mode
            reason = "The highest-priority eligible output was selected."
    else:
        route_outputs = [segment for segment in route if segment["role"] == "output"]
        route_output = route_outputs[-1] if route_outputs else None
        winner = route_output["name"] if route_output else None
        trigger = "Graph conditions and device availability"
        reason_code = "graph-route" if route_output else "no-selection"
        reason = (
            "The active graph selected this output."
            if route_output
            else "No eligible output has been selected yet."
        )
    return (
        {
            "trigger": trigger,
            "winner": winner,
            "winnerReferenceId": (
                winner_item[1]
                if winner_item
                else (route_output["referenceId"] if route_output else None)
            ),
            "reasonCode": reason_code,
            "reason": reason,
            "selectorNodeId": selection_node_id,
        },
        sorted(alternatives, key=lambda item: (item["selectorNodeId"], item["name"])),
    )


def _signals(inputs: ResolverInputs, pipeline: ResolverPipelineResult):
    node_names = {node["id"]: node["type"] for node in pipeline.expanded_document["nodes"]}
    edge_by_id = {edge["id"]: edge for edge in pipeline.expanded_document["edges"]}
    descriptors = []
    for edge_id in pipeline.selected_edge_ids:
        contract = _plain(pipeline.signal_contracts.get(edge_id, {}))
        edge = edge_by_id.get(edge_id)
        if edge is None:
            continue
        source = contract.get("source", {})
        negotiated = contract.get("negotiated", {})
        changed = {
            key: {"from": source.get(key), "to": negotiated.get(key)}
            for key in ("content", "codecs", "sampleFormats", "rates", "layouts")
            if source.get(key) != negotiated.get(key)
        }
        descriptors.append(
            {
                "edgeId": edge_id,
                "fromNodeId": edge["from"]["node"],
                "toNodeId": edge["to"]["node"],
                "from": node_names.get(edge["from"]["node"]),
                "to": node_names.get(edge["to"]["node"]),
                "signal": negotiated,
                "changes": changed,
                "compatible": bool(contract.get("compatible", False)),
            }
        )
    input_facts = {
        key.removeprefix("signal.source."): value
        for key, value in inputs.signal_facts.facts.items()
        if key.startswith("signal.source.")
    }
    return {"input": input_facts, "path": descriptors}


def _headline(status: str, route: list[dict], alternatives: list[dict], errors: list[dict]):
    sources = [segment["name"] for segment in route if segment["role"] == "source"]
    outputs = [segment["name"] for segment in route if segment["role"] == "output"]
    if any(issue["code"] == "resource_unavailable" for issue in errors):
        state, title, summary = (
            "waiting",
            "Waiting for an audio processor",
            "The selected route will start when its required processor is ready.",
        )
    elif status in {"resolved", "degraded"} and route:
        state = "active" if status == "resolved" else "degraded"
        title = (
            f"{sources[0]} is playing on {outputs[-1]}"
            if sources and outputs
            else "The selected audio route is active"
        )
        unavailable = [
            item
            for item in alternatives
            if item["status"] == "unavailable" and item["role"] == "output"
        ]
        summary = (
            f"{unavailable[0]['name']} is unavailable, so {outputs[-1]} was selected."
            if unavailable and outputs
            else "The selected route is ready."
        )
    elif status == "resolved":
        state, title, summary = (
            "inactive",
            "No audio path is active",
            "Activate the graph or satisfy its route conditions to start audio.",
        )
    elif status == "waiting":
        state, title, summary = (
            "waiting",
            "Waiting for the audio route",
            "Connect the required device or wait for the required processor to become ready.",
        )
    else:
        state = "failed"
        title = "The audio route could not be prepared"
        summary = errors[0]["message"] if errors else "Review the graph and runtime details."
    return {"status": state, "title": title, "summary": summary}


def build_explanation_presentation(
    inputs: ResolverInputs,
    pipeline: ResolverPipelineResult,
    *,
    status: str,
    warnings: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> dict[str, object]:
    route = _route_segments(inputs, pipeline)
    selection, alternatives = _selection_presentation(inputs, pipeline, route)
    active_processors = [segment for segment in route if segment["kind"] == "processor"]
    actionable_errors = [
        {
            **issue,
            "severity": "error" if issue in errors else "warning",
            "nextStep": (
                "Connect or enable the required device and retry."
                if issue["code"] in {"endpoint_no_match", "selector_unavailable"}
                else (
                    "Wait for the processor to report ready, then retry."
                    if issue["code"] == "resource_unavailable"
                    else "Review the graph configuration and technical details."
                )
            ),
        }
        for issue in [*errors, *warnings]
    ]
    override_resolution = pipeline.override_resolution.to_dict()
    overrides = [
        {
            "id": item.get("overrideId"),
            "scopeType": item.get("scopeType"),
            "scopeId": item.get("scopeId"),
            "reason": item.get("reason"),
            "value": item.get("value"),
        }
        for item in override_resolution.get("winners", [])
    ]
    headline = _headline(status, route, alternatives, actionable_errors)
    return {
        "schemaVersion": EXPLANATION_PRESENTATION_SCHEMA_VERSION,
        "headline": headline,
        "route": route,
        "selection": selection,
        "alternatives": alternatives,
        "signals": _signals(inputs, pipeline),
        "processors": active_processors,
        "overrides": overrides,
        "transition": {
            "status": (
                "ready" if headline["status"] in {"active", "degraded"} else headline["status"]
            ),
            "durationMs": None,
            "observedAt": inputs.evaluated_at,
            "message": None,
        },
        "errors": actionable_errors,
        "technicalReferences": {
            "worldVersion": inputs.world_version.token,
            "selectedEdgeIds": list(pipeline.selected_edge_ids),
            "selectorNodeIds": sorted(pipeline.selector_decisions),
            "resourceNodeIds": sorted(pipeline.resource_decisions),
            "issuePaths": sorted({issue["path"] for issue in [*errors, *warnings]}),
        },
    }
