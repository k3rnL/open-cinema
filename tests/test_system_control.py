from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    OrchestrationEvent,
    RuntimeProjection,
    SystemControlAction,
    SystemControlOperation,
    SystemControlStatus,
)
from api.system_v1 import control

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client():
    user = get_user_model().objects.create_user(username="system-staff", is_staff=True)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def regular_client():
    user = get_user_model().objects.create_user(username="system-regular")
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture(autouse=True)
def available_helper(monkeypatch):
    control._HELPER_CACHE.clear()
    monkeypatch.setattr(control, "_helper_check", lambda action: (True, None))
    monkeypatch.setattr(control, "boot_id", lambda: "boot-a")
    monkeypatch.setattr(control, "service_instance_marker", lambda: "service-a")


def _accepted(command, **kwargs):
    return subprocess.CompletedProcess(command, 0, "", "")


def _action_token(client: APIClient, action_id: str) -> str:
    response = client.get("/api/system/v1/actions")
    assert response.status_code == 200
    action = next(item for item in response.json()["items"] if item["id"] == action_id)
    assert action["available"] is True
    return action["actionToken"]


def test_actions_are_capability_documents_and_non_staff_cannot_invoke(
    regular_client, monkeypatch
) -> None:
    token = _action_token(regular_client, "reboot")
    invoked = []
    monkeypatch.setattr(control.subprocess, "run", lambda *args, **kwargs: invoked.append(args))

    response = regular_client.post(
        "/api/system/v1/actions/reboot",
        {"actionToken": token},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert invoked == []
    assert SystemControlOperation.objects.count() == 0


def test_restart_accepts_only_advertised_component_and_fixed_helper_arguments(
    staff_client, monkeypatch
) -> None:
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return _accepted(command, **kwargs)

    monkeypatch.setattr(control.subprocess, "run", run)
    component = staff_client.get("/api/system/v1/components").json()["items"][0]
    token = component["actions"][0]["actionToken"]
    calls.clear()

    response = staff_client.post(
        "/api/system/v1/components/open-cinema/actions/restart",
        {"actionToken": token, "unit": "ssh.service", "arguments": ["--now"]},
        format="json",
    )

    assert response.status_code == 202
    assert response.json()["action"] == "restart-open-cinema"
    assert response.json()["status"] == "reconnecting"
    assert calls == [
        (
            [
                "/usr/bin/sudo",
                "-n",
                "/usr/local/libexec/open-cinema-system-control",
                "restart-open-cinema",
            ],
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 2,
            },
        )
    ]
    operation = SystemControlOperation.objects.get()
    assert operation.target_id == "open-cinema"
    assert list(
        OrchestrationEvent.objects.filter(correlation_id=operation.correlation_id).values_list(
            "event_type", flat=True
        )
    ) == ["system-control.requested", "system-control.accepted"]

    rejected = staff_client.post(
        "/api/system/v1/components/ssh-service/actions/restart",
        {"actionToken": token},
        format="json",
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "invalid-request"


def test_stale_or_cross_action_token_is_rejected_before_invocation(
    staff_client, monkeypatch
) -> None:
    invoked = []
    monkeypatch.setattr(control.subprocess, "run", lambda *args, **kwargs: invoked.append(args))
    stale = signing.dumps(
        {"action": "reboot-appliance", "bootId": "old-boot"},
        salt="open-cinema-system-control-v1",
    )

    response = staff_client.post(
        "/api/system/v1/actions/reboot", {"actionToken": stale}, format="json"
    )

    assert response.status_code == 400
    assert "stale" in response.json()["detail"]
    restart_token = _action_token(staff_client, "reboot")
    cross_action = staff_client.post(
        "/api/system/v1/components/open-cinema/actions/restart",
        {"actionToken": restart_token},
        format="json",
    )
    assert cross_action.status_code == 400
    assert invoked == []


def test_duplicate_action_reuses_in_progress_operation(staff_client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or _accepted(command, **kwargs),
    )
    token = _action_token(staff_client, "reboot")

    first = staff_client.post(
        "/api/system/v1/actions/reboot", {"actionToken": token}, format="json"
    )
    second = staff_client.post(
        "/api/system/v1/actions/reboot", {"actionToken": token}, format="json"
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(calls) == 1
    assert SystemControlOperation.objects.count() == 1


def test_new_action_supersedes_an_unpolled_operation_completed_by_restart(
    staff_client,
    monkeypatch,
) -> None:
    user = get_user_model().objects.create_user(username="stale-restart-staff")
    previous = SystemControlOperation.objects.create(
        action=SystemControlAction.RESTART_OPEN_CINEMA,
        target_id="open-cinema",
        status=SystemControlStatus.RECONNECTING,
        requested_by=user,
        initial_boot_id="boot-a",
        initial_service_instance="service-before-restart",
    )
    component = staff_client.get("/api/system/v1/components").json()["items"][0]
    token = component["actions"][0]["actionToken"]
    calls = []
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or _accepted(command, **kwargs),
    )
    response = staff_client.post(
        "/api/system/v1/components/open-cinema/actions/restart",
        {"actionToken": token},
        format="json",
    )

    previous.refresh_from_db()
    assert previous.status == SystemControlStatus.SUCCEEDED
    assert response.status_code == 202
    assert response.json()["id"] != str(previous.pk)
    assert response.json()["status"] == "reconnecting"
    assert len(calls) == 1
    assert SystemControlOperation.objects.count() == 2


def test_helper_failure_and_confirmation_timeout_are_reported(staff_client, monkeypatch) -> None:
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "denied"),
    )
    token = _action_token(staff_client, "reboot")
    failed = staff_client.post(
        "/api/system/v1/actions/reboot", {"actionToken": token}, format="json"
    )
    assert failed.status_code == 202
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"]["code"] == "helper-invocation-failed"

    operation = SystemControlOperation.objects.create(
        action=SystemControlAction.RESTART_ORCHESTRATOR,
        target_id="open-cinema-orchestrator",
        status=SystemControlStatus.EXECUTING,
        requested_by=get_user_model().objects.create_user(username="timeout-staff"),
        initial_boot_id="boot-a",
        initial_service_instance="service-a",
    )
    SystemControlOperation.objects.filter(pk=operation.pk).update(
        requested_at=timezone.now() - timedelta(seconds=91)
    )
    timed_out = staff_client.get(f"/api/system/v1/operations/{operation.pk}")
    assert timed_out.status_code == 200
    assert timed_out.json()["status"] == "failed"
    assert timed_out.json()["error"]["code"] == "confirmation-timeout"


