from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from hypothesis import assume, given
from hypothesis import strategies as st

from core.orchestration.condition_evaluation import EligibilityStatus
from core.orchestration.endpoint_inventory import RuntimeEndpointReference
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.manual_override_resolution import resolve_manual_overrides
from core.orchestration.path_selection import (
    PathCandidate,
    PathSelectionStatus,
    SelectionTieBreak,
    resolve_exclusive_selection,
)
from core.orchestration.resolved_plan import ResolverPlanStatus, build_resolved_plan
from core.orchestration.resolver_inputs import (
    ResolverGraphRevisionInput,
    ResolverOverrideInput,
    ResolverResourceInput,
    ResolverResourcePolicyInput,
    ResolverSignalFactsInput,
)
from core.orchestration.resolver_pipeline import ResolutionStage, run_resolution_pipeline
from core.orchestration.subgraph_expansion import expand_subgraphs
from tests.test_resolver_pipeline import _registry, _resolver_inputs
from tests.test_subgraph_expansion import (
    _instance,
    _parent_document,
    _subgraph_document,
)


def _plan(inputs):
    pipeline = run_resolution_pipeline(inputs, registry=_registry())
    return pipeline, build_resolved_plan(inputs, pipeline)


@given(missing_input=st.booleans(), missing_output=st.booleans())
def test_unavailable_required_endpoints_never_leave_an_incomplete_selected_path(
    missing_input: bool,
    missing_output: bool,
) -> None:
    inputs = _resolver_inputs()
    inventory = replace(
        inputs.runtime_inventory,
        candidates=tuple(
            candidate
            for candidate in inputs.runtime_inventory.candidates
            if not (
                (missing_input and candidate.direction.value == "input")
                or (missing_output and candidate.direction.value == "output")
            )
        ),
    )

    pipeline, plan = _plan(replace(inputs, runtime_inventory=inventory))

    if missing_input or missing_output:
        assert pipeline.selected_edge_ids == ()
        assert plan.status is ResolverPlanStatus.WAITING
        assert any(issue.code == "endpoint_no_match" for issue in pipeline.issues)
    else:
        assert pipeline.selected_edge_ids == ("edge:in", "edge:out")
        assert plan.status is ResolverPlanStatus.RESOLVED


@given(
    direction=st.sampled_from(("input", "output")),
    replacement_node_id=st.integers(min_value=10_000, max_value=1_000_000),
)
def test_equal_endpoint_candidates_always_produce_an_explicit_conflict(
    direction: str,
    replacement_node_id: int,
) -> None:
    inputs = _resolver_inputs()
    original = next(
        candidate
        for candidate in inputs.runtime_inventory.candidates
        if candidate.direction.value == direction
    )
    assume(replacement_node_id != original.runtime.node_id)
    duplicate = replace(
        original,
        runtime=RuntimeEndpointReference(
            generation=original.runtime.generation,
            node_id=replacement_node_id,
            device_id=original.runtime.device_id,
        ),
    )
    inventory = replace(
        inputs.runtime_inventory,
        candidates=(*inputs.runtime_inventory.candidates, duplicate),
    )

    pipeline, plan = _plan(replace(inputs, runtime_inventory=inventory))

    assert plan.status is ResolverPlanStatus.CONFLICTED
    assert pipeline.selected_edge_ids == ()
    assert any(issue.code == "endpoint_ambiguous" for issue in pipeline.issues)


@given(
    data=st.data(),
    priorities=st.lists(
        st.integers(min_value=-10_000, max_value=10_000),
        min_size=2,
        max_size=7,
        unique=True,
    ),
)
def test_competing_unique_priorities_always_select_the_global_maximum(
    data,
    priorities: list[int],
) -> None:
    candidates = tuple(
        PathCandidate(
            reference_id=f"candidate:{index}",
            priority=priority,
            declaration_order=index,
            eligibility=EligibilityStatus.ELIGIBLE,
        )
        for index, priority in enumerate(priorities)
    )
    permutation = data.draw(st.permutations(range(len(candidates))))

    decision = resolve_exclusive_selection(
        (candidates[index] for index in permutation),
        tie_break=SelectionTieBreak.DECLARATION_ORDER,
    )

    assert decision.status is PathSelectionStatus.RESOLVED
    assert decision.selected[0].priority == max(priorities)


