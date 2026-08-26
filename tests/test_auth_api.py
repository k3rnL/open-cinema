from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

pytestmark = pytest.mark.django_db


def _csrf_client() -> tuple[Client, str]:
    client = Client(enforce_csrf_checks=True)
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    return client, client.cookies["csrftoken"].value


def test_session_login_and_logout_use_django_session_and_csrf(settings) -> None:
    settings.AUDIO_ORCHESTRATION_FEATURES = {
        **settings.AUDIO_ORCHESTRATION_FEATURES,
        "orchestration_api": True,
    }
    user = get_user_model().objects.create_user(
        username="admin",
        password="admin",
        is_staff=True,
        is_superuser=True,
    )
    client, csrf_token = _csrf_client()

    anonymous = client.get("/api/auth/session")
    assert anonymous.json() == {"authenticated": False, "user": None}
    assert "no-cache" in anonymous.headers["Cache-Control"]

    missing_csrf = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin"}),
        content_type="application/json",
    )
    assert missing_csrf.status_code == 403

    logged_in = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin", "remember": False}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"] == {
        "id": str(user.pk),
        "username": "admin",
        "name": "admin",
        "email": "",
        "isStaff": True,
        "isSuperuser": True,
    }
    assert client.get("/api/audio/v1/schema").status_code == 200

    rotated_csrf = client.cookies["csrftoken"].value
    missing_logout_csrf = client.post("/api/auth/logout")
    assert missing_logout_csrf.status_code == 403
    logged_out = client.post(
        "/api/auth/logout",
        HTTP_X_CSRFTOKEN=rotated_csrf,
    )
    assert logged_out.status_code == 200
    assert client.get("/api/auth/session").json() == {
        "authenticated": False,
        "user": None,
    }


def test_login_rejects_bad_payload_and_credentials_without_disclosing_users() -> None:
    get_user_model().objects.create_user(username="admin", password="admin")
    client, csrf_token = _csrf_client()

    malformed = client.post(
        "/api/auth/login",
        data="not-json",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "invalid-request"

    incorrect = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "wrong"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    unknown = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "missing", "password": "wrong"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert incorrect.status_code == unknown.status_code == 401
    assert incorrect.json()["detail"] == unknown.json()["detail"]


def test_default_admin_command_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_CINEMA_DEFAULT_ADMIN_PASSWORD", "admin")
    first = StringIO()
    call_command("ensure_default_admin", username="admin", stdout=first)

    user = get_user_model().objects.get(username="admin")
    assert user.is_active and user.is_staff and user.is_superuser
    assert user.check_password("admin")
    assert "created" in first.getvalue()

    second = StringIO()
    call_command("ensure_default_admin", username="admin", stdout=second)
    assert "unchanged" in second.getvalue()