def test_orchestrator_operation_succeeds_only_after_fresh_ready_projection(
    staff_client,
) -> None:
    operation = SystemControlOperation.objects.create(
        action=SystemControlAction.RESTART_ORCHESTRATOR,
        target_id="open-cinema-orchestrator",
        status=SystemControlStatus.EXECUTING,
        requested_by=get_user_model().objects.create_user(username="ready-staff"),
        initial_boot_id="boot-a",
        initial_service_instance="service-a",
    )
    RuntimeProjection.objects.create(
        projection_type="orchestration-health",
        subject_key="orchestrator",
        world_generation=1,
        world_sequence=1,
        observed_at=timezone.now() + timedelta(milliseconds=1),
        payload={"ready": True},
    )

    response = staff_client.get(f"/api/system/v1/operations/{operation.pk}")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["completedAt"] is not None


def test_helper_and_ansible_policy_keep_the_allowlist_fixed() -> None:
    root = Path(__file__).resolve().parents[1]
    helper = (root / "deployment/roles/open-cinema/files/open-cinema-system-control").read_text()
    sudoers = (
        root / "deployment/roles/open-cinema/templates/open-cinema-system-control.sudoers.j2"
    ).read_text()
    tasks = (root / "deployment/roles/open-cinema/tasks/main.yml").read_text()
    gunicorn = (root / "deployment/roles/open-cinema/templates/gunicorn.service.j2").read_text()

    for action in (
        "restart-open-cinema",
        "restart-orchestrator",
        "reboot-appliance",
    ):
        assert action in helper
        assert f"--check {action}" in sudoers
        assert "helper_path }} " + action in sudoers
    assert "ssh.service" not in helper + sudoers
    assert "validate: /usr/sbin/visudo -cf %s" in tasks
    assert 'become_user: "{{ open_cinema.user }}"' in tasks
    assert (
        "NoNewPrivileges={{ (not (open_cinema.system_control.enabled | bool)) | lower }}"
        in gunicorn
    )
