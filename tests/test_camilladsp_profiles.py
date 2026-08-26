from __future__ import annotations

import copy

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from api.models import CamillaDSPProfile
from core.orchestration.camilladsp_profiles import (
    CamillaDSPProfileError,
    normalize_camilladsp_profile,
    resolve_camilladsp_parameters,
)


def profile_document(*, channels: int = 2) -> dict[str, object]:
    positions = ["FL", "FR"] if channels == 2 else ["FL", "FR", "FC", "LFE", "SL", "SR"]
    contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "rates": [48000],
        "layouts": [{"channels": channels, "positions": positions}],
    }
    return {
        "schemaVersion": 1,
        "title": "Living room",
        "parameters": [
            {
                "name": "gainDb",
                "type": "number",
                "default": -3.0,
                "minimum": -80,
                "maximum": 12,
            }
        ],
        "signalContracts": {"input": copy.deepcopy(contract), "output": contract},
        "processing": {
            "chunksize": 1024,
            "filters": {
                "room_gain": {
                    "type": "Gain",
                    "parameters": {"gain": {"parameter": "gainDb"}},
                }
            },
            "pipeline": [
                {"type": "Filter", "channels": list(range(channels)), "names": ["room_gain"]}
            ],
        },
    }


def test_profile_normalization_is_stable_and_resolves_typed_parameters() -> None:
    document = profile_document()
    reversed_parameters = copy.deepcopy(document)
    reversed_parameters["parameters"] = list(reversed(document["parameters"]))

    first = normalize_camilladsp_profile(document)
    second = normalize_camilladsp_profile(reversed_parameters)

    assert first.digest == second.digest
    assert resolve_camilladsp_parameters(first, {"gainDb": -6}) == {"gainDb": -6}
    with pytest.raises(CamillaDSPProfileError, match="above maximum"):
        resolve_camilladsp_parameters(first, {"gainDb": 20})


def test_profile_rejects_devices_and_undeclared_parameter_references() -> None:
    concrete = profile_document()
    concrete["processing"]["capture"] = {"type": "File", "filename": "transient.raw"}
    with pytest.raises(CamillaDSPProfileError, match="Additional properties"):
        normalize_camilladsp_profile(concrete)

    missing = profile_document()
    missing["processing"]["chunksize"] = {"parameter": "unknown"}
    with pytest.raises(CamillaDSPProfileError, match="undeclared parameter"):
        normalize_camilladsp_profile(missing)


@pytest.mark.django_db
def test_profile_rows_are_immutable_versioned_resources() -> None:
    owner = get_user_model().objects.create_user(username="camilladsp-profile-owner")
    first = CamillaDSPProfile.objects.create(
        version=1,
        owner=owner,
        name="Living room",
        content=profile_document(),
    )

    next_profile = first.new_version(content={**profile_document(), "title": "Living room v2"})
    next_profile.save()

    assert next_profile.profile_id == first.profile_id
    assert next_profile.version == 2
    assert CamillaDSPProfile.objects.latest_versions().get().pk == next_profile.pk
    first.name = "Mutated"
    with pytest.raises(ValidationError, match="immutable"):
        first.save()
