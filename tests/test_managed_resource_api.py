import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    ManagedAudioAdapter,
    ManagedAudioAdapterRuntimeState,
    RuntimeProjection,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enable_audio_api(settings):
    settings.AUDIO_ORCHESTRATION_FEATURES = {
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": True,
        "live_reconciliation": True,
    }


@pytest.fixture
def staff_client():
    user = get_user_model().objects.create_user(username="resource-staff", is_staff=True)
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def _projection(projection_type: str, subject: str, payload: dict, sequence: int):
    return RuntimeProjection.objects.create(
        projection_type=projection_type,
        subject_key=subject,
        world_generation=3,
        world_sequence=sequence,
        observed_at=timezone.now(),
        payload=payload,
    )


def test_managed_resources_correlate_adapter_and_processor_without_duplicate_rows(
    staff_client,
) -> None:
    user, client = staff_client
    adapter = ManagedAudioAdapter.objects.create(
        owner=user,
        name="Mac ROC input",
        kind="roc-receiver",
        enabled=True,
        update_version=4,
    )
    ManagedAudioAdapterRuntimeState.objects.create(
        adapter=adapter,
        lifecycle="ready",
        health="healthy",
        runtime_generation=3,
        runtime_key="runtime:3:node:20",
        observed_at=timezone.now(),
    )
    _projection(
        "endpoint-candidate",
        "runtime:3:node:20",
        {
            "runtimeKey": "runtime:3:node:20",
            "managedAdapter": {"id": str(adapter.pk), "kind": "roc-receiver"},
            "device": {"properties": {"device.serial": "private"}},
        },
        9,
    )
    _projection(
        "managed-resource",
        "processor:camilladsp:camilladsp-0:capture",
        {
            "identity": {
                "processorKind": "camilladsp",
                "instanceId": "camilladsp-0",
                "port": "capture",
            },
            "state": "idle",
            "ready": True,
        },
        10,
    )
    _projection(
        "managed-resource",
        "processor:camilladsp:camilladsp-0:playback",
        {
            "identity": {
                "processorKind": "camilladsp",
                "instanceId": "camilladsp-0",
                "port": "playback",
            },
            "state": "idle",
            "ready": True,
        },
        11,
    )
    _projection(
        "processor-health",
        "processor:camilladsp:camilladsp-0",
        {
            "kind": "camilladsp",
            "instanceId": "camilladsp-0",
            "ready": True,
            "health": "healthy",
            "profile": "Living room",
        },
        12,
    )

    response = client.get("/api/audio/v1/runtime/resources")

    assert response.status_code == 200
    assert response.json()["schemaVersion"] == 1
    assert len(response.json()["items"]) == 2
    by_type = {item["resourceType"]: item for item in response.json()["items"]}
    adapter_document = by_type["adapter"]
    assert adapter_document["id"] == f"adapter:{adapter.pk}"
    assert adapter_document["observed"]["health"] == "healthy"
    assert adapter_document["actions"] == [
        {
            "id": "restart",
            "label": "Restart",
            "available": True,
            "reason": None,
            "method": "POST",
            "href": f"/api/audio/v1/adapters/{adapter.pk}/restart",
            "updateVersion": 4,
        }
    ]
    processor = by_type["processor"]
    assert processor["name"] == "CamillaDSP · camilladsp-0"
    assert processor["observed"]["profile"] == "Living room"
    assert len(processor["correlations"]) == 2
    assert processor["actions"][0]["available"] is False
    assert "safe supervisor" in processor["actions"][0]["reason"]


def test_disabled_adapter_and_uncorrelated_processor_explain_read_only_state(
    staff_client,
) -> None:
    user, client = staff_client
    adapter = ManagedAudioAdapter.objects.create(
        owner=user,
        name="Recorder",
        kind="debug-file-recorder",
        enabled=False,
    )
    ManagedAudioAdapterRuntimeState.objects.create(adapter=adapter)
    _projection(
        "managed-resource",
        "processor:pcm-auto-decoder:decoder-0:output",
        {
            "identity": {
                "processorKind": "pcm-auto-decoder",
                "instanceId": "decoder-0",
                "port": "output",
            },
            "state": "suspended",
            "ready": True,
        },
        9,
    )

    response = client.get("/api/audio/v1/runtime/resources")

    by_id = {item["id"]: item for item in response.json()["items"]}
    adapter_action = by_id[f"adapter:{adapter.pk}"]["actions"][0]
    assert adapter_action["available"] is False
    assert adapter_action["reason"] == "Enable this resource before restarting it."
    decoder = by_id["processor:pcm-auto-decoder:decoder-0"]
    assert decoder["observed"]["health"] == "unknown"
    assert decoder["freshness"]["stale"] is False
    assert decoder["actions"][0]["href"] is None


def test_non_staff_resource_view_is_owner_scoped_and_redacted() -> None:
    owner = get_user_model().objects.create_user(username="resource-owner")
    other = get_user_model().objects.create_user(username="resource-other")
    own = ManagedAudioAdapter.objects.create(
        owner=owner, name="Own ROC", kind="roc-receiver", enabled=True
    )
    ManagedAudioAdapterRuntimeState.objects.create(adapter=own)
    foreign = ManagedAudioAdapter.objects.create(
        owner=other, name="Foreign ROC", kind="roc-receiver", enabled=True
    )
    ManagedAudioAdapterRuntimeState.objects.create(adapter=foreign)
    _projection(
        "endpoint-candidate",
        "runtime:3:node:20",
        {
            "managedAdapter": {"id": str(own.pk)},
            "device": {"properties": {"device.serial": "private"}},
        },
        9,
    )
    client = APIClient()
    client.force_authenticate(owner)

    response = client.get("/api/audio/v1/runtime/resources")

    assert [item["name"] for item in response.json()["items"]] == ["Own ROC"]
    evidence = response.json()["items"][0]["correlations"][0]["evidence"]
    assert evidence["device"]["properties"]["device.serial"] == "[redacted]"
