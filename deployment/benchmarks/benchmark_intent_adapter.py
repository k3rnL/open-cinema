#!/usr/bin/env python3
"""Snapshot and restore active graph intent through OpenCinema services.

The benchmark runner deliberately does not write orchestration tables.  This
adapter runs in the installed application environment and uses the same
compare-and-swap activation service as the management API.  Generated row
identities, timestamps, and desired-state sequence numbers are observations;
the restoration contract is the semantic set of enabled graph selections.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def semantic_digest(active: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(list(active))).hexdigest()


def normalize_active(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the stable, behavior-defining part of enabled activations."""

    normalized = [
        {
            "definitionId": str(record["definitionId"]),
            "revisionId": str(record["revisionId"]),
            "parameterBindings": dict(record.get("parameterBindings") or {}),
            "sceneBindings": dict(record.get("sceneBindings") or {}),
        }
        for record in records
    ]
    normalized.sort(key=lambda record: record["definitionId"])
    definition_ids = [record["definitionId"] for record in normalized]
    if len(definition_ids) != len(set(definition_ids)):
        raise ValueError("active-intent snapshot contains duplicate graph definitions")
    return normalized


def snapshot_document(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active = normalize_active([row for row in rows if bool(row["enabled"])])
    observations = sorted(
        (
            {
                "definitionId": str(row["definitionId"]),
                "revisionId": str(row["revisionId"]),
                "enabled": bool(row["enabled"]),
                "desiredStateVersion": int(row["desiredStateVersion"]),
            }
            for row in rows
        ),
        key=lambda row: row["definitionId"],
    )
    return {
        "schemaVersion": 1,
        "active": active,
        "semanticDigest": semantic_digest(active),
        "observedVersions": observations,
    }


def reconciliation_plan(
    expected_active: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Describe the minimal supported-service calls needed for restoration."""

    expected = {row["definitionId"]: row for row in normalize_active(expected_active)}
    current = {str(row["definitionId"]): row for row in current_rows}
    actions: list[dict[str, Any]] = []

    for definition_id in sorted(set(current) - set(expected)):
        row = current[definition_id]
        if bool(row["enabled"]):
            actions.append(
                {
                    "action": "deactivate",
                    "definitionId": definition_id,
                    "expectedVersion": int(row["desiredStateVersion"]),
                }
            )

    for definition_id in sorted(expected):
        wanted = expected[definition_id]
        observed = current.get(definition_id)
        matches = bool(observed and observed["enabled"])
        if matches:
            matches = (
                str(observed["revisionId"]) == wanted["revisionId"]
                and dict(observed.get("parameterBindings") or {}) == wanted["parameterBindings"]
                and dict(observed.get("sceneBindings") or {}) == wanted["sceneBindings"]
            )
        if not matches:
            actions.append(
                {
                    "action": "activate",
                    "definitionId": definition_id,
                    "revisionId": wanted["revisionId"],
                    "parameterBindings": wanted["parameterBindings"],
                    "sceneBindings": wanted["sceneBindings"],
                    "expectedVersion": (
                        int(observed["desiredStateVersion"]) if observed is not None else 0
                    ),
                }
            )
    return actions


def configure_django(*, database_path: Path) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opencinema.settings")
    os.environ["DATABASE_PATH"] = str(database_path)
    import django

    django.setup()


def activation_rows() -> list[dict[str, Any]]:
    from api.models.orchestration import GraphActivation

    return [
        {
            "definitionId": str(row["definition_id"]),
            "revisionId": str(row["revision_id"]),
            "enabled": bool(row["enabled"]),
            "parameterBindings": row["parameter_bindings"],
            "sceneBindings": row["scene_bindings"],
            "desiredStateVersion": int(row["desired_state_version"]),
        }
        for row in GraphActivation.objects.order_by("definition_id").values(
            "definition_id",
            "revision_id",
            "enabled",
            "parameter_bindings",
            "scene_bindings",
            "desired_state_version",
        )
    ]


def restore_desired_intent(expected_document: Mapping[str, Any]) -> dict[str, Any]:
    if expected_document.get("schemaVersion") != 1:
        raise ValueError("unsupported active-intent snapshot schema")
    expected_active = normalize_active(expected_document.get("active", []))
    expected_digest = semantic_digest(expected_active)
    if expected_document.get("semanticDigest") != expected_digest:
        raise ValueError("active-intent snapshot digest does not match its content")

    from api.models.orchestration import GraphActivation, GraphDefinition, GraphRevision
    from core.orchestration.activations import activate_graph, deactivate_graph

    actions = reconciliation_plan(expected_active, activation_rows())
    applied: list[dict[str, Any]] = []
    for action in actions:
        definition = GraphDefinition.objects.get(pk=action["definitionId"])
        if action["action"] == "deactivate":
            activation = deactivate_graph(
                definition=definition,
                expected_version=action["expectedVersion"],
            )
        else:
            revision = GraphRevision.objects.get(
                pk=action["revisionId"], definition_id=action["definitionId"]
            )
            activation = activate_graph(
                definition=definition,
                revision=revision,
                expected_version=action["expectedVersion"],
                parameter_bindings=action["parameterBindings"],
                scene_bindings=action["sceneBindings"],
            )
        applied.append(
            {
                "action": action["action"],
                "definitionId": action["definitionId"],
                "desiredStateVersion": (
                    activation.desired_state_version if activation is not None else None
                ),
            }
        )

    observed = snapshot_document(activation_rows())
    if observed["semanticDigest"] != expected_digest:
        raise RuntimeError(
            "supported-service restoration completed without restoring active intent"
        )
    return {"changed": bool(applied), "actions": applied, "snapshot": observed}


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, required=True)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("snapshot")
    restore = subcommands.add_parser("restore")
    restore.add_argument(
        "--snapshot-stdin",
        action="store_true",
        help="read the private prepare snapshot from standard input",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    try:
        configure_django(database_path=arguments.database_path)
        if arguments.command == "snapshot":
            result = snapshot_document(activation_rows())
        else:
            if not arguments.snapshot_stdin:
                raise ValueError("restore requires --snapshot-stdin")
            document = json.load(sys.stdin)
            if not isinstance(document, dict):
                raise ValueError("active-intent snapshot must be an object")
            result = restore_desired_intent(document)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:  # pragma: no cover - exercised by the runner boundary
        print(
            json.dumps(
                {"error": str(error), "errorType": type(error).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