def _fan_out_inputs(capacity: int):
    inputs = _resolver_inputs()
    document = {
        "schemaVersion": 1,
        "id": "graph:fan-out-resources",
        "kind": "graph",
        "metadata": {"name": "Fan-out resource property"},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": "endpoint:phone",
                    "direction": "input",
                },
            },
            {
                "id": "fan-out",
                "type": "core.fan-out",
                "version": 1,
                "configuration": {"failureMode": "best-effort"},
            },
            *(
                {
                    "id": f"processor-{suffix}",
                    "type": "test.processor",
                    "version": 1,
                    "configuration": {"resourceRequirement": {"kind": "decoder", "units": 1}},
                }
                for suffix in ("a", "b")
            ),
            *(
                {
                    "id": f"sink-{suffix}",
                    "type": "core.endpoint-reference",
                    "version": 1,
                    "configuration": {
                        "logicalEndpointId": "endpoint:speakers",
                        "direction": "output",
                    },
                }
                for suffix in ("a", "b")
            ),
        ],
        "edges": [
            {
                "id": "edge:source",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "fan-out", "port": "input"},
            },
            *(
                {
                    "id": f"edge:branch:{suffix}",
                    "from": {"node": "fan-out", "port": "outputs"},
                    "to": {"node": f"processor-{suffix}", "port": "input"},
                }
                for suffix in ("a", "b")
            ),
            *(
                {
                    "id": f"edge:sink:{suffix}",
                    "from": {"node": f"processor-{suffix}", "port": "output"},
                    "to": {"node": f"sink-{suffix}", "port": "input"},
                }
                for suffix in ("a", "b")
            ),
        ],
        "layout": {},
    }
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=graph_content_digest(document),
        document=document,
    )
    resource_policy = ResolverResourcePolicyInput(
        version=inputs.resource_policy.version,
        resources=(
            ResolverResourceInput(
                resource_id="decoder:shared",
                kind="decoder",
                capacity=capacity,
                allocated=0,
                health="ready",
            ),
        ),
        policy={"conflict": "priority"},
    )
    return replace(
        inputs,
        graph=graph,
        subgraph_revisions=(),
        resource_policy=resource_policy,
    )


@given(capacity=st.integers(min_value=0, max_value=3))
def test_fan_out_resource_shortage_is_complete_and_deterministic(
    capacity: int,
) -> None:
    pipeline, _ = _plan(_fan_out_inputs(capacity))
    expected_assignments = min(capacity, 2)
    unavailable = [issue for issue in pipeline.issues if issue.stage is ResolutionStage.RESOURCES]

    assert len(pipeline.resource_assignments) == expected_assignments
    assert len(unavailable) == 2 - expected_assignments
    assert tuple(pipeline.resource_assignments) == tuple(
        f"processor-{suffix}" for suffix in ("a", "b")[:expected_assignments]
    )


def _nested_subgraph_case(depth: int):
    leaf_definition = "definition:nested:0"
    leaf_revision = "revision:nested:0"
    documents = {(leaf_definition, leaf_revision): _subgraph_document()}
    child_definition = leaf_definition
    child_revision = leaf_revision
    public_ports = [
        {
            "name": direction,
            "direction": direction,
            "contract": {"mediaKind": "audio", "content": "any"},
            "internalBinding": {"node": "node:nested", "port": direction},
        }
        for direction in ("input", "output")
    ]
    for level in range(1, depth):
        definition_id = f"definition:nested:{level}"
        revision_id = f"revision:nested:{level}"
        documents[(definition_id, revision_id)] = _subgraph_document(
            graph_id=definition_id,
            nodes=[
                _instance(
                    "node:nested",
                    child_definition,
                    child_revision,
                    {"parameter": "gain"},
                )
            ],
            public_ports=public_ports,
        )
        child_definition = definition_id
        child_revision = revision_id
    parent = _parent_document(
        [
            _instance(
                "node:outer",
                child_definition,
                child_revision,
                {"parameter": "roomGain"},
            )
        ]
    )
    return parent, documents


