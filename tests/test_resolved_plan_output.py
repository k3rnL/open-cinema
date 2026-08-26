import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from wyreplumber.runtime import FrozenDict

from core.orchestration.resolved_plan import (
    ResolverPlanStatus,
    build_resolved_plan,
    classify_plan_status,
    current_plan_policy,
)
from core.orchestration.resolver_inputs import ResolverGraphRevisionInput
from core.orchestration.resolver_pipeline import (
    ResolutionIssue,
    ResolutionStage,
    run_resolution_pipeline,
)
from tests.test_resolver_pipeline import _registry, _resolver_inputs

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_resolved_plan_contains_canonical_graph_paths_contracts_actions_and_explanation() -> None:
    inputs = _resolver_inputs()
    pipeline = run_resolution_pipeline(inputs, registry=_registry())

    plan = build_resolved_plan(inputs, pipeline)

    assert plan.status is ResolverPlanStatus.RESOLVED
    assert len(plan.digest) == 64
    assert plan.document["desired"]["revisionId"] == "revision:pipeline:1"
    assert plan.document["world"]["version"] == inputs.world_version.token
    assert plan.document["currentPlanPolicy"] == {
        "mayBecomeCurrent": True,
        "mayRemainCurrent": True,
        "mayExecuteActions": True,
        "retainLastSafePlan": False,
        "reason": "The plan is complete and has no resolution diagnostics.",
    }
    assert [node["id"] for node in plan.document["expandedGraph"]["nodes"]] == [
        "processing/process",
        "sink",
        "source",
    ]
    assert plan.document.to_dict()["paths"] == {
        "activeNodeIds": ["processing/process", "sink", "source"],
        "selectedEdgeIds": ["edge:in", "edge:out"],
        "rejectedEdgeIds": [],
    }
    assert plan.document["signalContracts"]["edge:in"]["compatible"] is True
    assert plan.document["resourceAssignments"]["processing/process"] == {
        "resourceId": "decoder:0",
        "units": 1,
    }
    assert plan.document["resourceDecisions"]["processing/process"]["status"] == ("allocated")
    assert {action["kind"] for action in plan.document["actionIntent"]} == {
        "connect-path",
        "endpoint-target",
        "reserve-resource",
    }
    assert plan.document["warnings"] == ()
    assert plan.document["errors"] == ()
    assert plan.explanation["summary"]["errorCount"] == 0
    assert json.loads(json.dumps(plan.document.to_dict(), sort_keys=True)) == (
        plan.document.to_dict()
    )


def test_rejected_paths_remain_visible_when_condition_is_false() -> None:
    inputs = _resolver_inputs(cinema=False)
    pipeline = run_resolution_pipeline(inputs, registry=_registry())

    plan = build_resolved_plan(inputs, pipeline)

    assert plan.status is ResolverPlanStatus.RESOLVED
    assert plan.document.to_dict()["paths"]["selectedEdgeIds"] == []
    assert plan.document.to_dict()["paths"]["rejectedEdgeIds"] == [
        "edge:in",
        "edge:out",
    ]
    assert plan.explanation["conditionResults"]["$.edges[0].condition"] == "false"


def test_missing_resource_is_degraded_with_warning_and_no_reservation_action() -> None:
    inputs = _resolver_inputs(resources=False)
    pipeline = run_resolution_pipeline(inputs, registry=_registry())

    plan = build_resolved_plan(inputs, pipeline)

    assert plan.status is ResolverPlanStatus.DEGRADED
    assert plan.document["warnings"][0]["code"] == "resource_unavailable"
    assert not any(action["kind"] == "reserve-resource" for action in plan.document["actionIntent"])
    assert plan.explanation.to_dict()["summary"] == {
        "selectedEndpoints": ["endpoint:phone", "endpoint:speakers"],
        "selectedEdges": ["edge:in", "edge:out"],
        "warningCount": 1,
        "errorCount": 0,
    }


def test_missing_endpoint_is_waiting_with_rejected_complete_path() -> None:
    inputs = _resolver_inputs()
    inventory = type(inputs.runtime_inventory)(
        generation=inputs.runtime_inventory.generation,
        sequence=inputs.runtime_inventory.sequence,
        captured_at=inputs.runtime_inventory.captured_at,
        candidates=tuple(
            candidate
            for candidate in inputs.runtime_inventory.candidates
            if candidate.direction.value == "input"
        ),
    )
    waiting_inputs = replace(inputs, runtime_inventory=inventory)
    pipeline = run_resolution_pipeline(waiting_inputs, registry=_registry())

    plan = build_resolved_plan(waiting_inputs, pipeline)

    assert plan.status is ResolverPlanStatus.WAITING
    assert plan.document.to_dict()["paths"]["selectedEdgeIds"] == []
    assert plan.document["warnings"][0]["code"] == "endpoint_no_match"
    assert plan.document["currentPlanPolicy"]["retainLastSafePlan"] is True


