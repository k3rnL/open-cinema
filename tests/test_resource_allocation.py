from django.test import override_settings

from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from core.orchestration.resource_allocation import (
    ResourceRequest,
    allocate_graph_resources,
    allocate_resource_requests,
)
from core.orchestration.resolution_context import deployed_processor_resource_policy
from core.orchestration.resolver_inputs import (
    ResolverResourceInput,
    ResolverResourcePolicyInput,
)


def _resource(resource_id, kind, capacity=1, health="ready"):
    return ResolverResourceInput(
        resource_id=resource_id,
        kind=kind,
        capacity=capacity,
        allocated=0,
        health=health,
    )


def test_decoder_and_camilladsp_requests_use_resources_of_their_own_kind() -> None:
    result = allocate_resource_requests(
        (
            ResourceRequest("decoder-node", "decoder"),
            ResourceRequest("dsp-node", "camilladsp"),
        ),
        (
            _resource("camilladsp:0", "camilladsp"),
            _resource("decoder:0", "decoder"),
        ),
    )

    assert result.assignments.to_dict() == {
        "decoder-node": {"resourceId": "decoder:0", "units": 1},
        "dsp-node": {"resourceId": "camilladsp:0", "units": 1},
    }
    assert result.issues == ()


@override_settings(AUDIO_PROCESSOR_CAPACITY={"camilladsp": 2, "decoder": 1})
def test_deployed_capacity_becomes_portable_resolver_resources() -> None:
    policy = deployed_processor_resource_policy()

    assert policy.version == 1
    assert policy.policy == {"conflict": "priority"}
    assert [(item.resource_id, item.kind) for item in policy.resources] == [
        ("camilladsp:0", "camilladsp"),
        ("camilladsp:1", "camilladsp"),
        ("decoder:0", "decoder"),
    ]


def test_higher_priority_wins_capacity_conflict_independent_of_request_order() -> None:
    low = ResourceRequest("decoder-low", "decoder", priority=10)
    high = ResourceRequest("decoder-high", "decoder", priority=500)

    forward = allocate_resource_requests(
        (low, high),
        (_resource("decoder:0", "decoder"),),
    )
    reverse = allocate_resource_requests(
        (high, low),
        (_resource("decoder:0", "decoder"),),
    )

    assert forward == reverse
    assert tuple(forward.assignments) == ("decoder-high",)
    assert forward.decisions["decoder-low"]["reason"] == ("resource_capacity_conflict")
    assert forward.decisions["decoder-low"]["competingNodeIds"] == ("decoder-high",)


def test_equal_priority_uses_node_id_and_reports_the_tie_break() -> None:
    result = allocate_resource_requests(
        (
            ResourceRequest("node:z", "decoder", priority=100),
            ResourceRequest("node:a", "decoder", priority=100),
        ),
        (_resource("decoder:0", "decoder"),),
    )

    assert tuple(result.assignments) == ("node:a",)
    assert result.decisions["node:z"]["tieBreak"] == "node-id"
    assert result.decisions["node:z"]["competingNodeIds"] == ("node:a",)


def test_unhealthy_and_missing_resources_have_distinct_diagnostics() -> None:
    unhealthy = allocate_resource_requests(
        (ResourceRequest("decoder", "decoder"),),
        (_resource("decoder:0", "decoder", health="failed"),),
    )
    missing = allocate_resource_requests(
        (ResourceRequest("dsp", "camilladsp"),),
        (_resource("decoder:0", "decoder"),),
    )

    assert unhealthy.issues[0].code == "resource_unhealthy"
    assert missing.issues[0].code == "resource_unavailable"


def test_graph_infers_decoder_and_camilladsp_requirements_and_priorities() -> None:
    document = {
        "nodes": [
            {
                "id": "decoder",
                "type": "processor.pcm-auto-decoder",
                "configuration": {"resourcePriority": 200},
            },
            {
                "id": "dsp",
                "type": "processor.camilladsp-profile-selector",
                "configuration": {"resourcePriority": 100},
            },
        ]
    }
    policy = ResolverResourcePolicyInput(
        version=1,
        resources=(
            _resource("decoder:0", "decoder"),
            _resource("camilladsp:0", "camilladsp"),
        ),
        policy={"conflict": "priority"},
    )

    result = allocate_graph_resources(document, {"decoder", "dsp"}, policy)

    assert set(result.assignments) == {"decoder", "dsp"}
    assert result.decisions["decoder"]["priority"] == 200
    assert result.decisions["dsp"]["priority"] == 100


def test_invalid_graph_requirement_is_reported_without_crashing_resolution() -> None:
    document = {
        "nodes": [
            {
                "id": "decoder",
                "type": "test.processor",
                "configuration": {"resourceRequirement": {"kind": "decoder", "units": 0}},
            }
        ]
    }
    policy = ResolverResourcePolicyInput(
        version=1,
        resources=(_resource("decoder:0", "decoder"),),
        policy={"conflict": "priority"},
    )

    result = allocate_graph_resources(document, {"decoder"}, policy)

    assert result.assignments == {}
    assert result.decisions["decoder"]["reason"] == "resource_requirement_invalid"
    assert result.issues[0].code == "resource_requirement_invalid"


def test_camilladsp_deployment_capacity_is_deterministic_for_one_or_more_instances() -> None:
    requests = (
        ResourceRequest("dsp-low", "camilladsp", priority=10),
        ResourceRequest("dsp-high", "camilladsp", priority=100),
    )

    single = allocate_resource_requests(
        requests,
        CamillaDSPDeploymentPolicy(instance_count=1).resources(),
    )
    multiple = allocate_resource_requests(
        tuple(reversed(requests)),
        CamillaDSPDeploymentPolicy(instance_count=2).resources(),
    )

    assert single.assignments.to_dict() == {"dsp-high": {"resourceId": "camilladsp:0", "units": 1}}
    assert single.decisions["dsp-low"]["reason"] == "resource_capacity_conflict"
    assert multiple.assignments.to_dict() == {
        "dsp-high": {"resourceId": "camilladsp:0", "units": 1},
        "dsp-low": {"resourceId": "camilladsp:1", "units": 1},
    }


def test_bypassed_camilladsp_node_consumes_no_instance() -> None:
    document = {
        "nodes": [
            {
                "id": "dsp",
                "type": "processor.camilladsp-profile-selector",
                "configuration": {},
            },
            {"id": "bypass", "type": "core.conditional-bypass", "configuration": {}},
        ]
    }
    policy = ResolverResourcePolicyInput(
        version=1,
        resources=CamillaDSPDeploymentPolicy().resources(),
        policy={"conflict": "priority"},
    )

    result = allocate_graph_resources(document, {"bypass"}, policy)

    assert result.assignments == {}
    assert result.issues == ()