@given(depth=st.integers(min_value=1, max_value=5))
def test_nested_subgraphs_expand_to_the_exact_requested_depth(depth: int) -> None:
    parent, documents = _nested_subgraph_case(depth)

    result = expand_subgraphs(
        parent,
        loader=lambda definition_id, revision_id: deepcopy(
            documents.get((definition_id, revision_id))
        ),
        maximum_depth=depth,
    )

    expected_node = "/".join(["node:outer", *(["node:nested"] * (depth - 1)), "node:adapter"])
    assert result.valid
    assert result.maximum_depth == depth
    assert expected_node in {node["id"] for node in result.document["nodes"]}


@given(unknown_result=st.sampled_from(("eligible", "ineligible", "waiting", "error")))
def test_unknown_facts_follow_the_declared_edge_policy(unknown_result: str) -> None:
    inputs = _resolver_inputs()
    document = inputs.graph.document.to_dict()
    document["edges"][0]["condition"] = {
        "expression": {
            "op": "eq",
            "fact": "signal.source.content.codec",
            "value": "pcm",
        },
        "unknownResult": unknown_result,
    }
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=graph_content_digest(document),
        document=document,
    )
    unknown_inputs = replace(
        inputs,
        graph=graph,
        signal_facts=ResolverSignalFactsInput(version=1, facts={}),
    )

    pipeline, plan = _plan(unknown_inputs)

    expected = {
        "eligible": (("edge:in", "edge:out"), ResolverPlanStatus.RESOLVED),
        "ineligible": ((), ResolverPlanStatus.RESOLVED),
        "waiting": ((), ResolverPlanStatus.WAITING),
        "error": ((), ResolverPlanStatus.CONFLICTED),
    }[unknown_result]
    assert (pipeline.selected_edge_ids, plan.status) == expected
    assert pipeline.condition_results["$.edges[0].condition"] == "unknown"


@given(
    seconds_from_expiry=st.integers(min_value=-86_400, max_value=86_400),
    override_gain=st.floats(
        min_value=0,
        max_value=1,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_expired_overrides_never_leak_into_resolved_parameters(
    seconds_from_expiry: int,
    override_gain: float,
) -> None:
    evaluated_at = datetime(2026, 8, 22, 16, tzinfo=timezone.utc)
    expiry = evaluated_at + timedelta(seconds=seconds_from_expiry)
    override = ResolverOverrideInput(
        override_id="override:property:gain",
        scope_type="graph_parameter",
        scope_id="gain",
        value={"value": override_gain},
        priority=100,
        starts_at=(evaluated_at - timedelta(days=2)).isoformat(),
        expires_at=expiry.isoformat(),
        cancelled_at=None,
        active=True,
        reason="Property-test gain",
    )

    resolution = resolve_manual_overrides(
        (override,),
        evaluated_at=evaluated_at.isoformat(),
        endpoint_ids=(),
        base_parameter_values={"gain": 0.7},
        base_modes={},
    )

    if seconds_from_expiry <= 0:
        assert resolution.parameter_values["gain"] == 0.7
        assert resolution.winners == ()
        assert resolution.rejected[0].reason == "expired"
    else:
        assert resolution.parameter_values["gain"] == override_gain
        assert [winner.override_id for winner in resolution.winners] == ["override:property:gain"]
