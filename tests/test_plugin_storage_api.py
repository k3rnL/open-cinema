from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from core.plugin_system.storage import PLUGIN_STORAGE_SCHEMAS

pytestmark = pytest.mark.django_db

PLUGIN_ID = "test.storage"
SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string"}},
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def registered_plugin_schemas():
    PLUGIN_STORAGE_SCHEMAS.clear()
    PLUGIN_STORAGE_SCHEMAS.register(
        plugin_id=PLUGIN_ID,
        schema_id="test.storage.preset",
        schema_version=1,
        schema=SCHEMA,
    )
    PLUGIN_STORAGE_SCHEMAS.register(
        plugin_id=PLUGIN_ID,
        schema_id="test.storage.source",
        schema_version=1,
        schema=SCHEMA,
    )
    yield
    PLUGIN_STORAGE_SCHEMAS.clear()


@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        username="plugin-storage-admin",
        password="admin",
        is_staff=True,
    )
    client.force_login(user)
    return client


def test_plugin_storage_api_is_staff_only(client) -> None:
    url = "/api/plugin-platform/v2/plugins/test.storage/documents/test.storage.presets"

    anonymous = client.get(url)
    user = get_user_model().objects.create_user(username="plugin-storage-user")
    client.force_login(user)
    ordinary = client.get(url)

    assert anonymous.status_code in {401, 403}
    assert ordinary.status_code == 403


def test_document_api_validates_registered_schema_and_preconditions(staff_client) -> None:
    collection_url = "/api/plugin-platform/v2/plugins/test.storage/documents/test.storage.presets"
    created = staff_client.post(
        collection_url,
        data=json.dumps(
            {
                "id": "cinema",
                "schemaId": "test.storage.preset",
                "schemaVersion": 1,
                "document": {"name": "Cinema"},
            }
        ),
        content_type="application/json",
        HTTP_OPEN_CINEMA_API_VERSION="2",
    )
    detail_url = f"{collection_url}/cinema"
    loaded = staff_client.get(detail_url)
    stale = staff_client.put(
        detail_url,
        data=json.dumps(
            {
                "schemaId": "test.storage.preset",
                "schemaVersion": 1,
                "document": {"name": "Stale"},
            }
        ),
        content_type="application/json",
        HTTP_IF_MATCH='"9"',
    )
    invalid = staff_client.post(
        collection_url,
        data=json.dumps(
            {
                "id": "invalid",
                "schemaId": "test.storage.preset",
                "schemaVersion": 1,
                "document": {},
            }
        ),
        content_type="application/json",
    )

    assert created.status_code == 201
    assert created.headers["Open-Cinema-API-Version"] == "2"
    assert created.headers["ETag"] == '"1"'
    assert loaded.status_code == 200
    assert loaded.json()["document"] == {"name": "Cinema"}
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale-plugin-data"
    assert invalid.status_code == 400
    assert "required property" in invalid.json()["detail"]


def test_repeatable_instance_and_secret_apis_never_return_secret_value(
    staff_client, tmp_path, settings
) -> None:
    settings.OPEN_CINEMA_PLUGIN_SECRET_DIR = tmp_path / "secrets"
    instance_url = (
        "/api/plugin-platform/v2/plugins/test.storage/" "capabilities/test.storage.source/instances"
    )
    created = staff_client.post(
        instance_url,
        data=json.dumps(
            {
                "id": "main",
                "displayName": "Main",
                "schemaId": "test.storage.source",
                "configurationVersion": 1,
                "configuration": {"name": "Cinema"},
            }
        ),
        content_type="application/json",
    )
    secret_url = "/api/plugin-platform/v2/plugins/test.storage/secrets/test.storage.access-token"
    secret_value = "must-not-appear-in-any-response"
    configured = staff_client.put(
        secret_url,
        data=json.dumps({"value": secret_value}),
        content_type="application/json",
    )
    presence = staff_client.get(secret_url)
    missing_precondition = staff_client.put(
        secret_url,
        data=json.dumps({"value": "replacement"}),
        content_type="application/json",
    )

    assert created.status_code == 201
    assert created.json()["id"] == "main"
    assert configured.status_code == 200
    assert configured.json()["configured"] is True
    assert secret_value not in configured.content.decode()
    assert presence.status_code == 200
    assert secret_value not in presence.content.decode()
    assert missing_precondition.status_code == 428
