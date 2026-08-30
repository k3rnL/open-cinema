import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.test import APIClient

from api.models import (
    AppliedPlanState,
    DiagnosticRecord,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    OrchestrationEvent,
    ResolvedPlan,
    RuntimeProjection,
)

pytestmark = pytest.mark.django_db

REPLAY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "orchestration" / "resolver_replay_pipeline.json"
)


@pytest.fixture(autouse=True)
def enable_audio_v1(settings):
    settings.AUDIO_ORCHESTRATION_FEATURES = {
        "orchestration_api": True,
        "runtime_observation": False,
        "shadow_resolution": False,
        "processor_management": False,
        "live_reconciliation": False,
    }


@pytest.fixture
def api_user():
    return get_user_model().objects.create_user(username="audio-v1-user")


@pytest.fixture
def client(api_user):
    value = APIClient()
    value.force_authenticate(api_user)
    return value


def _graph_content(*, identity="graph:api", name="API graph", kind="graph"):
    return {
        "schemaVersion": 1,
        "id": identity,
        "kind": kind,
        "metadata": {"name": name},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [],
        "edges": [],
        "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
    }


def _camilladsp_profile_content(*, chunksize=1024):
    signal_contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "rates": [48000],
        "layouts": [{"channels": 2, "positions": ["FL", "FR"]}],
    }
    return {
        "schemaVersion": 1,
        "title": "Living room",
        "parameters": [],
        "signalContracts": {
            "input": signal_contract,
            "output": signal_contract,
        },
        "processing": {
            "chunksize": chunksize,
            "filters": {},
            "mixers": {},
            "pipeline": [],
        },
    }


def _published_graph(api_user):
    graph = GraphDefinition.objects.create(name="Published API graph", owner=api_user)
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=api_user,
        content=_graph_content(identity="graph:published"),
    )
    return graph, revision


def _candidate_projection(*, serial="headset-123"):
    return RuntimeProjection.objects.create(
        projection_type="endpoint-candidate",
        subject_key="runtime:7:node:42",
        world_generation=7,
        world_sequence=11,
        observed_at=timezone.now(),
        payload={
            "runtimeKey": "runtime:7:node:42",
            "direction": "output",
            "name": "bluez_output.headset",
            "description": "Living room headset",
            "mediaClass": "Audio/Sink",
            "state": "running",
            "nodeProperties": {
                "device.serial": serial,
                "node.name": "bluez_output.headset",
            },
            "device": {
                "name": "bluez_card.headset",
                "properties": {"api.bluez5.address": "00:11:22:33:44:55"},
            },
            "ports": [],
            "profiles": [],
            "routes": [],
            "audioCapabilities": {
                "formats": [
                    {
                        "content": "pcm",
                        "mediaType": {"value": "audio", "known": True, "choices": []},
                        "mediaSubtype": {"value": "raw", "known": True, "choices": []},
                        "sampleFormat": {"value": "F32LE", "known": True, "choices": []},
                        "rate": {"value": 48000, "known": True, "choices": []},
                        "channels": {"value": 2, "known": True, "choices": []},
                        "positions": {
                            "value": ["FL", "FR"],
                            "known": True,
                            "choices": [],
                        },
                        "codec": {"value": None, "known": False, "choices": []},
                    }
                ],
                "volume": 0.5,
                "mute": False,
                "latency": {"milliseconds": 12.0, "raw": "576/48000", "known": True},
            },
            "default": True,
            "linked": True,
            "activeSignal": True,
        },
    )


def test_schema_metadata_problem_contract_and_future_version(client, settings):
    response = client.get("/api/audio/v1/schema")

    assert response.status_code == 200
    assert response.data["apiVersion"] == 1
    assert response.data["conventions"]["optimisticConcurrency"]["requestHeader"] == ("If-Match")
    assert response["Open-Cinema-API-Version"] == "1"

    future = client.get(
        "/api/audio/v1/schema",
        HTTP_OPEN_CINEMA_API_VERSION="2",
    )
    assert future.status_code == 406
    assert future.data["code"] == "unsupported-api-version"
    assert future["Content-Type"].startswith("application/problem+json")

    settings.AUDIO_ORCHESTRATION_FEATURES["orchestration_api"] = False
    disabled = client.get("/api/audio/v1/schema")
    assert disabled.status_code == 503
    assert disabled.data["code"] == "orchestration-api-disabled"


