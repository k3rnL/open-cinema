from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from api.apps import PLUGIN_REGISTRY
from api.models import (
    PluginDesiredState,
    PluginInstallation,
    PluginObservedState,
    PluginOperation,
    PluginOperationKind,
    PluginOperationStatus,
)
from core.plugin_system.operations import (
    execute_plugin_operation,
    finalize_startup_operations,
    operation_document,
    request_operation_cancellation,
    request_plugin_operation,
)
from core.plugin_system.overlay import (
    PluginGenerationManifest,
    PluginOverlayManager,
)
from core.plugin_system.storage import (
    PluginInstallationRepository,
    StalePluginStateError,
)

pytestmark = pytest.mark.django_db


def _staff(username="plugin-admin"):
    return get_user_model().objects.create_user(username=username, is_staff=True)


def _installation(*, desired_state=PluginDesiredState.DISABLED, enable="hot"):
    item = PluginInstallationRepository.save_snapshot(
        plugin_id="counter",
        distribution_id="open-cinema",
        installed_version="0.3.2",
        manifest={"id": "counter"},
        provenance={"sourceType": "bundled"},
        lifecycle_impact={
            "install": "application-restart",
            "enable": enable,
            "disable": "hot",
            "update": "application-restart",
            "uninstall": "application-restart",
        },
        desired_state=desired_state,
    )
    item.observed_state = PluginObservedState.STOPPED
    item.save(update_fields=("observed_state", "updated_at"))
    return item


def _empty_generation(manager, generation_id, previous=None):
    manager.create_staging(generation_id)
    manager.write_manifest(
        generation_id,
        PluginGenerationManifest(
            generation_id,
            "2026-08-30T00:00:00Z",
            {"python": "3.12"},
            (),
            (),
            (),
            previous,
        ),
    )
    manager.activate(generation_id)


def test_install_api_is_staff_only_requires_trust_and_is_idempotent(client, monkeypatch) -> None:
    delayed = []
    monkeypatch.setattr(
        "api.tasks.plugin_operations.run_plugin_operation.delay",
        lambda operation_id: delayed.append(operation_id),
    )
    url = "/api/plugin-platform/v2/install"
    payload = {
        "pluginId": "test-plugin",
        "sourceType": "git",
        "repository": "https://example.test/test-plugin.git",
        "revision": "main",
        "trustedCodeAcknowledged": True,
    }
    user = get_user_model().objects.create_user(username="ordinary-plugin-user")
    client.force_login(user)
    assert client.post(url, payload, content_type="application/json").status_code == 403

    client.force_login(_staff())
    missing_trust = {**payload, "trustedCodeAcknowledged": False}
    assert (
        client.post(
            url,
            missing_trust,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="install-without-trust",
        ).status_code
        == 400
    )
    first = client.post(
        url,
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="install-test-plugin",
    )
    duplicate = client.post(
        url,
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="install-test-plugin",
    )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == first.json()["id"]
    assert delayed == [first.json()["id"]]


def test_lifecycle_api_rejects_stale_version_and_serializes_mutations(client, monkeypatch) -> None:
    installation = _installation()
    client.force_login(_staff())
    monkeypatch.setattr(
        "api.tasks.plugin_operations.run_plugin_operation.delay",
        lambda operation_id: None,
    )
    url = "/api/plugin-platform/v2/plugins/counter/actions/enable"
    stale = client.post(
        url,
        {"expectedVersion": installation.update_version + 1},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="stale-enable",
    )
    accepted = client.post(
        url,
        {"expectedVersion": installation.update_version},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="enable-counter",
    )
    overlapping = client.post(
        url,
        {"expectedVersion": installation.update_version},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="enable-counter-again",
    )

    assert stale.status_code == 409
    assert accepted.status_code == 202
    assert overlapping.status_code == 409


def test_operation_cancellation_requires_current_token() -> None:
    operation, _ = request_plugin_operation(
        plugin_id="test-plugin",
        kind=PluginOperationKind.INSTALL,
        idempotency_key="cancel-install",
        requested_by=_staff(),
        expected_version=None,
        stage_data={},
    )

    with pytest.raises(StalePluginStateError):
        request_operation_cancellation(
            operation.pk,
            concurrency_token=str(uuid.uuid4()),
        )
    updated = request_operation_cancellation(
        operation.pk,
        concurrency_token=str(operation.concurrency_token),
    )
    assert updated.cancellation_requested


