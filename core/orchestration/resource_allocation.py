from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wyreplumber.runtime import FrozenDict

from .resolver_inputs import ResolverResourceInput, ResolverResourcePolicyInput

_IMPLICIT_PROCESSOR_RESOURCES = {
    "processor.pcm-auto-decoder": "decoder",
    "processor.camilladsp-profile-selector": "camilladsp",
}
_HEALTHY_RESOURCE_STATES = {"ready", "available", "healthy"}


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    node_id: str
    kind: str
    units: int = 1
    priority: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ValueError("resource request node_id must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("resource request kind must be a non-empty string")
        if isinstance(self.units, bool) or not isinstance(self.units, int) or self.units < 1:
            raise ValueError("resource request units must be a positive integer")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("resource request priority must be an integer")


@dataclass(frozen=True, slots=True)
class ResourceAllocationIssue:
    node_id: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ResourceAllocationResult:
    assignments: FrozenDict
    decisions: FrozenDict
    issues: tuple[ResourceAllocationIssue, ...]


def allocate_resource_requests(
    requests: Sequence[ResourceRequest],
    resources: Sequence[ResolverResourceInput],
    *,
    conflict_policy: str = "priority",
) -> ResourceAllocationResult:
    if conflict_policy != "priority":
        raise ValueError("resource conflict policy must be 'priority'")
    canonical_requests = tuple(
        sorted(requests, key=lambda request: (-request.priority, request.node_id))
    )
    if any(not isinstance(request, ResourceRequest) for request in canonical_requests):
        raise TypeError("requests must contain ResourceRequest values")
    canonical_resources = tuple(sorted(resources, key=lambda item: item.resource_id))
    if any(not isinstance(resource, ResolverResourceInput) for resource in canonical_resources):
        raise TypeError("resources must contain ResolverResourceInput values")
    remaining = {
        resource.resource_id: resource.capacity - resource.allocated
        for resource in canonical_resources
        if resource.health in _HEALTHY_RESOURCE_STATES
    }
    assignments = {}
    decisions = {}
    issues = []
    winners_by_kind: dict[str, list[str]] = {}
    for request in canonical_requests:
        same_kind = tuple(
            resource for resource in canonical_resources if resource.kind == request.kind
        )
        healthy = tuple(
            resource for resource in same_kind if resource.health in _HEALTHY_RESOURCE_STATES
        )
        candidates = tuple(
            resource
            for resource in healthy
            if remaining.get(resource.resource_id, 0) >= request.units
        )
        previous_winners = winners_by_kind.setdefault(request.kind, [])
        tied_with_winner = any(
            winner.priority == request.priority and winner.node_id in previous_winners
            for winner in canonical_requests
        )
        if candidates:
            selected = candidates[0]
            remaining[selected.resource_id] -= request.units
            assignments[request.node_id] = {
                "resourceId": selected.resource_id,
                "units": request.units,
            }
            decisions[request.node_id] = {
                "status": "allocated",
                "kind": request.kind,
                "units": request.units,
                "priority": request.priority,
                "resourceId": selected.resource_id,
                "tieBreak": "node-id" if tied_with_winner else None,
                "competingNodeIds": [],
            }
            previous_winners.append(request.node_id)
            continue
        if not same_kind:
            code = "resource_unavailable"
            reason = f"No {request.kind!r} resource is declared."
        elif not healthy:
            code = "resource_unhealthy"
            reason = f"No {request.kind!r} resource is healthy."
        else:
            code = "resource_capacity_conflict"
            reason = (
                f"No {request.kind!r} resource has {request.units} free unit(s) "
                "after higher-priority allocations."
            )
        decisions[request.node_id] = {
            "status": "rejected",
            "kind": request.kind,
            "units": request.units,
            "priority": request.priority,
            "resourceId": None,
            "tieBreak": "node-id" if tied_with_winner else None,
            "competingNodeIds": list(previous_winners),
            "reason": code,
        }
        issues.append(ResourceAllocationIssue(request.node_id, code, reason))
    return ResourceAllocationResult(
        assignments=FrozenDict(assignments),
        decisions=FrozenDict(decisions),
        issues=tuple(issues),
    )


def graph_resource_requests(
    document: Mapping[str, object],
    active_node_ids: set[str] | frozenset[str],
) -> tuple[ResourceRequest, ...]:
    if not isinstance(document, Mapping):
        raise TypeError("document must be an object")
    requests = []
    nodes = sorted(
        (
            node
            for node in document.get("nodes", ())
            if isinstance(node, Mapping) and node.get("id") in active_node_ids
        ),
        key=lambda node: str(node.get("id")),
    )
    for node in nodes:
        configuration = node.get("configuration")
        configuration = configuration if isinstance(configuration, Mapping) else {}
        requirement = configuration.get("resourceRequirement")
        if isinstance(requirement, Mapping):
            kind = requirement.get("kind")
            units = requirement.get("units", 1)
            priority = requirement.get("priority", 0)
        else:
            kind = _IMPLICIT_PROCESSOR_RESOURCES.get(node.get("type"))
            units = 1
            priority = configuration.get("resourcePriority", 0)
        if kind is None:
            continue
        requests.append(ResourceRequest(node["id"], kind, units, priority))
    return tuple(requests)


def allocate_graph_resources(
    document: Mapping[str, object],
    active_node_ids: set[str] | frozenset[str],
    policy: ResolverResourcePolicyInput,
) -> ResourceAllocationResult:
    if not isinstance(policy, ResolverResourcePolicyInput):
        raise TypeError("policy must be a ResolverResourcePolicyInput")
    requests = []
    invalid_decisions = {}
    invalid_issues = []
    for node in sorted(
        (
            item
            for item in document.get("nodes", ())
            if isinstance(item, Mapping) and item.get("id") in active_node_ids
        ),
        key=lambda item: str(item.get("id")),
    ):
        try:
            request = graph_resource_requests(
                {"nodes": [node]},
                {node["id"]},
            )
        except (KeyError, TypeError, ValueError) as error:
            node_id = str(node.get("id"))
            invalid_decisions[node_id] = {
                "status": "rejected",
                "resourceId": None,
                "reason": "resource_requirement_invalid",
            }
            invalid_issues.append(
                ResourceAllocationIssue(
                    node_id,
                    "resource_requirement_invalid",
                    str(error),
                )
            )
            continue
        requests.extend(request)
    result = allocate_resource_requests(
        requests,
        policy.resources,
        conflict_policy=policy.policy.get("conflict", "priority"),
    )
    return ResourceAllocationResult(
        assignments=result.assignments,
        decisions=FrozenDict({**result.decisions.to_dict(), **invalid_decisions}),
        issues=tuple(
            sorted(
                (*result.issues, *invalid_issues),
                key=lambda issue: (issue.node_id, issue.code, issue.message),
            )
        ),
    )
