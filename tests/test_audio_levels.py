from __future__ import annotations

import math

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    EndpointAudioLevel,
    LogicalEndpoint,
    MasterAudioLevel,
    OrchestrationEvent,
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


def _selector(name: str) -> dict[str, object]:
    return {
        "version": 1,
        "match": "all",
        "predicates": [{"path": "node.name", "operator": "exact", "value": name}],
    }


@pytest.fixture
def staff():
    return get_user_model().objects.create_user(username="level-staff", is_staff=True)


@pytest.fixture
def client(staff):
    value = APIClient()
    value.force_authenticate(staff)
    return value


@pytest.fixture
def output(staff):
    return LogicalEndpoint.objects.create(
        name="Main speakers",
        owner=staff,
        direction="output",
        selector=_selector("speaker-node"),
    )


def _candidate(
    *,
    node_id: int = 10,
    name: str = "speaker-node",
    direction: str = "output",
    volume: float | None = 0.6,
    muted: bool | None = False,
    writable: bool = True,
    generation: int = 3,
    sequence: int = 9,
) -> RuntimeProjection:
    return RuntimeProjection.objects.create(
        projection_type="endpoint-candidate",
        subject_key=f"runtime:{generation}:node:{node_id}",
        world_generation=generation,
        world_sequence=sequence,
        observed_at=timezone.now(),
        payload={
            "runtimeKey": f"runtime:{generation}:node:{node_id}",
            "direction": direction,
            "name": name,
            "mediaClass": "Audio/Sink" if direction == "output" else "Audio/Source",
            "state": "running",
            "nodeProperties": {"node.name": name},
            "audioCapabilities": {
                "formats": [],
                "volume": {
                    "value": volume,
                    "known": volume is not None,
                    "readable": volume is not None,
                    "writable": writable,
                },
                "mute": {
                    "value": muted,
                    "known": muted is not None,
                    "readable": muted is not None,
                    "writable": writable,
                },
                "latency": {"milliseconds": None, "raw": None, "known": False},
            },
        },
    )


def test_audio_level_models_have_neutral_defaults_and_reject_non_finite_values(
    output,
) -> None:
    master = MasterAudioLevel.objects.create()
    endpoint = EndpointAudioLevel.objects.create(endpoint=output)

    assert (master.level, master.muted, master.update_version) == (1.0, False, 1)
    assert (endpoint.level, endpoint.muted, endpoint.update_version) == (1.0, False, 1)
    endpoint.level = math.nan
    with pytest.raises(ValidationError, match="between zero and one"):
        endpoint.full_clean()


