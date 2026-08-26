from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from api.models import LogicalEndpointDirection

LOGICAL_ENDPOINT_SELECTOR_VERSION = 1
MAX_LOGICAL_SELECTOR_VALUES = 32
MAX_LOGICAL_SELECTOR_VALUE_LENGTH = 128


@dataclass(frozen=True, slots=True)
class LogicalEndpointSelectorIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LogicalEndpointSummary:
    endpoint_id: str
    name: str
    direction: str
    tags: tuple[str, ...]
    groups: tuple[str, ...]
    update_version: int

    @classmethod
    def from_endpoint(cls, endpoint) -> LogicalEndpointSummary:
        """Detach the fields used by pure desired-endpoint selection."""

        return cls(
            endpoint_id=str(endpoint.pk),
            name=endpoint.name,
            direction=endpoint.direction,
            tags=tuple(endpoint.tags),
            groups=tuple(endpoint.groups),
            update_version=endpoint.update_version,
        )


@dataclass(frozen=True, slots=True)
class LogicalEndpointSelector:
    direction: str | None
    required_tags: tuple[str, ...]
    ordered_groups: tuple[str, ...]

    def rank(self, endpoint: LogicalEndpointSummary) -> tuple[int, int] | None:
        if self.direction is not None and endpoint.direction != self.direction:
            return None
        if not set(self.required_tags).issubset(endpoint.tags):
            return None
        if not self.ordered_groups:
            return (0, 0)

        matching_groups = set(self.ordered_groups).intersection(endpoint.groups)
        if not matching_groups:
            return None
        selector_rank = min(self.ordered_groups.index(group) for group in matching_groups)
        endpoint_rank = min(
            endpoint.groups.index(group)
            for group in matching_groups
            if self.ordered_groups.index(group) == selector_rank
        )
        return selector_rank, endpoint_rank


@dataclass(frozen=True, slots=True)
class LogicalEndpointSelectorValidation:
    valid: bool
    selector: LogicalEndpointSelector | None
    issues: tuple[LogicalEndpointSelectorIssue, ...]


@dataclass(frozen=True, slots=True)
class LogicalEndpointSelectionDiagnostic:
    endpoint_id: str
    name: str
    eligible: bool
    group_rank: int | None
    membership_rank: int | None
    accepted_evidence: tuple[str, ...]
    rejected_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicalEndpointSelection:
    selected: tuple[LogicalEndpointSummary, ...]
    diagnostics: tuple[LogicalEndpointSelectionDiagnostic, ...]


def _parse_values(
    document: Mapping[str, object],
    field: str,
    issues: list[LogicalEndpointSelectorIssue],
) -> tuple[str, ...]:
    raw_values = document.get(field, [])
    path = f"$.{field}"
    if not isinstance(raw_values, list):
        issues.append(LogicalEndpointSelectorIssue(path, "invalid_type", "Value must be an array."))
        return ()
    if len(raw_values) > MAX_LOGICAL_SELECTOR_VALUES:
        issues.append(
            LogicalEndpointSelectorIssue(
                path,
                "value_limit",
                f"Value has more than {MAX_LOGICAL_SELECTOR_VALUES} entries.",
            )
        )
    values: list[str] = []
    for index, value in enumerate(raw_values):
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_LOGICAL_SELECTOR_VALUE_LENGTH
        ):
            issues.append(
                LogicalEndpointSelectorIssue(
                    f"{path}[{index}]",
                    "invalid_value",
                    "Entries must be non-empty strings of at most "
                    f"{MAX_LOGICAL_SELECTOR_VALUE_LENGTH} characters.",
                )
            )
            continue
        if value in values:
            issues.append(
                LogicalEndpointSelectorIssue(
                    f"{path}[{index}]",
                    "duplicate_value",
                    f"Duplicate value: {value}.",
                )
            )
            continue
        values.append(value)
    return tuple(values)