def test_schema_bootstraps_csrf_for_session_authenticated_writes(api_user):
    api_user.set_password("review-password")
    api_user.save(update_fields=["password"])
    session_client = APIClient(enforce_csrf_checks=True)
    assert session_client.login(username=api_user.username, password="review-password")

    schema = session_client.get("/api/audio/v1/schema")

    assert schema.status_code == 200
    assert "csrftoken" in schema.cookies
    token = schema.cookies["csrftoken"].value
    graph = {
        "name": "Session-authenticated graph",
        "kind": "graph",
    }

    rejected = session_client.post("/api/audio/v1/graphs", graph, format="json")
    assert rejected.status_code == 403
    assert "CSRF" in rejected.data["detail"]

    accepted = session_client.post(
        "/api/audio/v1/graphs",
        graph,
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert accepted.status_code == 201


def test_runtime_snapshot_reports_unavailable_without_hiding_desired_api(client):
    response = client.get("/api/audio/v1/runtime/snapshot")

    assert response.status_code == 200
    assert response.data["runtimeAvailable"] is False
    assert response.data["items"] == []


def test_schema_and_openapi_documents_are_valid_and_complete(client):
    schemas = client.get("/api/audio/v1/schemas")
    openapi = client.get("/api/audio/v1/openapi.json")
    catalogue = client.get("/api/audio/v1/node-types")

    assert schemas.status_code == openapi.status_code == catalogue.status_code == 200
    for schema in schemas.data["schemas"].values():
        Draft202012Validator.check_schema(schema)
    assert openapi.data["openapi"] == "3.1.0"
    assert "/graphs/{definitionId}/revisions" in openapi.data["paths"]
    assert "Problem" in openapi.data["components"]["schemas"]
    by_id = {item["id"]: item for item in catalogue.data["items"]}
    assert by_id["processor.pcm-auto-decoder"]["available"] is True
    assert by_id["processor.camilladsp-profile-selector"]["ports"][0]["contract"]["content"] == (
        "pcm"
    )
    assert "/camilladsp/profiles" in openapi.data["paths"]


def test_camilladsp_profiles_are_versioned_reusable_resources(client):
    created = client.post(
        "/api/audio/v1/camilladsp/profiles",
        {
            "name": "Living room",
            "description": "Main loudspeaker calibration",
            "content": _camilladsp_profile_content(),
        },
        format="json",
    )

    assert created.status_code == 201
    assert created.data["version"] == 1
    assert created.data["content"]["processing"]["chunksize"] == 1024
    profile_id = created.data["profileId"]

    second = client.post(
        "/api/audio/v1/camilladsp/profiles",
        {
            "profileId": profile_id,
            "content": _camilladsp_profile_content(chunksize=2048),
        },
        format="json",
    )
    assert second.status_code == 201
    assert second.data["profileId"] == profile_id
    assert second.data["version"] == 2

    latest = client.get("/api/audio/v1/camilladsp/profiles")
    history = client.get(
        f"/api/audio/v1/camilladsp/profiles?profileId={profile_id}&allVersions=true"
    )
    detail = client.get(f"/api/audio/v1/camilladsp/profiles/{created.data['id']}")

    assert [item["version"] for item in latest.data["items"]] == [2]
    assert [item["version"] for item in history.data["items"]] == [2, 1]
    assert detail.data["version"] == 1


def test_graph_revision_workflow_is_versioned_and_optimistic(client):
    graph_response = client.post(
        "/api/audio/v1/graphs",
        {"name": "Living room", "kind": "graph", "labels": {"room": "living"}},
        format="json",
    )
    assert graph_response.status_code == 201
    graph_id = graph_response.data["id"]

    revision_response = client.post(
        f"/api/audio/v1/graphs/{graph_id}/revisions",
        {"schemaVersion": 1, "content": _graph_content()},
        format="json",
    )
    assert revision_response.status_code == 201
    assert revision_response["ETag"] == '"1"'
    revision_id = revision_response.data["id"]

    missing = client.patch(
        f"/api/audio/v1/revisions/{revision_id}",
        {"content": _graph_content(name="Edited")},
        format="json",
    )
    assert missing.status_code == 428
    assert missing.data["code"] == "precondition-required"

    edited = client.patch(
        f"/api/audio/v1/revisions/{revision_id}",
        {"content": _graph_content(name="Edited")},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert edited.status_code == 200
    assert edited.data["updateVersion"] == 2

    stale = client.patch(
        f"/api/audio/v1/revisions/{revision_id}",
        {"content": _graph_content(name="Stale")},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert stale.status_code == 412
    assert stale.data["currentVersion"] == 2

    validated = client.post(
        f"/api/audio/v1/revisions/{revision_id}/validate",
        {},
        format="json",
    )
    compared = client.get(f"/api/audio/v1/revisions/{revision_id}/compare?other={revision_id}")
    assert validated.data["valid"] is True
    assert compared.data["semanticEqual"] is True

    published = client.post(
        f"/api/audio/v1/revisions/{revision_id}/publish",
        {},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert published.status_code == 200
    assert published.data["state"] == "published"

    activated = client.post(
        f"/api/audio/v1/revisions/{revision_id}/activate",
        {"parameterBindings": {}, "sceneBindings": {}},
        format="json",
        HTTP_IF_MATCH='"0"',
    )
    assert activated.status_code == 200
    assert activated.data["desiredStateVersion"] == 1

    missing_precondition = client.delete(
        f"/api/audio/v1/graphs/{graph_id}/activation",
    )
    assert missing_precondition.status_code == 428

    stale_deactivation = client.delete(
        f"/api/audio/v1/graphs/{graph_id}/activation",
        HTTP_IF_MATCH='"0"',
    )
    assert stale_deactivation.status_code == 412
    assert stale_deactivation.data["currentVersion"] == 1

    deactivated = client.delete(
        f"/api/audio/v1/graphs/{graph_id}/activation",
        HTTP_IF_MATCH='"1"',
    )
    assert deactivated.status_code == 200
    assert deactivated.data["revisionId"] is None
    assert deactivated.data["desiredStateVersion"] == 2
    assert deactivated["ETag"] == '"2"'

    graph_after_deactivation = client.get(f"/api/audio/v1/graphs/{graph_id}")
    assert graph_after_deactivation.data["activeRevisionId"] is None
    assert graph_after_deactivation.data["desiredStateVersion"] == 2

    repeated = client.delete(
        f"/api/audio/v1/graphs/{graph_id}/activation",
        HTTP_IF_MATCH='"2"',
    )
    assert repeated.data["desiredStateVersion"] == 2

    reactivated = client.post(
        f"/api/audio/v1/revisions/{revision_id}/activate",
        {"parameterBindings": {}, "sceneBindings": {}},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert reactivated.data["revisionId"] == revision_id
    assert reactivated.data["desiredStateVersion"] == 3

    exported = client.get(f"/api/audio/v1/revisions/{revision_id}/export")
    assert exported.data["format"] == "open-cinema.desired-audio-graph/v1"
    dry_import = client.post(
        "/api/audio/v1/graphs/import?dryRun=true",
        exported.data,
        format="json",
    )
    assert dry_import.status_code == 200
    assert dry_import.data["created"] is False
    assert dry_import.data["valid"] is False


def test_subgraphs_share_the_definition_and_revision_contract(client):
    response = client.post(
        "/api/audio/v1/subgraphs",
        {"name": "Room correction", "labels": {}},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["kind"] == "subgraph"
    listed = client.get("/api/audio/v1/subgraphs?limit=10&offset=0")
    assert [item["id"] for item in listed.data["items"]] == [response.data["id"]]


def test_endpoint_inventory_explanation_binding_and_redaction(client):
    _candidate_projection()
    selector = {
        "version": 1,
        "match": "all",
        "predicates": [
            {
                "path": "node.properties.device.serial",
                "operator": "exact",
                "value": "headset-123",
            }
        ],
    }
    created = client.post(
        "/api/audio/v1/endpoints",
        {
            "name": "Headset",
            "direction": "output",
            "selector": selector,
            "tags": ["headset"],
            "groups": ["private-outputs"],
        },
        format="json",
    )
    assert created.status_code == 201
    endpoint_id = created.data["id"]

    candidates = client.get("/api/audio/v1/endpoint-candidates?capability=pcm")
    payload = candidates.data["items"][0]["payload"]
    assert payload["nodeProperties"]["device.serial"] == "[redacted]"
    assert payload["device"]["properties"]["api.bluez5.address"] == "[redacted]"

    explanation = client.get(f"/api/audio/v1/endpoints/{endpoint_id}/candidates")
    assert explanation.data["resolution"]["status"] == "matched"
    assert explanation.data["resolution"]["selectedRuntimeKey"] == "runtime:7:node:42"

    preview = client.post(
        "/api/audio/v1/endpoints/selector-preview",
        {"selector": selector, "direction": "output"},
        format="json",
    )
    assert preview.data["resolution"]["status"] == "matched"
    assert preview.data["persistentDesiredChange"] is False

    bound = client.post(
        f"/api/audio/v1/endpoints/{endpoint_id}/binding",
        {"runtimeKey": "runtime:7:node:42"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert bound.status_code == 200
    assert bound.data["persistentDesiredChange"] is True
    assert bound.data["selectorReview"]["confidence"] == "high"
    assert bound.data["endpoint"]["updateVersion"] == 2

    filtered = client.get("/api/audio/v1/endpoints?tag=headset&group=private-outputs")
    assert filtered.data["pagination"]["total"] == 1


def test_plan_history_current_and_side_effect_free_dry_run(client, api_user):
    graph, revision = _published_graph(api_user)
    plan = ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=1,
        world_generation=3,
        world_sequence=9,
        resolution_mode="live",
        status="resolved",
        document={"world": {"version": "3:9:1:1:1:1:1"}, "paths": {}},
        explanation={"kind": "audio-resolution", "status": "resolved"},
    )
    AppliedPlanState.objects.create(
        graph_definition=graph,
        current_plan=plan,
        transition_generation=1,
        status="converged",
    )

    history = client.get(f"/api/audio/v1/plans/history?graphId={graph.pk}")
    current = client.get(f"/api/audio/v1/plans/current?graphId={graph.pk}")
    assert history.data["items"][0]["runtimeVersion"] == "3:9:1:1:1:1:1"
    assert current.data["items"][0]["applied"]["status"] == "converged"

    count = ResolvedPlan.objects.count()
    replay = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
    dry_run = client.post("/api/audio/v1/plans/dry-run", replay, format="json")
    assert dry_run.status_code == 200
    assert dry_run.data["dryRun"] is True
    assert dry_run.data["persisted"] is False
    assert dry_run.data["audioMutated"] is False
    assert ResolvedPlan.objects.count() == count


def test_runtime_readiness_diagnostics_authorization_and_redaction(client, api_user):
    _candidate_projection()
    DiagnosticRecord.objects.create(
        category="wireplumber.snapshot",
        payload={"device.serial": "private-value"},
    )
    snapshot = client.get("/api/audio/v1/runtime/snapshot?types=endpoint-candidate")
    readiness = client.get("/api/audio/v1/runtime/readiness")
    denied = client.get("/api/audio/v1/runtime/diagnostics")

    assert snapshot.data["representation"] == "observedRuntime"
    assert snapshot.data["runtimeAvailable"] is True
    assert readiness.data["desiredEditingAvailable"] is True
    assert readiness.data["liveControlsAvailable"] is False
    assert denied.status_code == 403

    staff = get_user_model().objects.create_user(username="audio-v1-staff", is_staff=True)
    admin_client = APIClient()
    admin_client.force_authenticate(staff)
    bundle = admin_client.get("/api/audio/v1/runtime/diagnostics")
    assert bundle.status_code == 200
    assert bundle.data["administrative"] is True
    assert bundle.data["diagnostics"][0]["payload"]["device.serial"] == "private-value"


def test_typed_expiring_overrides_are_creator_scoped_and_cancellable(client):
    expires = timezone.now() + timedelta(hours=1)
    created = client.post(
        "/api/audio/v1/overrides",
        {
            "scopeType": "endpoint",
            "scopeId": "selector:main-output",
            "value": "endpoint:headset",
            "priority": 150,
            "reason": "Private listening for one hour",
            "expiresAt": expires.isoformat(),
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["mutationKind"] == "temporaryOverride"
    assert created.data["persistentDesiredChange"] is False
    assert created.data["active"] is True

    listed = client.get("/api/audio/v1/overrides?active=true")
    assert listed.data["pagination"]["total"] == 1
    cancelled = client.post(
        f"/api/audio/v1/overrides/{created.data['id']}/cancel",
        {},
        format="json",
    )
    assert cancelled.data["active"] is False
    assert cancelled.data["cancelledAt"] is not None


def test_sse_resumption_reports_gap_and_full_snapshot(client, api_user):
    _candidate_projection()
    graph = GraphDefinition.objects.create(name="Event graph", owner=api_user)
    discarded = OrchestrationEvent.objects.create(
        correlation_id=uuid.uuid4(),
        graph_definition=graph,
        event_type="runtime.snapshot",
        payload={"state": "old"},
    )
    discarded.delete()
    event = OrchestrationEvent.objects.create(
        correlation_id=uuid.uuid4(),
        graph_definition=graph,
        event_type="endpoint.changed",
        payload={"device.serial": "secret", "available": True},
    )

    response = client.get(
        "/api/audio/v1/events?follow=false",
        HTTP_LAST_EVENT_ID="0",
    )
    stream = iter(response.streaming_content)
    retry = next(stream).decode()
    snapshot = next(stream).decode()
    response.close()

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Open-Cinema-Event-Gap"] == "true"
    assert retry == "retry: 2000\n\n"
    assert "event: snapshot" in snapshot
    assert '"replaceLocalState":true' in snapshot
    assert f"id: {event.sequence}" in snapshot

    resumed = client.get(
        "/api/audio/v1/events?follow=false&types=endpoint",
        HTTP_LAST_EVENT_ID=str(event.sequence - 1),
    )
    resumed_stream = iter(resumed.streaming_content)
    next(resumed_stream)
    item = next(resumed_stream).decode()
    resumed.close()
    assert "event: endpoint" in item
    assert '"device.serial":"[redacted]"' in item


def test_fresh_sse_subscription_starts_with_current_snapshot_not_event_history(client, api_user):
    _candidate_projection()
    graph = GraphDefinition.objects.create(name="Fresh event graph", owner=api_user)
    event = OrchestrationEvent.objects.create(
        correlation_id=uuid.uuid4(),
        graph_definition=graph,
        event_type="transition.completed",
        payload={"historical": True},
    )

    response = client.get("/api/audio/v1/events?follow=false")
    stream = iter(response.streaming_content)
    retry = next(stream).decode()
    snapshot = next(stream).decode()
    remaining = b"".join(stream).decode()
    response.close()

    assert retry == "retry: 2000\n\n"
    assert "event: snapshot" in snapshot
    assert '"reason":"initial-sync"' in snapshot
    assert f"id: {event.sequence}" in snapshot
    assert "event: transition" not in remaining


def test_owner_scoping_returns_not_found_for_other_users(client):
    other = get_user_model().objects.create_user(username="audio-v1-other")
    graph = GraphDefinition.objects.create(name="Other graph", owner=other)

    response = client.get(f"/api/audio/v1/graphs/{graph.pk}")

    assert response.status_code == 404
    assert response.data["code"] == "not-found"
