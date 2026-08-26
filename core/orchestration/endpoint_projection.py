from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from .endpoint_inventory import EndpointInventorySnapshot
from .endpoint_matching import EndpointMatchStatus, match_endpoint_candidates
from .endpoint_selectors import parse_endpoint_selector


class EndpointProjectionState(StrEnum):
    DISCOVERED = "discovered"
    ROUTE_AVAILABLE = "route-available"
    SELECTED = "selected"
    LINKED = "linked"
    ACTIVE_SIGNAL = "active-signal"
    SUSPENDED = "suspended"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


_STATE_PRIORITY = {
    EndpointProjectionState.DISCOVERED: 0,
    EndpointProjectionState.ROUTE_AVAILABLE: 1,
    EndpointProjectionState.SELECTED: 2,
    EndpointProjectionState.LINKED: 3,
    EndpointProjectionState.ACTIVE_SIGNAL: 4,
    EndpointProjectionState.SUSPENDED: 5,
    EndpointProjectionState.UNAVAILABLE: 6,
    EndpointProjectionState.AMBIGUOUS: 7,
    EndpointProjectionState.ERROR: 8,
}


@dataclass(frozen=True, slots=True)
class LogicalEndpointIntent:
    id: str
    name: str
    direction: str
    selector: Mapping[str, object]
    last_known_summary: Mapping[str, object]

    @classmethod
    def from_model(cls, endpoint) -> "LogicalEndpointIntent":
        return cls(
            id=str(endpoint.pk),
            name=endpoint.name,
            direction=endpoint.direction,
            selector=endpoint.explicit_binding or endpoint.selector,
            last_known_summary=endpoint.last_known_summary,
        )


@dataclass(frozen=True, slots=True)
class LogicalEndpointProjection:
    endpoint_id: str
    name: str
    direction: str
    primary_state: EndpointProjectionState
    states: tuple[EndpointProjectionState, ...]
    runtime_key: str | None
    matched_candidates: int
    last_seen: str | None
    summary: Mapping[str, object]
    diagnostics: tuple[Mapping[str, object], ...]

    def to_document(self) -> dict[str, object]:
        return {
            "endpointId": self.endpoint_id,
            "name": self.name,
            "direction": self.direction,
            "state": self.primary_state.value,
            "states": [state.value for state in self.states],
            "runtimeKey": self.runtime_key,
            "matchedCandidates": self.matched_candidates,
            "lastSeen": self.last_seen,
            "summary": dict(self.summary),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def _candidate_states(candidate, *, selected):
    states = {EndpointProjectionState.DISCOVERED}
    route_available = not candidate.routes or any(
        route.active or route.availability == "yes" for route in candidate.routes
    )
    if route_available:
        states.add(EndpointProjectionState.ROUTE_AVAILABLE)
    if selected:
        states.add(EndpointProjectionState.SELECTED)
    if candidate.is_linked:
        states.add(EndpointProjectionState.LINKED)
    if candidate.has_active_signal:
        states.add(EndpointProjectionState.ACTIVE_SIGNAL)
    if candidate.node_state == "suspended":
        states.add(EndpointProjectionState.SUSPENDED)
    if candidate.node_state == "error" or candidate.node_error:
        states.add(EndpointProjectionState.ERROR)
    return states


def _ordered(states):
    return tuple(sorted(states, key=lambda state: (_STATE_PRIORITY[state], state.value)))


def project_logical_endpoint(
    intent: LogicalEndpointIntent,
    inventory: EndpointInventorySnapshot,
    *,
    selected_runtime_keys: set[str] | frozenset[str] = frozenset(),
) -> LogicalEndpointProjection:
    validation = parse_endpoint_selector(intent.selector)
    if not validation.valid:
        diagnostics = tuple(
            {"path": issue.path, "code": issue.code, "message": issue.message}
            for issue in validation.issues
        )
        states = (EndpointProjectionState.ERROR,)
        return LogicalEndpointProjection(
            str(intent.id),
            intent.name,
            intent.direction,
            EndpointProjectionState.ERROR,
            states,
            None,
            0,
            intent.last_known_summary.get("lastSeen"),
            intent.last_known_summary,
            diagnostics,
        )
    direction_candidates = tuple(
        candidate
        for candidate in inventory.candidates
        if candidate.direction.value == intent.direction
    )
    match = match_endpoint_candidates(validation.selector, direction_candidates)
    diagnostics = tuple(
        {
            "runtimeKey": diagnostic.runtime_key,
            "matched": diagnostic.matched_selector,
            "score": diagnostic.score,
            "acceptedEvidence": list(diagnostic.accepted_evidence),
            "rejectedEvidence": list(diagnostic.rejected_evidence),
        }
        for diagnostic in match.diagnostics
    )
    if match.status == EndpointMatchStatus.NO_MATCH:
        states = (EndpointProjectionState.UNAVAILABLE,)
        return LogicalEndpointProjection(
            str(intent.id),
            intent.name,
            intent.direction,
            EndpointProjectionState.UNAVAILABLE,
            states,
            None,
            0,
            intent.last_known_summary.get("lastSeen"),
            intent.last_known_summary,
            diagnostics,
        )
    if match.status == EndpointMatchStatus.AMBIGUOUS:
        states = _ordered({EndpointProjectionState.DISCOVERED, EndpointProjectionState.AMBIGUOUS})
        return LogicalEndpointProjection(
            str(intent.id),
            intent.name,
            intent.direction,
            EndpointProjectionState.AMBIGUOUS,
            states,
            None,
            len(match.tied),
            inventory.captured_at,
            intent.last_known_summary,
            diagnostics,
        )
    candidate = match.selected
    states = _ordered(
        _candidate_states(
            candidate,
            selected=candidate.runtime_key in selected_runtime_keys,
        )
    )
    primary = max(states, key=lambda state: _STATE_PRIORITY[state])
    summary = {
        "lastSeen": inventory.captured_at,
        "name": candidate.name,
        "description": candidate.description,
        "mediaClass": candidate.media_class,
    }
    return LogicalEndpointProjection(
        str(intent.id),
        intent.name,
        intent.direction,
        primary,
        states,
        candidate.runtime_key,
        1,
        inventory.captured_at,
        summary,
        diagnostics,
    )


def project_endpoint_inventory(
    intents: Iterable[LogicalEndpointIntent],
    inventory: EndpointInventorySnapshot,
    *,
    selected_runtime_keys: set[str] | frozenset[str] = frozenset(),
) -> tuple[LogicalEndpointProjection, ...]:
    return tuple(
        project_logical_endpoint(
            intent,
            inventory,
            selected_runtime_keys=selected_runtime_keys,
        )
        for intent in sorted(intents, key=lambda item: (item.name, str(item.id)))
    )
