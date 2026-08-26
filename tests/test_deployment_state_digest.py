from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command

from api.models import GraphDefinition
from core.orchestration.deployment_state import dynamic_audio_state_document


@pytest.mark.django_db
def test_dynamic_audio_state_digest_is_stable_and_tracks_user_intent(
    django_user_model,
) -> None:
    user = django_user_model.objects.create_user(username="rollback-owner")
    before = dynamic_audio_state_document()
    repeated = dynamic_audio_state_document()

    assert before == repeated
    assert before["schemaVersion"] == 1
    assert before["models"]["api.graphdefinition"]["count"] == 0

    GraphDefinition.objects.create(owner=user, name="Rollback state", kind="graph")
    after = dynamic_audio_state_document()

    assert after["intentDigest"] != before["intentDigest"]
    assert after["models"]["api.graphdefinition"]["count"] == 1


@pytest.mark.django_db
def test_deployment_state_digest_management_command_is_machine_readable() -> None:
    output = StringIO()

    call_command("deployment_state_digest", stdout=output)

    document = json.loads(output.getvalue())
    assert document["schemaVersion"] == 1
    assert len(document["intentDigest"]) == 64
    assert "audit" in document
