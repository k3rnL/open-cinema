from __future__ import annotations

import importlib.util
import copy
from pathlib import Path
import sys
import uuid

import pytest
from django.contrib.auth import get_user_model

from api.models import (
    CamillaDSPProfile,
    GraphActivation,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.activations import activate_graph

ROOT = Path(__file__).parents[1]
BENCHMARKS = ROOT / "deployment" / "benchmarks"
MODULE_PATH = ROOT / "deployment" / "benchmarks" / "benchmark_intent_adapter.py"
SPEC = importlib.util.spec_from_file_location("open_cinema_benchmark_intent_adapter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def test_semantic_snapshot_ignores_disabled_rows_and_generated_versions() -> None:
    rows = [
        {
            "definitionId": "b",
            "revisionId": "revision-b",
            "enabled": False,
            "parameterBindings": {},
            "sceneBindings": {},
            "desiredStateVersion": 99,
        },
        {
            "definitionId": "a",
            "revisionId": "revision-a",
            "enabled": True,
            "parameterBindings": {"gain": 0.5},
            "sceneBindings": {"room": "main"},
            "desiredStateVersion": 3,
        },
    ]

    first = adapter.snapshot_document(rows)
    rows[0]["desiredStateVersion"] = 100
    rows[1]["desiredStateVersion"] = 4
    second = adapter.snapshot_document(rows)

    assert first["active"] == [
        {
            "definitionId": "a",
            "revisionId": "revision-a",
            "parameterBindings": {"gain": 0.5},
            "sceneBindings": {"room": "main"},
        }
    ]
    assert first["semanticDigest"] == second["semanticDigest"]
    assert first["observedVersions"] != second["observedVersions"]


def test_reconciliation_plan_is_minimal_and_compare_and_swap_versioned() -> None:
    expected = [
        {
            "definitionId": "keep",
            "revisionId": "r1",
            "parameterBindings": {},
            "sceneBindings": {},
        },
        {
            "definitionId": "replace",
            "revisionId": "r2",
            "parameterBindings": {"profile": "cinema"},
            "sceneBindings": {},
        },
    ]
    current = [
        {
            "definitionId": "extra",
            "revisionId": "rx",
            "enabled": True,
            "parameterBindings": {},
            "sceneBindings": {},
            "desiredStateVersion": 7,
        },
        {
            "definitionId": "keep",
            "revisionId": "r1",
            "enabled": True,
            "parameterBindings": {},
            "sceneBindings": {},
            "desiredStateVersion": 2,
        },
        {
            "definitionId": "replace",
            "revisionId": "r1",
            "enabled": False,
            "parameterBindings": {},
            "sceneBindings": {},
            "desiredStateVersion": 9,
        },
    ]

    assert adapter.reconciliation_plan(expected, current) == [
        {
            "action": "deactivate",
            "definitionId": "extra",
            "expectedVersion": 7,
        },
        {
            "action": "activate",
            "definitionId": "replace",
            "revisionId": "r2",
            "parameterBindings": {"profile": "cinema"},
            "sceneBindings": {},
            "expectedVersion": 9,
        },
    ]


@pytest.mark.django_db
def test_restore_uses_activation_services_and_restores_semantic_intent() -> None:
    owner = get_user_model().objects.create_user(username="benchmark-intent-owner")
    graph = GraphDefinition.objects.create(name="Prepared graph", owner=owner)
    first = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={"revision": 1},
    )
    second = GraphRevision.objects.create(
        definition=graph,
        revision_number=2,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={"revision": 2},
    )
    prepared = activate_graph(
        definition=graph,
        revision=first,
        expected_version=0,
        parameter_bindings={"volume": 0.8},
    )
    expected = adapter.snapshot_document(adapter.activation_rows())

    activate_graph(
        definition=graph,
        revision=second,
        expected_version=prepared.desired_state_version,
        parameter_bindings={"volume": 0.2},
    )
    extra_graph = GraphDefinition.objects.create(name="Unexpected graph", owner=owner)
    extra_revision = GraphRevision.objects.create(
        definition=extra_graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content={},
    )
    activate_graph(definition=extra_graph, revision=extra_revision, expected_version=0)

    result = adapter.restore_desired_intent(expected)

    restored = GraphActivation.objects.get(definition=graph)
    unexpected = GraphActivation.objects.get(definition=extra_graph)
    assert result["changed"] is True
    assert result["snapshot"]["semanticDigest"] == expected["semanticDigest"]
    assert restored.enabled is True
    assert restored.revision == first
    assert restored.parameter_bindings == {"volume": 0.8}
    assert unexpected.enabled is False


def test_deployment_adapter_contains_no_direct_database_mutation() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in source
    assert "UPDATE API_" not in source
    assert "DELETE FROM" not in source
    assert "ACTIVATE_GRAPH(" in source
    assert "DEACTIVATE_GRAPH(" in source


def test_django_startup_notices_cannot_contaminate_adapter_json(
    monkeypatch, capsys, tmp_path
) -> None:
    import django

    monkeypatch.setattr(django, "setup", lambda: print("plugin startup notice"))

    adapter.configure_django(database_path=tmp_path / "db.sqlite3")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "plugin startup notice\n"


def managed_graph_document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": "graph:prepared-managed-chain",
        "kind": "graph",
        "metadata": {"name": "Prepared managed chain", "labels": {}},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": str(uuid.uuid4()),
                    "direction": "input",
                },
            },
            {
                "id": "decoder",
                "type": "processor.pcm-auto-decoder",
                "version": 1,
                "configuration": {
                    "pcmBehavior": "bypass",
                    "encodedBehavior": "decode",
                    "unsupportedBehavior": "error",
                    "workingSampleFormat": "FLOAT32LE",
                    "workingRate": 48_000,
                    "workingLayout": "7.1",
                },
            },
            {
                "id": "dsp",
                "type": "processor.camilladsp-profile-selector",
                "version": 1,
                "configuration": {
                    "profileId": str(uuid.uuid4()),
                    "profileVersion": 1,
                },
            },
            {
                "id": "sink",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": str(uuid.uuid4()),
                    "direction": "output",
                },
            },
        ],
        "edges": [
            {
                "id": "source-to-decoder",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "decoder", "port": "input"},
            },
            {
                "id": "decoder-to-dsp",
                "from": {"node": "decoder", "port": "output"},
                "to": {"node": "dsp", "port": "input"},
            },
            {
                "id": "dsp-to-sink",
                "from": {"node": "dsp", "port": "output"},
                "to": {"node": "sink", "port": "input"},
            },
        ],
        "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
    }


