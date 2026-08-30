"""Isolated candidate-generation contract validation entry point."""

from __future__ import annotations

import importlib
import json
import os
import sys
from importlib import metadata
from pathlib import Path

from .contracts import PluginHealth, PluginLifecycleState
from .v2_contracts import PLUGIN_ENTRY_POINT
from .v2_registry import PluginDistributionRegistry

RESULT_PREFIX = "OPEN_CINEMA_PLUGIN_VALIDATION="


def validate_overlay(site_packages: Path, expected: dict[str, str]) -> dict[str, object]:
    overlay = str(site_packages.resolve())
    sys.path.append(overlay)
    importlib.invalidate_caches()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opencinema.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()
    distributions = tuple(metadata.distributions(path=[overlay]))
    entry_points = tuple(
        entry_point
        for distribution in distributions
        for entry_point in distribution.entry_points
        if entry_point.group == PLUGIN_ENTRY_POINT
    )
    registry = PluginDistributionRegistry()
    registry.discover(entry_points_provider=lambda: entry_points)
    actual = {record.manifest.plugin_id: record.manifest.version for record in registry.records}
    unhealthy = []
    for record in registry.records:
        if (
            record.state is not PluginLifecycleState.AVAILABLE
            or record.health is not PluginHealth.HEALTHY
            or any(
                capability.declaration.required
                and (
                    capability.state is not PluginLifecycleState.AVAILABLE
                    or capability.health is not PluginHealth.HEALTHY
                )
                for capability in record.capabilities
            )
        ):
            unhealthy.append(record.manifest.plugin_id)
    return {
        "valid": actual == expected and not unhealthy and not registry.diagnostics,
        "expected": expected,
        "actual": actual,
        "unhealthy": sorted(unhealthy),
        "diagnostics": [item.to_document() for item in registry.diagnostics],
        "registry": [record.to_document() for record in registry.records],
    }


def main() -> int:
    if len(sys.argv) != 3:
        return 64
    site_packages = Path(sys.argv[1])
    expected = json.loads(sys.argv[2])
    if not isinstance(expected, dict):
        return 64
    try:
        result = validate_overlay(
            site_packages,
            {str(key): str(value) for key, value in expected.items()},
        )
    except Exception as error:
        result = {
            "valid": False,
            "expected": expected,
            "actual": {},
            "unhealthy": [],
            "diagnostics": [
                {
                    "code": "generation-validation-crashed",
                    "message": str(error)[:2048],
                    "exception": type(error).__name__,
                }
            ],
            "registry": [],
        }
    print(RESULT_PREFIX + json.dumps(result, separators=(",", ":")))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
