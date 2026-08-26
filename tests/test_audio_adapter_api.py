import wave

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from api.models import ManagedAudioAdapter, OrchestrationEvent

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enable_audio_v1(settings, tmp_path):
    settings.AUDIO_ORCHESTRATION_FEATURES = {
        "orchestration_api": True,
        "runtime_observation": False,
        "shadow_resolution": False,
        "processor_management": False,
        "live_reconciliation": False,
    }
    settings.AUDIO_ADAPTER_MEDIA_ROOT = tmp_path
    with wave.open(str(tmp_path / "loop.wav"), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0" * 1920)


@pytest.fixture
def owner():
    return get_user_model().objects.create_user(username="adapter-api")


@pytest.fixture
def client(owner):
    value = APIClient()
    value.force_authenticate(owner)
    return value


def _receiver(name="ROC input", enabled=False):
    return {
        "schemaVersion": 1,
        "name": name,
        "kind": "roc-receiver",
        "configuration": {"localAddress": "0.0.0.0"},
        "enabled": enabled,
    }


def test_adapter_catalogue_and_crud_keep_desired_observed_separate(client):
    catalogue = client.get("/api/audio/v1/adapter-types")
    assert catalogue.status_code == 200
    assert {item["kind"] for item in catalogue.data["items"]} == {
        "roc-receiver",
        "roc-sender",
        "debug-file-source",
        "debug-file-recorder",
    }

    created = client.post("/api/audio/v1/adapters", _receiver(), format="json")
    assert created.status_code == 201
    adapter_id = created.data["id"]
    assert created.data["desired"]["configuration"]["sourcePort"] == 10001
    assert created.data["observed"]["lifecycle"] == "stopped"
    assert created["ETag"] == '"1"'

    listed = client.get("/api/audio/v1/adapters")
    assert listed.data["pagination"]["total"] == 1
    updated = client.patch(
        f"/api/audio/v1/adapters/{adapter_id}",
        {"enabled": True},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert updated.data["desired"]["enabled"] is True
    assert updated.data["desired"]["updateVersion"] == 2


def test_concurrency_restart_safe_delete_and_audit(client):
    created = client.post("/api/audio/v1/adapters", _receiver(enabled=True), format="json")
    adapter_id = created.data["id"]
    stale = client.patch(
        f"/api/audio/v1/adapters/{adapter_id}",
        {"name": "stale"},
        format="json",
        HTTP_IF_MATCH='"9"',
    )
    assert stale.status_code == 412
    assert stale.data["currentVersion"] == 1

    restarted = client.post(
        f"/api/audio/v1/adapters/{adapter_id}/restart",
        {},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert restarted.data["desired"]["restartGeneration"] == 1
    assert restarted.data["desired"]["updateVersion"] == 2
    enabled_delete = client.delete(
        f"/api/audio/v1/adapters/{adapter_id}",
        HTTP_IF_MATCH='"2"',
    )
    assert enabled_delete.status_code == 409

    disabled = client.patch(
        f"/api/audio/v1/adapters/{adapter_id}",
        {"enabled": False},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    deleted = client.delete(
        f"/api/audio/v1/adapters/{adapter_id}",
        HTTP_IF_MATCH=f'"{disabled.data["desired"]["updateVersion"]}"',
    )
    assert deleted.status_code == 204
    assert not ManagedAudioAdapter.objects.filter(pk=adapter_id).exists()
    assert set(OrchestrationEvent.objects.values_list("event_type", flat=True)) >= {
        "audio-adapter.created",
        "audio-adapter.updated",
        "audio-adapter.restart-requested",
        "audio-adapter.deleted",
    }


def test_validation_and_owner_filtering(client, owner):
    invalid = client.post(
        "/api/audio/v1/adapters",
        {
            "name": "Escape",
            "kind": "debug-file-source",
            "configuration": {"path": "../secret.wav"},
        },
        format="json",
    )
    assert invalid.status_code == 422
    assert invalid.data["errors"][0]["path"] == "configuration.path"

    created = client.post("/api/audio/v1/adapters", _receiver(), format="json")
    other = get_user_model().objects.create_user(username="other-adapter-user")
    other_client = APIClient()
    other_client.force_authenticate(other)
    assert other_client.get(f"/api/audio/v1/adapters/{created.data['id']}").status_code == 404


def test_session_authenticated_adapter_write_uses_csrf(owner):
    owner.set_password("review-password")
    owner.save(update_fields=["password"])
    session_client = APIClient(enforce_csrf_checks=True)
    assert session_client.login(username=owner.username, password="review-password")
    schema = session_client.get("/api/audio/v1/schema")
    token = schema.cookies["csrftoken"].value

    rejected = session_client.post("/api/audio/v1/adapters", _receiver(), format="json")
    accepted = session_client.post(
        "/api/audio/v1/adapters",
        _receiver(),
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert rejected.status_code == 403
    assert accepted.status_code == 201
