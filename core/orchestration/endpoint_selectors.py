from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .endpoint_inventory import (
    DURABLE_ENDPOINT_PROPERTY_KEYS,
    RuntimeEndpointCandidate,
)

ENDPOINT_SELECTOR_VERSION = 1
MAX_SELECTOR_PREDICATES = 32
MAX_SELECTOR_SET_VALUES = 32
MAX_SELECTOR_PATTERN_LENGTH = 128
MAX_SELECTOR_WILDCARDS = 4

_DIRECT_PATHS = {
    "direction",
    "mediaClass",
    "node.name",
    "node.description",
    "node.state",
    "device.name",
    "device.description",
    "device.mediaClass",
    "route.name",
    "route.availability",
    "route.active",
    "profile.name",
    "profile.availability",
    "profile.active",
}


class SelectorMatchMode(StrEnum):
    ALL = "all"
    ANY = "any"


class SelectorOperator(StrEnum):
    EXACT = "exact"
    ONE_OF = "oneOf"
    PATTERN = "pattern"


@dataclass(frozen=True, slots=True)
class EndpointSelectorIssue:
    path: str
    code: str
    message: str


def _same(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _safe_glob(value: str, pattern: str, *, case_sensitive: bool) -> bool:
    if not case_sensitive:
        value = value.casefold()
        pattern = pattern.casefold()
    previous = [True] + [False] * len(value)
    for token in pattern:
        current = [False] * (len(value) + 1)
        if token == "*":
            current[0] = previous[0]
            for index in range(1, len(value) + 1):
                current[index] = previous[index] or current[index - 1]
        elif token == "?":
            for index in range(1, len(value) + 1):
                current[index] = previous[index - 1]
        else:
            for index in range(1, len(value) + 1):
                current[index] = previous[index - 1] and value[index - 1] == token
        previous = current
    return previous[-1]


def _candidate_values(candidate: RuntimeEndpointCandidate, path: str) -> tuple[object, ...]:
    direct = {
        "direction": candidate.direction.value,
        "mediaClass": candidate.media_class,
        "node.name": candidate.name,
        "node.description": candidate.description,
        "node.state": candidate.node_state,
        "device.name": candidate.device_name,
        "device.description": candidate.device_description,
        "device.mediaClass": candidate.device_media_class,
    }
    if path in direct:
        return (direct[path],) if direct[path] is not None else ()
    if path.startswith("node.properties."):
        key = path.removeprefix("node.properties.")
        value = candidate.node_properties.get(key)
        return (value,) if value is not None else ()
    if path.startswith("device.properties."):
        key = path.removeprefix("device.properties.")
        value = candidate.device_properties.get(key)
        return (value,) if value is not None else ()
    if path.startswith("route."):
        attribute = {
            "route.name": "name",
            "route.availability": "availability",
            "route.active": "active",
        }[path]
        return tuple(getattr(route, attribute) for route in candidate.routes)
    if path.startswith("profile."):
        attribute = {
            "profile.name": "name",
            "profile.availability": "availability",
            "profile.active": "active",
        }[path]
        return tuple(getattr(profile, attribute) for profile in candidate.profiles)
    return ()


@dataclass(frozen=True, slots=True)
class EndpointSelectorPredicate:
    path: str
    operator: SelectorOperator
    value: object
    case_sensitive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator", SelectorOperator(self.operator))

    def matches(self, candidate: RuntimeEndpointCandidate) -> bool:
        values = _candidate_values(candidate, self.path)
        if self.operator == SelectorOperator.EXACT:
            return any(_same(value, self.value) for value in values)
        if self.operator == SelectorOperator.ONE_OF:
            return any(any(_same(value, option) for option in self.value) for value in values)
        return any(
            isinstance(value, str)
            and _safe_glob(
                value,
                self.value,
                case_sensitive=self.case_sensitive,
            )
            for value in values
        )


@dataclass(frozen=True, slots=True)
class EndpointSelector:
    mode: SelectorMatchMode
    predicates: tuple[EndpointSelectorPredicate, ...]

    def matches(self, candidate: RuntimeEndpointCandidate) -> bool:
        results = tuple(predicate.matches(candidate) for predicate in self.predicates)
        return all(results) if self.mode == SelectorMatchMode.ALL else any(results)


@dataclass(frozen=True, slots=True)
class EndpointSelectorValidation:
    valid: bool
    selector: EndpointSelector | None
    issues: tuple[EndpointSelectorIssue, ...]


def _path_is_safe(path: object) -> bool:
    if path in _DIRECT_PATHS:
        return True
    for prefix in ("node.properties.", "device.properties."):
        if isinstance(path, str) and path.startswith(prefix):
            return path.removeprefix(prefix) in DURABLE_ENDPOINT_PROPERTY_KEYS
    return False


def _scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def parse_endpoint_selector(document: Mapping[str, object]) -> EndpointSelectorValidation:
    issues: list[EndpointSelectorIssue] = []
    if not isinstance(document, Mapping):
        return EndpointSelectorValidation(
            False,
            None,
            (EndpointSelectorIssue("$", "invalid_type", "Selector must be an object."),),
        )
    if document.get("version") != ENDPOINT_SELECTOR_VERSION:
        issues.append(
            EndpointSelectorIssue(
                "$.version",
                "unsupported_version",
                f"Selector version must be {ENDPOINT_SELECTOR_VERSION}.",
            )
        )
    try:
        mode = SelectorMatchMode(document.get("match"))
    except (TypeError, ValueError):
        issues.append(
            EndpointSelectorIssue("$.match", "invalid_match", "Match must be 'all' or 'any'.")
        )
        mode = SelectorMatchMode.ALL
    raw_predicates = document.get("predicates")
    if not isinstance(raw_predicates, list) or not raw_predicates:
        issues.append(
            EndpointSelectorIssue(
                "$.predicates",
                "invalid_predicates",
                "Selector needs a non-empty predicate array.",
            )
        )
        raw_predicates = []
    if len(raw_predicates) > MAX_SELECTOR_PREDICATES:
        issues.append(
            EndpointSelectorIssue(
                "$.predicates",
                "predicate_limit",
                f"Selector has more than {MAX_SELECTOR_PREDICATES} predicates.",
            )
        )
    predicates = []
    for index, raw in enumerate(raw_predicates):
        path = f"$.predicates[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(EndpointSelectorIssue(path, "invalid_predicate", "Expected an object."))
            continue
        unknown = set(raw) - {"path", "operator", "value", "caseSensitive"}
        if unknown:
            issues.append(
                EndpointSelectorIssue(
                    path,
                    "unknown_fields",
                    f"Unknown fields: {', '.join(sorted(unknown))}.",
                )
            )
        field_path = raw.get("path")
        if not _path_is_safe(field_path):
            issues.append(
                EndpointSelectorIssue(
                    f"{path}.path",
                    "unsafe_path",
                    "Selector path is not in the endpoint fact catalogue.",
                )
            )
        try:
            operator = SelectorOperator(raw.get("operator"))
        except (TypeError, ValueError):
            issues.append(
                EndpointSelectorIssue(
                    f"{path}.operator",
                    "invalid_operator",
                    "Operator must be exact, oneOf, or pattern.",
                )
            )
            continue
        value = raw.get("value")
        case_sensitive = raw.get("caseSensitive", True)
        if not isinstance(case_sensitive, bool):
            issues.append(
                EndpointSelectorIssue(
                    f"{path}.caseSensitive",
                    "invalid_case_sensitivity",
                    "caseSensitive must be a boolean.",
                )
            )
            case_sensitive = True
        if operator == SelectorOperator.EXACT and not _scalar(value):
            issues.append(
                EndpointSelectorIssue(
                    f"{path}.value",
                    "invalid_exact_value",
                    "Exact value must be a JSON scalar.",
                )
            )
        elif operator == SelectorOperator.ONE_OF:
            if (
                not isinstance(value, list)
                or not value
                or len(value) > MAX_SELECTOR_SET_VALUES
                or any(not _scalar(item) for item in value)
            ):
                issues.append(
                    EndpointSelectorIssue(
                        f"{path}.value",
                        "invalid_set",
                        f"oneOf requires 1-{MAX_SELECTOR_SET_VALUES} scalar values.",
                    )
                )
            else:
                value = tuple(value)
        elif operator == SelectorOperator.PATTERN:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > MAX_SELECTOR_PATTERN_LENGTH
                or value.count("*") + value.count("?") > MAX_SELECTOR_WILDCARDS
                or any(character in value for character in "[]{}\\")
            ):
                issues.append(
                    EndpointSelectorIssue(
                        f"{path}.value",
                        "unsafe_pattern",
                        "Pattern must be a bounded glob using only '*' and '?' wildcards.",
                    )
                )
        if not any(issue.path.startswith(path) for issue in issues):
            predicates.append(
                EndpointSelectorPredicate(
                    path=field_path,
                    operator=operator,
                    value=value,
                    case_sensitive=case_sensitive,
                )
            )
    selector = None if issues else EndpointSelector(mode, tuple(predicates))
    return EndpointSelectorValidation(not issues, selector, tuple(issues))
