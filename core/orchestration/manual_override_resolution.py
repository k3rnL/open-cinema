from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from wyreplumber.runtime import FrozenDict, thaw_json

from .resolver_inputs import ResolverOverrideInput


@dataclass(frozen=True, slots=True)
class RejectedManualOverride:
    override_id: str
    scope_type: str
    scope_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ManualOverrideResolution:
    winners: tuple[ResolverOverrideInput, ...]
    rejected: tuple[RejectedManualOverride, ...]
    endpoint_selections: FrozenDict
    parameter_values: FrozenDict
    modes: FrozenDict
    controls: FrozenDict
    provenance: FrozenDict

    def to_document(self) -> dict[str, object]:
        return {
            "winners": [
                {
                    "overrideId": item.override_id,
                    "scopeType": item.scope_type,
                    "scopeId": item.scope_id,
                    "priority": item.priority,
                    "startsAt": item.starts_at,
                    "expiresAt": item.expires_at,
                    "reason": item.reason,
                }
                for item in self.winners
            ],
            "rejected": [
                {
                    "overrideId": item.override_id,
                    "scopeType": item.scope_type,
                    "scopeId": item.scope_id,
                    "reason": item.reason,
                }
                for item in self.rejected
            ],
            "endpointSelections": self.endpoint_selections.to_dict(),
            "parameterValues": self.parameter_values.to_dict(),
            "modes": self.modes.to_dict(),
            "controls": self.controls.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


def _window_reason(override: ResolverOverrideInput, evaluated_at: datetime) -> str | None:
    starts_at = _timestamp(override.starts_at, "starts_at")
    expires_at = (
        _timestamp(override.expires_at, "expires_at") if override.expires_at is not None else None
    )
    if override.cancelled_at is not None:
        return "cancelled"
    if evaluated_at < starts_at:
        return "not_started"
    if expires_at is not None and evaluated_at >= expires_at:
        return "expired"
    if not override.active:
        return "inactive"
    return None


def _invalid_target_reason(
    override: ResolverOverrideInput,
    *,
    endpoint_ids: set[str],
    parameter_names: set[str],
) -> str | None:
    value = thaw_json(override.value)
    if override.scope_type == "endpoint":
        if not isinstance(value, str) or value not in endpoint_ids:
            return "invalid_endpoint_target"
    elif override.scope_type == "graph_parameter":
        if override.scope_id not in parameter_names:
            return "invalid_parameter_target"
        if not isinstance(value, dict) or "value" not in value:
            return "invalid_parameter_value"
    elif override.scope_type in {"volume", "mute"}:
        if override.scope_id.startswith("endpoint:") and override.scope_id not in endpoint_ids:
            return "invalid_endpoint_target"
    return None


def resolve_manual_overrides(
    overrides: Iterable[ResolverOverrideInput],
    *,
    evaluated_at: str,
    endpoint_ids: Iterable[str],
    base_parameter_values: Mapping[str, object],
    base_modes: Mapping[str, object],
) -> ManualOverrideResolution:
    """Resolve temporary overrides without mutating persistent desired values."""

    moment = _timestamp(evaluated_at, "evaluated_at")
    endpoint_id_set = set(endpoint_ids)
    parameter_names = set(base_parameter_values)
    rejected: list[RejectedManualOverride] = []
    candidates = defaultdict(list)
    for override in overrides:
        if not isinstance(override, ResolverOverrideInput):
            raise TypeError("overrides must contain ResolverOverrideInput values")
        reason = _window_reason(override, moment) or _invalid_target_reason(
            override,
            endpoint_ids=endpoint_id_set,
            parameter_names=parameter_names,
        )
        if reason is not None:
            rejected.append(
                RejectedManualOverride(
                    override.override_id,
                    override.scope_type,
                    override.scope_id,
                    reason,
                )
            )
            continue
        candidates[(override.scope_type, override.scope_id)].append(override)

    winners = []
    for scoped in candidates.values():
        scoped.sort(
            key=lambda item: (
                -item.priority,
                -_timestamp(item.starts_at, "starts_at").timestamp(),
                item.override_id,
            )
        )
        winner = scoped[0]
        winners.append(winner)
        for loser in scoped[1:]:
            reason = (
                "lower_priority" if loser.priority < winner.priority else "newer_start_tie_break"
            )
            rejected.append(
                RejectedManualOverride(
                    loser.override_id,
                    loser.scope_type,
                    loser.scope_id,
                    reason,
                )
            )
    winners.sort(key=lambda item: (item.scope_type, item.scope_id, item.override_id))
    rejected.sort(key=lambda item: (item.scope_type, item.scope_id, item.override_id))

    endpoint_selections = {}
    parameter_values = dict(base_parameter_values)
    modes = dict(base_modes)
    controls = {}
    provenance = {
        f"parameter.{name}": {"source": "persistent_activation"} for name in parameter_values
    }
    provenance.update({f"mode.{name}": {"source": "persistent_activation"} for name in modes})
    for winner in winners:
        value = thaw_json(winner.value)
        source = {
            "source": "temporary_override",
            "overrideId": winner.override_id,
            "priority": winner.priority,
            "expiresAt": winner.expires_at,
        }
        if winner.scope_type == "endpoint":
            endpoint_selections[winner.scope_id] = value
            provenance[f"endpoint.{winner.scope_id}"] = source
        elif winner.scope_type == "graph_parameter":
            parameter_values[winner.scope_id] = value["value"]
            provenance[f"parameter.{winner.scope_id}"] = source
        elif winner.scope_type == "scene":
            modes[winner.scope_id] = value
            provenance[f"mode.{winner.scope_id}"] = source
        elif winner.scope_type in {"volume", "mute", "route"}:
            controls[f"{winner.scope_type}.{winner.scope_id}"] = value
            provenance[f"control.{winner.scope_type}.{winner.scope_id}"] = source

    return ManualOverrideResolution(
        winners=tuple(winners),
        rejected=tuple(rejected),
        endpoint_selections=FrozenDict(endpoint_selections),
        parameter_values=FrozenDict(parameter_values),
        modes=FrozenDict(modes),
        controls=FrozenDict(controls),
        provenance=FrozenDict(provenance),
    )
