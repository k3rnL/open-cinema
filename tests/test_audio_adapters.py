import wave

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from api.models import ManagedAudioAdapter, ManagedAudioAdapterRuntimeState
from core.orchestration.audio_adapters import (
    ADAPTER_TYPES,
    DEBUG_FILE_RECORDER,
    DEBUG_FILE_SOURCE,
    ROC_RECEIVER,
    ROC_SENDER,
    AudioAdapterConfigurationError,
    adapter_type_catalogue,
    normalize_adapter_configuration,
    resolve_adapter_media_path,
)

pytestmark = pytest.mark.django_db


def _wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0" * 1920)


def test_adapter_models_keep_desired_and_runtime_state_separate():
    owner = get_user_model().objects.create_user(username="adapter-owner")
    adapter = ManagedAudioAdapter.objects.create(
        owner=owner,
        name="Network input",
        kind=ROC_RECEIVER,
        configuration={"localAddress": "0.0.0.0"},
    )
    state = ManagedAudioAdapterRuntimeState.objects.create(adapter=adapter, process_id=123)

    state.lifecycle = "ready"
    state.save(update_fields=["lifecycle", "updated_at"])
    adapter.refresh_from_db()
    assert adapter.update_version == 1
    assert ManagedAudioAdapter.objects.visible_to(owner).get() == adapter

    adapter.configuration = []
    with pytest.raises(ValidationError):
        adapter.full_clean()


def test_catalogue_contains_four_schema_driven_endpoint_types():
    documents = adapter_type_catalogue()
    assert {item["kind"] for item in documents} == set(ADAPTER_TYPES)
    assert {item["direction"] for item in documents} == {"input", "output"}
    assert all(item["schemaVersion"] == 1 for item in documents)


def test_roc_configuration_defaults_and_validation():
    receiver = normalize_adapter_configuration(ROC_RECEIVER, {"localAddress": "0.0.0.0"})
    sender = normalize_adapter_configuration(ROC_SENDER, {"remoteAddress": "192.168.1.30"})

    assert receiver["sourcePort"] == 10001
    assert receiver["resamplerProfile"] == "medium"
    assert sender["fecCode"] == "disable"

    with pytest.raises(AudioAdapterConfigurationError, match="valid IPv4 or IPv6"):
        normalize_adapter_configuration(ROC_SENDER, {"remoteAddress": "not an address"})
    with pytest.raises(AudioAdapterConfigurationError, match="must be distinct"):
        normalize_adapter_configuration(
            ROC_RECEIVER,
            {"localAddress": "0.0.0.0", "sourcePort": 10001, "repairPort": 10001},
        )


def test_file_paths_are_confined_and_source_must_exist(tmp_path):
    media_root = tmp_path / "media"
    source = media_root / "samples" / "loop.wav"
    _wav(source)

    normalized = normalize_adapter_configuration(
        DEBUG_FILE_SOURCE,
        {"path": "samples/loop.wav"},
        media_root=media_root,
    )
    recorder = normalize_adapter_configuration(
        DEBUG_FILE_RECORDER,
        {"path": "recordings/output.wav"},
        media_root=media_root,
    )
    assert normalized["path"] == "samples/loop.wav"
    assert recorder["rate"] == 48000

    for hostile in ("../secret.wav", "/tmp/secret.wav", "samples/not-wave.flac"):
        with pytest.raises(AudioAdapterConfigurationError):
            resolve_adapter_media_path(hostile, root=media_root)
    with pytest.raises(AudioAdapterConfigurationError, match="does not exist"):
        normalize_adapter_configuration(
            DEBUG_FILE_SOURCE,
            {"path": "missing.wav"},
            media_root=media_root,
        )