def parse_logical_endpoint_selector(
    document: Mapping[str, object],
) -> LogicalEndpointSelectorValidation:
    issues: list[LogicalEndpointSelectorIssue] = []
    if not isinstance(document, Mapping):
        return LogicalEndpointSelectorValidation(
            valid=False,
            selector=None,
            issues=(
                LogicalEndpointSelectorIssue(
                    "$", "invalid_type", "Logical endpoint selector must be an object."
                ),
            ),
        )

    unknown = set(document) - {
        "version",
        "direction",
        "requiredTags",
        "orderedGroups",
    }
    if unknown:
        issues.append(
            LogicalEndpointSelectorIssue(
                "$",
                "unknown_fields",
                f"Unknown fields: {', '.join(sorted(unknown))}.",
            )
        )
    if document.get("version") != LOGICAL_ENDPOINT_SELECTOR_VERSION:
        issues.append(
            LogicalEndpointSelectorIssue(
                "$.version",
                "unsupported_version",
                f"Selector version must be {LOGICAL_ENDPOINT_SELECTOR_VERSION}.",
            )
        )

    direction = document.get("direction")
    if direction is not None and direction not in LogicalEndpointDirection.values:
        issues.append(
            LogicalEndpointSelectorIssue(
                "$.direction",
                "invalid_direction",
                "Direction must be input or output.",
            )
        )
        direction = None

    required_tags = _parse_values(document, "requiredTags", issues)
    ordered_groups = _parse_values(document, "orderedGroups", issues)
    if not required_tags and not ordered_groups:
        issues.append(
            LogicalEndpointSelectorIssue(
                "$",
                "empty_selector",
                "At least one required tag or ordered group is required.",
            )
        )

    if issues:
        return LogicalEndpointSelectorValidation(False, None, tuple(issues))
    return LogicalEndpointSelectorValidation(
        True,
        LogicalEndpointSelector(
            direction=direction,
            required_tags=required_tags,
            ordered_groups=ordered_groups,
        ),
        (),
    )


def select_logical_endpoints(
    selector: LogicalEndpointSelector,
    endpoints: Iterable[LogicalEndpointSummary],
    *,
    eligible_endpoint_ids: Collection[str] | None = None,
) -> LogicalEndpointSelection:
    """Select and order logical endpoints without consulting runtime or storage."""

    eligible_ids = (
        None
        if eligible_endpoint_ids is None
        else {str(endpoint_id) for endpoint_id in eligible_endpoint_ids}
    )
    ranked: list[tuple[int, int, LogicalEndpointSummary]] = []
    diagnostics: list[LogicalEndpointSelectionDiagnostic] = []
    for endpoint in endpoints:
        rank = selector.rank(endpoint)
        accepted: list[str] = []
        rejected: list[str] = []
        if selector.direction is not None:
            evidence = f"direction:{selector.direction}"
            (accepted if endpoint.direction == selector.direction else rejected).append(evidence)
        for tag in selector.required_tags:
            evidence = f"tag:{tag}"
            (accepted if tag in endpoint.tags else rejected).append(evidence)
        matching_groups = [group for group in selector.ordered_groups if group in endpoint.groups]
        if selector.ordered_groups:
            if matching_groups:
                accepted.append(f"group:{matching_groups[0]}")
            else:
                rejected.append("group:no-ordered-group-match")
        runtime_eligible = eligible_ids is None or endpoint.endpoint_id in eligible_ids
        if not runtime_eligible:
            rejected.append("runtime:not-eligible")
        is_eligible = rank is not None and runtime_eligible
        if is_eligible:
            ranked.append((rank[0], rank[1], endpoint))
        diagnostics.append(
            LogicalEndpointSelectionDiagnostic(
                endpoint_id=endpoint.endpoint_id,
                name=endpoint.name,
                eligible=is_eligible,
                group_rank=rank[0] if rank is not None else None,
                membership_rank=rank[1] if rank is not None else None,
                accepted_evidence=tuple(accepted),
                rejected_evidence=tuple(rejected),
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2].name, item[2].endpoint_id))
    diagnostic_by_id = {item.endpoint_id: item for item in diagnostics}
    ordered_diagnostics = [diagnostic_by_id[item[2].endpoint_id] for item in ranked]
    ordered_diagnostics.extend(
        sorted(
            (item for item in diagnostics if not item.eligible),
            key=lambda item: (item.name, item.endpoint_id),
        )
    )
    return LogicalEndpointSelection(
        selected=tuple(item[2] for item in ranked),
        diagnostics=tuple(ordered_diagnostics),
    )
