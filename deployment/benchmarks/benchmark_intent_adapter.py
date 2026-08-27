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
import copy
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import yaml


BENCHMARK_DEFINITION_NAME = "Open Cinema benchmark CamillaDSP fixtures"
BENCHMARK_DEFINITION_LABEL = "camilladsp-native-v1"
BENCHMARK_PROFILE_PREFIX = "Open Cinema benchmark: "
CHANNEL_LAYOUTS = {
    "stereo": ("FL", "FR"),
    "5.1-side": ("FL", "FR", "FC", "LFE", "SL", "SR"),
    "5.1-rear": ("FL", "FR", "FC", "LFE", "RL", "RR"),
    "7.1": ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"),
}


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

    # Third-party/plugin AppConfig hooks may print startup notices. Keep stdout
    # reserved for the adapter's single machine-readable JSON document.
    with redirect_stdout(sys.stderr):
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


def _safe_asset(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("CamillaDSP fixture path must be non-empty")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("CamillaDSP fixture path escapes its registry root") from error
    if not candidate.is_file():
        raise ValueError(f"CamillaDSP fixture asset is missing: {relative}")
    return candidate


def _rewrite_filter_assets(value: object, *, root: Path) -> object:
    if isinstance(value, list):
        return [_rewrite_filter_assets(item, root=root) for item in value]
    if not isinstance(value, Mapping):
        return copy.deepcopy(value)
    result = {
        str(key): _rewrite_filter_assets(item, root=root) for key, item in value.items()
    }
    filename = result.get("filename")
    if isinstance(filename, str) and filename and not Path(filename).is_absolute():
        result["filename"] = str(_safe_asset(root, filename))
    return result


def benchmark_profile_document(
    *,
    fixture_id: str,
    fixture: Mapping[str, Any],
    asset: Mapping[str, Any],
    asset_root: Path,
    signal_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert a checksummed workload overlay into a device-independent profile."""

    devices = asset.get("devices")
    if not isinstance(devices, Mapping):
        raise ValueError(f"CamillaDSP fixture {fixture_id} has no devices object")
    input_channels = fixture.get("inputChannels")
    output_channels = fixture.get("outputChannels")
    layout = signal_contract.get("layouts", [{}])[0]
    bus_channels = layout.get("channels") if isinstance(layout, Mapping) else None
    if input_channels != output_channels or not isinstance(bus_channels, int):
        raise ValueError(f"CamillaDSP fixture {fixture_id} changes the managed channel layout")
    if not isinstance(input_channels, int) or input_channels > bus_channels:
        raise ValueError(f"CamillaDSP fixture {fixture_id} exceeds the managed channel bus")

    processing: dict[str, Any] = {
        "chunksize": devices.get("chunksize"),
        "samplerate": devices.get("samplerate"),
    }
    if "capture_samplerate" in devices:
        processing["captureSamplerate"] = devices["capture_samplerate"]
    if "resampler" in devices:
        processing["resampler"] = copy.deepcopy(devices["resampler"])
    for key in ("filters", "mixers", "pipeline"):
        if key in asset:
            processing[key] = _rewrite_filter_assets(asset[key], root=asset_root)
    return {
        "schemaVersion": 1,
        "title": f"{BENCHMARK_PROFILE_PREFIX}{fixture_id}",
        "description": str(
            asset.get("description")
            or "Synthetic Open Cinema benchmark workload; not a listening profile."
        ),
        "parameters": [],
        "signalContracts": {
            "input": copy.deepcopy(dict(signal_contract)),
            "output": copy.deepcopy(dict(signal_contract)),
        },
        "processing": processing,
    }


def _source_graph_content():
    from api.models.orchestration import GraphActivation

    candidates = []
    for activation in GraphActivation.objects.select_related(
        "definition", "revision", "definition__owner"
    ).filter(enabled=True):
        if activation.definition.labels.get("openCinemaBenchmark") == BENCHMARK_DEFINITION_LABEL:
            continue
        nodes = activation.revision.content.get("nodes", [])
        if any(
            isinstance(node, Mapping)
            and node.get("type") == "processor.camilladsp-profile-selector"
            for node in nodes
        ):
            candidates.append(activation)
    if len(candidates) != 1:
        raise ValueError(
            "CamillaDSP benchmark fixtures require exactly one active non-benchmark managed graph"
        )
    return candidates[0].definition.owner, copy.deepcopy(candidates[0].revision.content)


def _signal_contract_from_graph(content: Mapping[str, Any]) -> dict[str, Any]:
    decoder = next(
        (
            node
            for node in content.get("nodes", [])
            if isinstance(node, Mapping) and node.get("type") == "processor.pcm-auto-decoder"
        ),
        None,
    )
    configuration = decoder.get("configuration", {}) if isinstance(decoder, Mapping) else {}
    layout_name = configuration.get("workingLayout")
    rate = configuration.get("workingRate")
    sample_format = configuration.get("workingSampleFormat")
    positions = CHANNEL_LAYOUTS.get(layout_name) if isinstance(layout_name, str) else None
    if positions is None or not isinstance(rate, int) or not isinstance(sample_format, str):
        raise ValueError("active benchmark source graph has no resolved decoder working format")
    return {
        "mediaKind": "audio",
        "content": "pcm",
        "sampleFormats": [sample_format],
        "rates": [rate],
        "layouts": [{"channels": len(positions), "positions": list(positions)}],
    }


def _profile_registry(profiles_root: Path) -> dict[str, Any]:
    registry_path = profiles_root / "profiles.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("cannot load the CamillaDSP benchmark profile registry") from error
    if not isinstance(registry, dict) or not isinstance(registry.get("profiles"), list):
        raise ValueError("CamillaDSP benchmark profile registry is invalid")
    return registry


def ensure_camilladsp_fixtures(profiles_root: Path) -> dict[str, Any]:
    """Idempotently publish managed profiles and graph revisions used by benchmarks."""

    from django.db import transaction
    from django.db.models import Max

    from api.audio_v1.catalogue import api_node_type_registry
    from api.models import (
        CamillaDSPProfile,
        GraphDefinition,
        GraphDefinitionKind,
        GraphRevision,
        GraphRevisionState,
    )
    from core.orchestration.camilladsp_profiles import normalize_camilladsp_profile
    from core.orchestration.graph_documents import (
        graph_content_digest,
        normalize_graph_document,
    )
    from core.orchestration.graph_validation import validate_graph_structure
    from core.orchestration.revisions import publish_draft_revision

    profiles_root = profiles_root.resolve()
    registry = _profile_registry(profiles_root)
    benchmark = GraphDefinition.objects.filter(
        labels__openCinemaBenchmark=BENCHMARK_DEFINITION_LABEL
    ).select_related("owner").first()
    if benchmark is None:
        owner, source = _source_graph_content()
    else:
        owner = benchmark.owner
        latest = benchmark.revisions.order_by("-revision_number").first()
        if latest is None:
            raise ValueError("benchmark graph definition has no source revision")
        source = copy.deepcopy(latest.content)
    signal_contract = _signal_contract_from_graph(source)

    with transaction.atomic():
        if benchmark is None:
            benchmark = GraphDefinition(
                name=BENCHMARK_DEFINITION_NAME,
                kind=GraphDefinitionKind.GRAPH,
                owner=owner,
                labels={"openCinemaBenchmark": BENCHMARK_DEFINITION_LABEL},
            )
            benchmark.full_clean()
            benchmark.save()
        elif benchmark.name != BENCHMARK_DEFINITION_NAME:
            raise ValueError("benchmark graph definition identity is ambiguous")

        fixtures: dict[str, dict[str, Any]] = {}
        for fixture in registry["profiles"]:
            if not isinstance(fixture, Mapping) or not isinstance(fixture.get("id"), str):
                raise ValueError("CamillaDSP benchmark registry contains an invalid fixture")
            fixture_id = fixture["id"]
            if fixture.get("inputChannels") != fixture.get("outputChannels"):
                continue
            path = _safe_asset(profiles_root, fixture.get("path"))
            if path.stat().st_size != fixture.get("sizeBytes"):
                raise ValueError(f"CamillaDSP fixture size differs: {fixture_id}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != fixture.get("sha256"):
                raise ValueError(f"CamillaDSP fixture digest differs: {fixture_id}")
            asset = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(asset, Mapping):
                raise ValueError(f"CamillaDSP fixture is not an object: {fixture_id}")
            profile_content = benchmark_profile_document(
                fixture_id=fixture_id,
                fixture=fixture,
                asset=asset,
                asset_root=profiles_root,
                signal_contract=signal_contract,
            )
            normalized = normalize_camilladsp_profile(profile_content)
            profile_name = f"{BENCHMARK_PROFILE_PREFIX}{fixture_id}"
            latest_profile = (
                CamillaDSPProfile.objects.filter(owner=owner, name=profile_name)
                .order_by("-version")
                .first()
            )
            if latest_profile is not None and latest_profile.content_digest == normalized.digest:
                profile = latest_profile
            elif latest_profile is None:
                profile = CamillaDSPProfile(
                    version=1,
                    owner=owner,
                    name=profile_name,
                    description="Managed synthetic benchmark fixture",
                    content=normalized.content,
                )
                profile.save()
            else:
                profile = latest_profile.new_version(
                    content=normalized.content,
                    name=profile_name,
                    description="Managed synthetic benchmark fixture",
                )
                profile.save()

            content = copy.deepcopy(source)
            content["id"] = "graph:benchmark-camilladsp-native-v1"
            metadata = dict(content.get("metadata") or {})
            metadata["name"] = f"Benchmark CamillaDSP: {fixture_id}"
            labels = dict(metadata.get("labels") or {})
            labels["openCinemaBenchmark"] = BENCHMARK_DEFINITION_LABEL
            labels["processorFixture"] = fixture_id
            metadata["labels"] = labels
            content["metadata"] = metadata
            selectors = [
                node
                for node in content.get("nodes", [])
                if isinstance(node, dict)
                and node.get("type") == "processor.camilladsp-profile-selector"
            ]
            if len(selectors) != 1:
                raise ValueError("benchmark graph requires exactly one CamillaDSP selector")
            selectors[0]["configuration"] = {
                "profileId": str(profile.profile_id),
                "profileVersion": profile.version,
            }
            content = normalize_graph_document(content)
            validation = validate_graph_structure(content, registry=api_node_type_registry())
            if not validation.valid:
                raise ValueError(f"benchmark graph fixture is invalid: {fixture_id}")
            content_digest = graph_content_digest(content)
            revision = benchmark.revisions.filter(
                content_digest=content_digest,
                state=GraphRevisionState.PUBLISHED,
            ).first()
            if revision is None:
                revision_number = (
                    benchmark.revisions.aggregate(value=Max("revision_number"))["value"] or 0
                ) + 1
                revision = GraphRevision(
                    definition=benchmark,
                    schema_version=1,
                    revision_number=revision_number,
                    state=GraphRevisionState.DRAFT,
                    author=owner,
                    content=content,
                    content_digest=content_digest,
                    validation_summary=validation.summary(),
                )
                revision.full_clean()
                revision.save()
                revision = publish_draft_revision(
                    revision_id=revision.pk,
                    expected_update_version=revision.update_version,
                    registry=api_node_type_registry(),
                )
            fixtures[fixture_id] = {
                "revisionId": str(revision.pk),
                "profileDigest": profile.content_digest,
                "profileTitle": profile_content["title"],
            }
    return {
        "definitionId": str(benchmark.pk),
        "definitionLabel": BENCHMARK_DEFINITION_LABEL,
        "fixtures": fixtures,
    }


def activate_camilladsp_fixture(profiles_root: Path, fixture_id: str) -> dict[str, Any]:
    from django.db import transaction

    from api.models.orchestration import GraphActivation, GraphDefinition, GraphRevision
    from core.orchestration.activations import activate_graph, deactivate_graph

    prepared = ensure_camilladsp_fixtures(profiles_root)
    try:
        selected = prepared["fixtures"][fixture_id]
    except KeyError as error:
        raise ValueError(f"unknown or topology-changing CamillaDSP fixture: {fixture_id}") from error
    definition = GraphDefinition.objects.get(pk=prepared["definitionId"])
    revision = GraphRevision.objects.get(pk=selected["revisionId"], definition=definition)
    actions = []
    with transaction.atomic():
        for activation in GraphActivation.objects.select_for_update().filter(enabled=True):
            if activation.definition_id == definition.pk:
                continue
            deactivate_graph(
                definition=activation.definition,
                expected_version=activation.desired_state_version,
            )
            actions.append({"action": "deactivate", "definitionId": str(activation.definition_id)})
        current = GraphActivation.objects.select_for_update().filter(definition=definition).first()
        if current is None or not current.enabled or current.revision_id != revision.pk:
            activation = activate_graph(
                definition=definition,
                revision=revision,
                expected_version=current.desired_state_version if current is not None else 0,
            )
            actions.append({"action": "activate", "definitionId": str(definition.pk)})
        else:
            activation = current
    return {
        **prepared,
        "fixtureId": fixture_id,
        "revisionId": str(revision.pk),
        "desiredStateVersion": activation.desired_state_version,
        "profileDigest": selected["profileDigest"],
        "profileTitle": selected["profileTitle"],
        "changed": bool(actions),
        "actions": actions,
        "snapshot": snapshot_document(activation_rows()),
    }


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
    ensure = subcommands.add_parser("ensure-camilladsp-fixtures")
    ensure.add_argument("--profiles-root", type=Path, required=True)
    activate = subcommands.add_parser("activate-camilladsp-fixture")
    activate.add_argument("--profiles-root", type=Path, required=True)
    activate.add_argument("--fixture-id", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    try:
        configure_django(database_path=arguments.database_path)
        if arguments.command == "snapshot":
            result = snapshot_document(activation_rows())
        elif arguments.command == "restore":
            if not arguments.snapshot_stdin:
                raise ValueError("restore requires --snapshot-stdin")
            document = json.load(sys.stdin)
            if not isinstance(document, dict):
                raise ValueError("active-intent snapshot must be an object")
            result = restore_desired_intent(document)
        elif arguments.command == "ensure-camilladsp-fixtures":
            result = ensure_camilladsp_fixtures(arguments.profiles_root)
        else:
            result = activate_camilladsp_fixture(
                arguments.profiles_root,
                arguments.fixture_id,
            )
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