@pytest.mark.django_db
def test_managed_camilladsp_fixtures_are_idempotent_and_switch_supported_intent() -> None:
    owner = get_user_model().objects.create_user(username="benchmark-fixture-owner")
    graph = GraphDefinition.objects.create(name="Prepared managed chain", owner=owner)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=managed_graph_document(),
    )
    activate_graph(definition=graph, revision=revision, expected_version=0)
    expected = adapter.snapshot_document(adapter.activation_rows())
    profiles_root = BENCHMARKS / "media" / "camilladsp"

    first = adapter.ensure_camilladsp_fixtures(profiles_root)
    profile_count = CamillaDSPProfile.objects.count()
    revision_count = GraphRevision.objects.count()
    second = adapter.ensure_camilladsp_fixtures(profiles_root)

    assert sorted(first["fixtures"]) == [
        "camilladsp-multichannel-128",
        "camilladsp-passthrough-128",
        "camilladsp-production-fir-iir-128",
        "camilladsp-stereo-128",
    ]
    assert second == first
    assert CamillaDSPProfile.objects.count() == profile_count == 4
    assert GraphRevision.objects.count() == revision_count == 5

    selected = adapter.activate_camilladsp_fixture(
        profiles_root,
        "camilladsp-production-fir-iir-128",
    )

    assert selected["changed"] is True
    assert GraphActivation.objects.get(definition=graph).enabled is False
    benchmark = GraphDefinition.objects.get(pk=first["definitionId"])
    assert GraphActivation.objects.get(definition=benchmark).enabled is True

    restored = adapter.restore_desired_intent(copy.deepcopy(expected))
    assert restored["snapshot"]["semanticDigest"] == expected["semanticDigest"]