def test_hot_enable_and_disable_are_restart_free_and_resumable(monkeypatch) -> None:
    installation = _installation()
    record = PLUGIN_REGISTRY.get("counter")
    monkeypatch.setattr(
        "core.plugin_system.operations._runtime_record",
        lambda plugin_id: record,
    )
    enable, _ = request_plugin_operation(
        plugin_id="counter",
        kind=PluginOperationKind.ENABLE,
        idempotency_key="hot-enable",
        requested_by=_staff(),
        expected_version=installation.update_version,
    )
    enable.status = PluginOperationStatus.RUNNING
    enable.stage = "worker-interrupted"
    enable.save(update_fields=("status", "stage", "updated_at"))
    execute_plugin_operation(str(enable.pk))
    enable.refresh_from_db()
    installation.refresh_from_db()

    assert enable.status == PluginOperationStatus.SUCCEEDED
    assert installation.desired_state == PluginDesiredState.ENABLED
    assert installation.observed_state == PluginObservedState.STARTED

    disable, _ = request_plugin_operation(
        plugin_id="counter",
        kind=PluginOperationKind.DISABLE,
        idempotency_key="hot-disable",
        requested_by=enable.requested_by,
        expected_version=installation.update_version,
    )
    execute_plugin_operation(str(disable.pk))
    disable.refresh_from_db()
    installation.refresh_from_db()
    assert disable.status == PluginOperationStatus.SUCCEEDED
    assert installation.desired_state == PluginDesiredState.DISABLED


def test_host_reboot_impact_stops_at_explicit_restart_pending(monkeypatch) -> None:
    installation = _installation(enable="host-reboot")
    record = PLUGIN_REGISTRY.get("counter")
    monkeypatch.setattr(
        "core.plugin_system.operations._runtime_record",
        lambda plugin_id: record,
    )
    operation, _ = request_plugin_operation(
        plugin_id="counter",
        kind=PluginOperationKind.ENABLE,
        idempotency_key="host-enable",
        requested_by=_staff(),
        expected_version=installation.update_version,
    )

    execute_plugin_operation(str(operation.pk))
    operation.refresh_from_db()

    assert operation.status == PluginOperationStatus.RESTART_PENDING
    assert operation.effective_lifecycle_impact == "host-reboot"
    assert operation_document(operation)["restartAction"]["id"] == "reboot"


def test_application_restart_impact_does_not_run_hot_hook(monkeypatch) -> None:
    installation = _installation(enable="application-restart")
    record = PLUGIN_REGISTRY.get("counter")
    called = []
    monkeypatch.setattr(
        "core.plugin_system.operations._runtime_record",
        lambda plugin_id: record,
    )
    monkeypatch.setattr(record.plugin, "start", lambda context: called.append(context))
    operation, _ = request_plugin_operation(
        plugin_id="counter",
        kind=PluginOperationKind.ENABLE,
        idempotency_key="restart-enable",
        requested_by=_staff(),
        expected_version=installation.update_version,
    )

    execute_plugin_operation(str(operation.pk))
    operation.refresh_from_db()
    assert operation.status == PluginOperationStatus.RESTART_PENDING
    assert operation.effective_lifecycle_impact == "application-restart"
    assert called == []
    assert operation_document(operation)["restartAction"]["id"] == "restart"


@override_settings(OPEN_CINEMA_PLUGIN_GENERATION_RETENTION=2)
def test_startup_finalizes_healthy_generation(tmp_path, settings) -> None:
    settings.OPEN_CINEMA_PLUGIN_ROOT = tmp_path / "plugins"
    manager = PluginOverlayManager(settings.OPEN_CINEMA_PLUGIN_ROOT)
    _empty_generation(manager, "gen-healthy")
    installation = _installation()
    operation = PluginOperation.objects.create(
        plugin_id="counter",
        kind=PluginOperationKind.INSTALL,
        status=PluginOperationStatus.RESTART_PENDING,
        stage="restart-pending",
        idempotency_key="healthy-startup",
        requested_by=_staff(),
        output_generation="gen-healthy",
    )

    finalize_startup_operations(PLUGIN_REGISTRY)
    operation.refresh_from_db()
    installation.refresh_from_db()
    assert operation.status == PluginOperationStatus.SUCCEEDED
    assert installation.observed_state == PluginObservedState.STOPPED