def test_master_level_is_persistent_versioned_and_staff_only(client, staff) -> None:
    first = client.get("/api/audio/v1/levels/master")
    assert first.status_code == 200
    assert first.json()["desired"] == {"level": 1.0, "muted": False}
    assert first["ETag"] == '"1"'

    updated = client.patch(
        "/api/audio/v1/levels/master",
        {"level": 0.8, "muted": True},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert updated.status_code == 200
    assert updated.json()["desired"] == {"level": 0.8, "muted": True}
    assert updated.json()["updateVersion"] == 2
    assert MasterAudioLevel.objects.get().level == 0.8
    assert OrchestrationEvent.objects.get().event_type == "audio-level.master-intent"

    stale = client.patch(
        "/api/audio/v1/levels/master",
        {"level": 0.4},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert stale.status_code == 412
    assert stale.json()["currentVersion"] == 2

    regular = get_user_model().objects.create_user(username="level-regular")
    regular_client = APIClient()
    regular_client.force_authenticate(regular)
    forbidden = regular_client.patch(
        "/api/audio/v1/levels/master",
        {"level": 0.2},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert forbidden.status_code == 403


@pytest.mark.parametrize("level", (-0.01, 1.01, True, "0.5"))
def test_master_level_rejects_invalid_normalized_values(client, level) -> None:
    client.get("/api/audio/v1/levels/master")
    response = client.patch(
        "/api/audio/v1/levels/master",
        {"level": level},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert response.status_code in {400, 422}
    assert MasterAudioLevel.objects.get().level == 1.0


def test_disconnected_endpoint_keeps_a_neutral_inspectable_preference(client, output) -> None:
    response = client.get(f"/api/audio/v1/endpoints/{output.pk}/level")

    assert response.status_code == 200
    assert response.json()["availability"] == "unavailable"
    assert response.json()["desired"] == {"level": 1.0, "muted": False}
    assert response.json()["runtimeVersion"] is None
    assert response.json()["capabilities"]["volume"]["writable"] is False
    assert EndpointAudioLevel.objects.filter(endpoint=output).exists()


def test_output_level_reports_factors_and_accepts_current_writable_candidate(
    client, output
) -> None:
    _candidate()
    MasterAudioLevel.objects.create(level=0.8)
    initial = client.get(f"/api/audio/v1/endpoints/{output.pk}/level")
    assert initial.status_code == 200
    assert initial.json()["runtimeVersion"] == "runtime:3:node:10"
    assert initial.json()["effective"] == {"level": 0.8, "muted": False}
    assert initial.json()["observed"] == {
        "level": 0.6,
        "muted": False,
        "known": True,
    }
    assert initial.json()["capabilities"]["volume"]["writable"] is True

    updated = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"level": 0.5, "runtimeVersion": "runtime:3:node:10"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert updated.status_code == 200
    assert updated.json()["desired"]["level"] == 0.5
    assert updated.json()["effective"]["level"] == 0.4
    assert updated.json()["applying"] is True
    event = OrchestrationEvent.objects.get(event_type="audio-level.endpoint-intent")
    assert event.payload["endpointId"] == str(output.pk)
    assert "runtime:3:node:10" not in str(event.payload)


def test_endpoint_runtime_guard_ignores_unrelated_world_sequence_changes(client, output) -> None:
    projection = _candidate(sequence=9)
    current = client.get(f"/api/audio/v1/endpoints/{output.pk}/level").json()

    projection.world_sequence = 10
    projection.save(update_fields=("world_sequence",))
    updated = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"level": 0.5, "runtimeVersion": current["runtimeVersion"]},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert updated.status_code == 200
    assert updated.json()["runtimeVersion"] == "runtime:3:node:10"


def test_output_level_treats_float32_observation_as_converged(client, output) -> None:
    _candidate(volume=0.8500000238418579)
    EndpointAudioLevel.objects.create(endpoint=output, level=0.85)

    response = client.get(f"/api/audio/v1/endpoints/{output.pk}/level")

    assert response.status_code == 200
    assert response.json()["effective"]["level"] == 0.85
    assert response.json()["applying"] is False


def test_endpoint_mutation_rejects_stale_read_only_unavailable_and_ambiguous(
    client, output
) -> None:
    _candidate(writable=False)
    client.get(f"/api/audio/v1/endpoints/{output.pk}/level")

    stale = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"level": 0.5, "runtimeVersion": "runtime:2:node:10"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "runtime-version-stale"

    read_only = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"level": 0.5, "runtimeVersion": "runtime:3:node:10"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert read_only.status_code == 409
    assert read_only.json()["code"] == "endpoint-volume-read-only"

    RuntimeProjection.objects.all().delete()
    unavailable = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"muted": True, "runtimeVersion": "runtime:3:node:10"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "endpoint-unavailable"

    _candidate(node_id=10)
    _candidate(node_id=11)
    ambiguous = client.patch(
        f"/api/audio/v1/endpoints/{output.pk}/level",
        {"muted": True, "runtimeVersion": "runtime:3:node:10"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert ambiguous.status_code == 409
    assert ambiguous.json()["code"] == "endpoint-ambiguous"
    assert EndpointAudioLevel.objects.get(endpoint=output).update_version == 1


def test_input_level_does_not_multiply_master(client, staff) -> None:
    endpoint = LogicalEndpoint.objects.create(
        name="TV input",
        owner=staff,
        direction="input",
        selector=_selector("tv-input"),
    )
    _candidate(name="tv-input", direction="input", volume=0.7)
    MasterAudioLevel.objects.create(level=0.2, muted=True)
    EndpointAudioLevel.objects.create(endpoint=endpoint, level=0.6)

    response = client.get(f"/api/audio/v1/endpoints/{endpoint.pk}/level")

    assert response.json()["scope"] == "input-level"
    assert response.json()["master"] is None
    assert response.json()["effective"] == {"level": 0.6, "muted": False}