@pytest.mark.parametrize(
    ("issue", "selected_edges", "status"),
    [
        (
            ResolutionIssue(
                ResolutionStage.ENDPOINTS,
                "$.logicalEndpoints['missing']",
                "endpoint_no_match",
                "Endpoint is absent.",
            ),
            (),
            ResolverPlanStatus.WAITING,
        ),
        (
            ResolutionIssue(
                ResolutionStage.ENDPOINTS,
                "$.logicalEndpoints['optional']",
                "endpoint_no_match",
                "Optional endpoint is absent.",
            ),
            ("edge:in", "edge:out"),
            ResolverPlanStatus.DEGRADED,
        ),
        (
            ResolutionIssue(
                ResolutionStage.PATHS,
                "$.nodes['selector']",
                "selector_conflicted",
                "Equal-priority candidates require an explicit tie-break.",
            ),
            (),
            ResolverPlanStatus.CONFLICTED,
        ),
        (
            ResolutionIssue(
                ResolutionStage.STRUCTURE,
                "$.edges[0].to.port",
                "unknown_port",
                "The target port does not exist.",
            ),
            (),
            ResolverPlanStatus.INVALID,
        ),
    ],
)
def test_statuses_are_explicit_and_do_not_depend_on_generic_valid_flag(
    issue: ResolutionIssue,
    selected_edges: tuple[str, ...],
    status: ResolverPlanStatus,
) -> None:
    pipeline = run_resolution_pipeline(_resolver_inputs(), registry=_registry())
    classified = replace(
        pipeline,
        valid=False,
        selected_edge_ids=selected_edges,
        issues=(issue,),
    )

    assert classify_plan_status(classified) is status


def test_degraded_complete_fallback_may_be_current_but_missing_resource_may_not() -> None:
    pipeline = run_resolution_pipeline(_resolver_inputs(), registry=_registry())
    degraded_fallback = replace(
        pipeline,
        valid=False,
        issues=(
            ResolutionIssue(
                ResolutionStage.ENDPOINTS,
                "$.logicalEndpoints['optional']",
                "endpoint_no_match",
                "Optional endpoint is absent.",
            ),
        ),
    )
    blocked_resource = replace(
        pipeline,
        valid=False,
        resource_assignments=FrozenDict(),
        issues=(
            ResolutionIssue(
                ResolutionStage.RESOURCES,
                "$.nodes['processing/process']",
                "resource_unavailable",
                "Decoder resource is unavailable.",
            ),
        ),
    )

    assert current_plan_policy(degraded_fallback).to_document() == {
        "mayBecomeCurrent": True,
        "mayRemainCurrent": True,
        "mayExecuteActions": True,
        "retainLastSafePlan": False,
        "reason": "A complete safe fallback remains selected despite degraded inputs.",
    }
    assert current_plan_policy(blocked_resource).to_document() == {
        "mayBecomeCurrent": False,
        "mayRemainCurrent": False,
        "mayExecuteActions": False,
        "retainLastSafePlan": True,
        "reason": "No complete executable fallback is available; retain the last safe plan.",
    }


def test_equivalent_randomized_input_order_has_identical_plan_and_explanation() -> None:
    inputs = _resolver_inputs()
    root = inputs.graph.document.to_dict()
    shuffled_root = deepcopy(root)
    shuffled_root["nodes"] = list(reversed(root["nodes"]))
    shuffled_root["edges"] = list(reversed(root["edges"]))
    shuffled_root["parameters"] = list(reversed(root["parameters"]))
    shuffled_root["layout"] = {"viewport": {"x": 99, "y": -20, "zoom": 2}}
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=inputs.graph.content_digest,
        document=shuffled_root,
    )
    subgraph_input = inputs.subgraph_revisions[0]
    subgraph = subgraph_input.document.to_dict()
    shuffled_subgraph = deepcopy(subgraph)
    shuffled_subgraph["publicPorts"] = list(reversed(subgraph["publicPorts"]))
    shuffled_subgraph["layout"] = {"viewport": {"x": 4, "y": 8, "zoom": 0.5}}
    subgraph_revision = ResolverGraphRevisionInput(
        definition_id=subgraph_input.definition_id,
        revision_id=subgraph_input.revision_id,
        revision_number=subgraph_input.revision_number,
        schema_version=subgraph_input.schema_version,
        content_digest=subgraph_input.content_digest,
        document=shuffled_subgraph,
    )
    inventory = type(inputs.runtime_inventory)(
        generation=inputs.runtime_inventory.generation,
        sequence=inputs.runtime_inventory.sequence,
        captured_at=inputs.runtime_inventory.captured_at,
        candidates=tuple(reversed(inputs.runtime_inventory.candidates)),
    )
    shuffled_inputs = replace(
        inputs,
        graph=graph,
        subgraph_revisions=(subgraph_revision,),
        logical_endpoints=tuple(reversed(inputs.logical_endpoints)),
        runtime_inventory=inventory,
    )

    canonical = build_resolved_plan(
        inputs,
        run_resolution_pipeline(inputs, registry=_registry()),
    )
    shuffled = build_resolved_plan(
        shuffled_inputs,
        run_resolution_pipeline(shuffled_inputs, registry=_registry()),
    )

    assert shuffled.digest == canonical.digest
    assert shuffled.document == canonical.document
    assert shuffled.explanation == canonical.explanation


def test_plan_digest_and_explanation_are_stable_across_python_processes() -> None:
    script = """
import json
import django

django.setup()

from core.orchestration.resolved_plan import build_resolved_plan
from core.orchestration.resolver_pipeline import run_resolution_pipeline
from tests.test_resolver_pipeline import _registry, _resolver_inputs

inputs = _resolver_inputs()
plan = build_resolved_plan(
    inputs,
    run_resolution_pipeline(inputs, registry=_registry()),
)
print(json.dumps({
    "digest": plan.digest,
    "explanation": plan.explanation.to_dict(),
}, sort_keys=True, separators=(",", ":")))
"""
    outputs = []
    for seed in ("1", "93847"):
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "opencinema.settings"
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(completed.stdout.strip().splitlines()[-1]))

    assert outputs[0] == outputs[1]