@override_settings(OPEN_CINEMA_PLUGIN_GENERATION_RETENTION=2)
def test_failed_health_gate_restores_last_known_good_pointer(tmp_path, settings) -> None:
    settings.OPEN_CINEMA_PLUGIN_ROOT = tmp_path / "plugins"
    manager = PluginOverlayManager(settings.OPEN_CINEMA_PLUGIN_ROOT)
    _empty_generation(manager, "gen-previous")
    _empty_generation(manager, "gen-candidate", "gen-previous")
    operation = PluginOperation.objects.create(
        plugin_id="missing-plugin",
        kind=PluginOperationKind.INSTALL,
        status=PluginOperationStatus.RESTART_PENDING,
        stage="restart-pending",
        idempotency_key="failed-startup",
        requested_by=_staff(),
        input_generation="gen-previous",
        output_generation="gen-candidate",
    )

    finalize_startup_operations(PLUGIN_REGISTRY)
    operation.refresh_from_db()
    assert operation.status == PluginOperationStatus.FAILED
    assert manager.pointer("current") == "gen-previous"
    assert "last-known-good" in operation.diagnostics[-1]["message"]


@override_settings(OPEN_CINEMA_PLUGIN_GENERATION_RETENTION=2)
def test_rollback_failure_is_retained_as_a_bounded_diagnostic(
    tmp_path, settings, monkeypatch
) -> None:
    settings.OPEN_CINEMA_PLUGIN_ROOT = tmp_path / "plugins"
    manager = PluginOverlayManager(settings.OPEN_CINEMA_PLUGIN_ROOT)
    _empty_generation(manager, "gen-only")
    operation = PluginOperation.objects.create(
        plugin_id="missing-plugin",
        kind=PluginOperationKind.INSTALL,
        status=PluginOperationStatus.RESTART_PENDING,
        stage="restart-pending",
        idempotency_key="rollback-failure",
        requested_by=_staff(),
        input_generation="gen-missing",
        output_generation="gen-only",
    )
    monkeypatch.setattr(
        "core.plugin_system.operations.PluginControlHelper.execute",
        lambda self, action, generation_id=None: (_ for _ in ()).throw(
            RuntimeError("rollback unavailable")
        ),
    )

    finalize_startup_operations(PLUGIN_REGISTRY)
    operation.refresh_from_db()
    assert operation.status == PluginOperationStatus.FAILED
    assert "rollback failed" in operation.diagnostics[-1]["message"]


def test_retry_reuses_failed_operation_input(monkeypatch) -> None:
    previous = PluginOperation.objects.create(
        plugin_id="retry-plugin",
        kind=PluginOperationKind.INSTALL,
        status=PluginOperationStatus.FAILED,
        stage="building",
        idempotency_key="original-failure",
        requested_by=_staff(),
        stage_data={"repository": "https://example.test/retry.git"},
    )
    retry, _ = request_plugin_operation(
        plugin_id="retry-plugin",
        kind=PluginOperationKind.RETRY,
        idempotency_key="retry-failure",
        requested_by=previous.requested_by,
        expected_version=None,
        stage_data={"retryOperationId": str(previous.pk)},
    )
    seen = []
    monkeypatch.setattr(
        "core.plugin_system.operations._install_or_update",
        lambda operation: (
            seen.append(operation.stage_data),
            setattr(operation, "status", "succeeded"),
        ),
    )

    execute_plugin_operation(str(retry.pk))
    assert seen == [previous.stage_data]


def test_failed_plugin_operation_does_not_break_unrelated_api(client) -> None:
    operation = PluginOperation.objects.create(
        plugin_id="failed-plugin",
        kind=PluginOperationKind.INSTALL,
        idempotency_key="missing-install-source",
        requested_by=_staff(),
        stage_data={},
    )
    execute_plugin_operation(str(operation.pk))
    operation.refresh_from_db()
    client.force_login(operation.requested_by)

    assert operation.status == PluginOperationStatus.FAILED
    assert client.get("/api/system/v1/overview").status_code == 200
