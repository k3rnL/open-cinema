"""Small, dependency-free version filters used by deployment preflight."""

from __future__ import annotations

import re
from collections.abc import Mapping


VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")


def open_cinema_extract_version(value: str) -> str:
    """Return the first numeric major.minor.patch version in command output."""
    match = VERSION_PATTERN.search(value)
    if match is None:
        return ""
    major, minor, patch = match.groups(default="0")
    return f"{major}.{minor}.{patch}"


def _version_tuple(value: str) -> tuple[int, int, int]:
    normalized = open_cinema_extract_version(value)
    if not normalized:
        raise ValueError(f"No numeric version found in {value!r}")
    major, minor, patch = normalized.split(".")
    return int(major), int(minor), int(patch)


def open_cinema_version_in_range(
    value: str,
    component: Mapping[str, str],
) -> bool:
    """Check an observed version against inclusive-minimum/exclusive-maximum bounds."""
    observed = _version_tuple(value)
    minimum = _version_tuple(component["minimum"])
    maximum = _version_tuple(component["maximum_exclusive"])
    return minimum <= observed < maximum


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "open_cinema_extract_version": open_cinema_extract_version,
            "open_cinema_version_in_range": open_cinema_version_in_range,
        }
