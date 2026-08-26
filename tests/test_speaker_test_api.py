from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.audio_v1 import speaker_test_views
from api.models import RuntimeProjection
from core.orchestration.speaker_test import SpeakerTestInvalidChannel

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enable_audio_v1(settings):
    settings.AUDIO_ORCHESTRATION_FEATURES = {
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": False,
        "processor_management": False,
        "live_reconciliation": False,
    }


@pytest.fixture
def staff_client():
    user = get_user_model().objects.create_user(username="speaker-admin", is_staff=True)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def regular_client():
    user = get_user_model().objects.create_user(username="speaker-user")
    client = APIClient()
    client.force_authenticate(user)
    return client


def _candidate(*, subject="runtime:5:node:20", managed=False, known=True):
    channels = ["FL", "FR", "FC", "LFE", "SL", "SR"]
    return RuntimeProjection.objects.create(
        projection_type="endpoint-candidate",
        subject_key=subject,
        world_generation=5,
        world_sequence=9,
        observed_at=timezone.now(),
        payload={
            "runtimeKey": subject,
            "direction": "output",
            "name": "alsa_output.surround",
            "description": "Main surround speakers",
            "mediaClass": "Audio/Sink",
            "origin": "managed-adapter" if managed else "runtime-device",
            "managed": managed,
            "error": None,
            "device": {"description": "USB amplifier"},
            "ports": [
                {
                    "direction": "input",
                    "channel": channel,
                    "properties": {"port.physical": "true", "port.id": str(index)},
                }
                for index, channel in enumerate(channels)
            ],
            "audioCapabilities": {
                "formats": [
                    {
                        "content": "pcm",
                        "positions": {"known": known, "value": channels},
                        "channels": {"known": True, "value": len(channels)},
                        "rate": {"known": True, "value": 48000},
                    }
                ]
            },
        },
    )


class FakeController:
    def __init__(self):
        self.active = {
            "active": False,
            "token": None,
            "runtimeKey": None,
            "outputName": None,
            "channel": None,
            "startedAt": None,
            "endsAt": None,
            "durationMs": None,
        }
        self.starts = []
        self.stops = 0

    def status(self):
        return self.active

    def start(self, output, channel):
        if channel not in output.channels:
            raise SpeakerTestInvalidChannel("channel is absent")
        self.starts.append((output.runtime_key, channel))
        now = timezone.now()
        self.active = {
            "active": True,
            "token": "2cd592c4-5c6c-41a8-a7e8-4acbed7bfb24",
            "runtimeKey": output.runtime_key,
            "outputName": output.name,
            "channel": channel,
            "startedAt": now.isoformat(),
            "endsAt": (now + timedelta(seconds=2)).isoformat(),
            "durationMs": 2000,
        }
        return self.active

    def stop(self):
        self.stops += 1
        self.active = {key: None for key in self.active}
        self.active["active"] = False
        return self.active


@pytest.fixture
def controller(monkeypatch):
    value = FakeController()
    monkeypatch.setattr(speaker_test_views, "speaker_test_controller", lambda: value)
    return value


def test_staff_discovers_only_current_physical_outputs(staff_client, controller):
    eligible = _candidate()
    _candidate(subject="runtime:5:node:21", managed=True)
    _candidate(subject="runtime:5:node:22", known=False)

    response = staff_client.get("/api/audio/v1/speaker-test")

    assert response.status_code == 200
    assert [item["runtimeKey"] for item in response.data["outputs"]] == [eligible.subject_key]
    output = response.data["outputs"][0]
    assert [item["position"] for item in output["channels"]] == [
        "FL",
        "FR",
        "FC",
        "LFE",
        "SL",
        "SR",
    ]
    assert output["channels"][2]["label"] == "Front center"


def test_speaker_test_is_staff_only(regular_client, controller):
    _candidate()

    assert regular_client.get("/api/audio/v1/speaker-test").status_code == 403
    assert (
        regular_client.post(
            "/api/audio/v1/speaker-test",
            {"runtimeKey": "runtime:5:node:20", "channel": "FL"},
            format="json",
        ).status_code
        == 403
    )
    assert regular_client.delete("/api/audio/v1/speaker-test").status_code == 403
    assert controller.starts == []


def test_staff_starts_and_stops_selected_channel(staff_client, controller):
    candidate = _candidate()

    started = staff_client.post(
        "/api/audio/v1/speaker-test",
        {"runtimeKey": candidate.subject_key, "channel": "FC"},
        format="json",
    )
    stopped = staff_client.delete("/api/audio/v1/speaker-test")

    assert started.status_code == 202
    assert started.data["active"] is True
    assert started.data["channel"] == "FC"
    assert controller.starts == [(candidate.subject_key, "FC")]
    assert stopped.data["active"] is False


def test_start_rejects_stale_output_and_invalid_channel(staff_client, controller):
    candidate = _candidate()
    stale = staff_client.post(
        "/api/audio/v1/speaker-test",
        {"runtimeKey": "runtime:4:node:20", "channel": "FL"},
        format="json",
    )
    invalid = staff_client.post(
        "/api/audio/v1/speaker-test",
        {"runtimeKey": candidate.subject_key, "channel": "UNKNOWN"},
        format="json",
    )

    assert stale.status_code == 409
    assert stale.data["code"] == "speaker-test-output-stale"
    assert invalid.status_code == 422
    assert invalid.data["code"] == "speaker-test-channel-invalid"
    assert controller.starts == []
