from __future__ import annotations

import json
import platform
from pathlib import Path
from time import sleep
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.urls import clear_url_caches, path
from django.utils import timezone

from api import urls as api_urls
from api.models import PluginInstallation
from core.plugin_system import (
    ActionConfirmation,
    ApiCapability,
    AutomationCapability,
    LifecycleImpact,
    ManagedAudioSourceCapability,
    ManagedResourceCapability,
    ManagedResourceContext,
    ManagedResourceObservation,
    OpenCinemaPlugin,
    PluginActionDescriptor,
    PluginDesiredState,
    PluginDistributionRegistry,
    PluginHealth,
    PluginLifecycleState,
    PluginProvenance,
    PluginRuntimeResult,
    RuntimePluginIdentity,
    RuntimeStatus,
    parse_plugin_manifest,
)
from core.plugin_system.integration import (
    PluginAutomationRegistry,
    plugin_api_urlpatterns,
)
from core.plugin_system.persistence_sync import synchronize_plugin_inventory
from core.plugin_system.storage import PluginInstallationRepository
from core.plugin_system.v2_registry import runtime_plugin_entry_points

pytestmark = pytest.mark.django_db


def _manifest(capabilities):
    return parse_plugin_manifest(
        {
            "schema-version": 2,
            "plugin": {
                "id": "test.runtime",
                "distribution": "open-cinema-test-runtime",
                "display-name": "Runtime test",
                "description": "Runtime integration fixture.",
                "vendor": "Tests",
                "version": "1.0.0",
                "license": "MIT",
                "source-url": "https://example.test/source",
                "documentation-url": "https://example.test/docs",
            },
            "compatibility": {
                "plugin-contract": {"minimum": 2, "maximum": 2},
                "open-cinema": ">=0.3,<1",
                "python": ">=3.12,<4",
                "operating-systems": [platform.system().lower()],
                "architectures": [platform.machine().lower()],
            },
            "capabilities": capabilities,
            "permissions": [],
            "lifecycle": {
                "install": "application-restart",
                "enable": "hot",
                "disable": "hot",
                "update": "application-restart",
                "uninstall": "application-restart",
            },
        }
    )


class RuntimeTestPlugin(OpenCinemaPlugin):
    @property
    def identity(self):
        return RuntimePluginIdentity(
            "test.runtime", "open-cinema-test-runtime", "1.0.0"
        )

    @staticmethod
    def ok(request):
        return JsonResponse({"status": "ok"})

    @staticmethod
    def write(request):
        return JsonResponse({"status": "written"})

    @staticmethod
    def explode(request):
        raise RuntimeError("isolated route failure")

    @staticmethod
    def slow(request):
        sleep(0.02)
        return JsonResponse({"status": "late"})

    def capabilities(self):
        return (
            ApiCapability(
                "test.runtime.api",
                routes=lambda: (
                    path("ok", self.ok),
                    path("write", self.write),
                    path("explode", self.explode),
                    path("slow", self.slow),
                ),
            ),
            AutomationCapability(
                "test.runtime.automation",
                hooks={
                    "test.runtime.echo": lambda value: value,
                    "test.runtime.failed": lambda: (_ for _ in ()).throw(
                        RuntimeError("automation failed")
                    ),
                },
            ),
        )


@pytest.fixture
def runtime_routes(settings):
    settings.OPEN_CINEMA_PLUGIN_ROUTE_TIMEOUT_SECONDS = 0.005
    manifest = _manifest(
        [
            {"id": "test.runtime.api", "kind": "api", "version": 1},
            {
                "id": "test.runtime.automation",
                "kind": "automation",
                "version": 1,
            },
        ]
    )
    registry = PluginDistributionRegistry()
    record = registry.register(manifest, RuntimeTestPlugin())
    original_length = len(api_urls.urlpatterns)
    api_urls.urlpatterns.extend(plugin_api_urlpatterns(registry))
    clear_url_caches()
    try:
        yield registry, record
    finally:
        del api_urls.urlpatterns[original_length:]
        clear_url_caches()


def test_plugin_routes_enforce_auth_state_health_timeout_and_failure_isolation(
    client, runtime_routes
) -> None:
    registry, record = runtime_routes
    anonymous = client.get("/api/plugins/test.runtime/ok")
    user = get_user_model().objects.create_user(username="plugin-runtime-user")
    client.force_login(user)
    healthy = client.get("/api/plugins/test.runtime/ok")
    failed = client.get("/api/plugins/test.runtime/explode")
    slow = client.get("/api/plugins/test.runtime/slow")
    record.capabilities[0].health = PluginHealth.HEALTHY
    record.desired_state = PluginDesiredState.DISABLED
    disabled = client.get("/api/plugins/test.runtime/ok")
    record.desired_state = PluginDesiredState.ENABLED
    record.capabilities[0].health = PluginHealth.FAILED
    unhealthy = client.get("/api/plugins/test.runtime/ok")

    assert anonymous.status_code == 401
    assert healthy.status_code == 200
    assert healthy.headers["Open-Cinema-Plugin"] == "test.runtime"
    assert failed.status_code == 500
    assert failed.json()["correlationId"]
    assert slow.status_code == 504
    assert disabled.status_code == 503
    assert disabled.json()["code"] == "plugin-disabled"
    assert unhealthy.status_code == 503
    assert registry.catalogue_document()["plugins"][0]["capabilities"][0]["diagnostics"]


def test_plugin_routes_reconcile_persisted_hot_lifecycle_state(
    client, runtime_routes
) -> None:
    registry, record = runtime_routes
    synchronize_plugin_inventory(registry)
    user = get_user_model().objects.create_user(username="plugin-hot-state-user")
    client.force_login(user)
    record.desired_state = PluginDesiredState.DISABLED
    record.state = PluginLifecycleState.STOPPED
    PluginInstallation.objects.filter(plugin_id="test.runtime").update(
        desired_state="enabled"
    )

    enabled = client.get("/api/plugins/test.runtime/ok")

    assert enabled.status_code == 200
    assert record.desired_state is PluginDesiredState.ENABLED
    assert record.state is PluginLifecycleState.STARTED

    PluginInstallation.objects.filter(plugin_id="test.runtime").update(
        desired_state="disabled"
    )
    disabled = client.get("/api/plugins/test.runtime/ok")

    assert disabled.status_code == 503
    assert record.desired_state is PluginDesiredState.DISABLED
    assert record.state is PluginLifecycleState.STOPPED


def test_startup_preserves_stronger_acquisition_provenance() -> None:
    manifest = _manifest(
        [
            {"id": "test.runtime.api", "kind": "api", "version": 1},
            {
                "id": "test.runtime.automation",
                "kind": "automation",
                "version": 1,
            },
        ]
    )
    exact_provenance = {
        "sourceType": "catalogue",
        "sourceUrl": "https://example.test/releases/plugin.whl",
        "artifactDigest": "sha256:" + "a" * 64,
        "resolvedRevision": "b" * 40,
        "version": "1.0.0",
    }
    PluginInstallationRepository.save_snapshot(
        plugin_id=manifest.plugin_id,
        distribution_id=manifest.distribution_id,
        installed_version=manifest.version,
        manifest=manifest.to_document(),
        provenance=exact_provenance,
        lifecycle_impact=manifest.lifecycle.to_document(),
    )
    registry = PluginDistributionRegistry()
    registry.register(
        manifest,
        RuntimeTestPlugin(),
        provenance=PluginProvenance(
            "installed-distribution",
            manifest.distribution_id,
            manifest.version,
            source_url=manifest.source_url,
        ),
    )

    assert synchronize_plugin_inventory(registry)

    installation = PluginInstallation.objects.get(plugin_id=manifest.plugin_id)
    assert installation.provenance_snapshot == exact_provenance
    assert registry.get(manifest.plugin_id).desired_state is PluginDesiredState.DISABLED


def test_unsafe_plugin_route_uses_core_csrf_protection(runtime_routes) -> None:
    client_class = pytest.importorskip("django.test").Client
    csrf_client = client_class(enforce_csrf_checks=True)
    user = get_user_model().objects.create_user(username="plugin-csrf-user")
    csrf_client.force_login(user)

    response = csrf_client.post(
        "/api/plugins/test.runtime/write",
        data=json.dumps({"value": True}),
        content_type="application/json",
    )

    assert response.status_code == 403


def test_automation_registration_obeys_desired_state_and_isolates_failure(
    runtime_routes,
) -> None:
    registry, record = runtime_routes
    automations = PluginAutomationRegistry(registry)
    automations.refresh()

    assert automations.ids() == ("test.runtime.echo", "test.runtime.failed")
    assert automations.invoke("test.runtime.echo", "value") == "value"
    with pytest.raises(RuntimeError, match="automation failed"):
        automations.invoke("test.runtime.failed")
    assert record.capabilities[1].health is PluginHealth.DEGRADED
    record.desired_state = PluginDesiredState.DISABLED
    with pytest.raises(PermissionError, match="disabled"):
        automations.invoke("test.runtime.echo", "value")


class ResourceProvider:
    def observe(self, context):
        return ManagedResourceObservation(
            PluginRuntimeResult(RuntimeStatus.READY, {"pid": 42}),
            timezone.now().isoformat(),
            5000,
            (
                PluginActionDescriptor(
                    "restart",
                    "Restart",
                    True,
                    LifecycleImpact.HOT,
                    ActionConfirmation.CONFIRM,
                    concurrency_token="version-1",
                ),
            ),
        )

    def actions(self, context):
        return self.observe(context).actions

    def execute(self, action_id, context):
        return PluginRuntimeResult(RuntimeStatus.READY, {"action": action_id})


class SourceProvider:
    def _result(self, hook):
        return PluginRuntimeResult(
            RuntimeStatus.READY,
            {
                "hook": hook,
                "pipewire.node.name": "open-cinema-test-source-main",
            },
        )

    def prepare(self, context):
        return self._result("prepare")

    def observe(self, context):
        return ManagedResourceObservation(
            self._result("observe"), timezone.now().isoformat(), 1000
        )

    def activate(self, context):
        return self._result("activate")

    def reconfigure(self, context):
        return self._result("reconfigure")

    def deactivate(self, context):
        return self._result("deactivate")

    def cleanup(self, context):
        return self._result("cleanup")


class ManagedPlugin(OpenCinemaPlugin):
    def __init__(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        self.resource = ManagedResourceCapability(
            "test.runtime.resources",
            resource_type="test.runtime.service",
            provider=ResourceProvider(),
            instance_schema=schema,
        )
        self.source = ManagedAudioSourceCapability(
            "test.runtime.sources",
            source_type="test.runtime.audio-source",
            provider=SourceProvider(),
            instance_schema=schema,
            signal_contract={
                "mediaKind": "audio",
                "content": "pcm",
                "rates": [44100],
                "layouts": [{"channels": 2, "positions": ["FL", "FR"]}],
            },
            correlation_keys=("pipewire.node.name",),
        )

    @property
    def identity(self):
        return RuntimePluginIdentity(
            "test.runtime", "open-cinema-test-runtime", "1.0.0"
        )

    def capabilities(self):
        return self.resource, self.source


def test_managed_resource_and_audio_source_contracts_are_typed_and_core_bounded() -> (
    None
):
    manifest = _manifest(
        [
            {
                "id": "test.runtime.resources",
                "kind": "managed-resource",
                "version": 1,
            },
            {
                "id": "test.runtime.sources",
                "kind": "managed-audio-source",
                "version": 1,
            },
        ]
    )
    plugin = ManagedPlugin()
    record = PluginDistributionRegistry().register(manifest, plugin)
    context = ManagedResourceContext(
        "test.runtime",
        "test.runtime.sources",
        "main",
        {"name": "Main"},
        1,
        concurrency_token="version-1",
    )

    resource_observation = plugin.resource.provider.observe(context)
    source_result = plugin.source.provider.activate(context)

    assert record.health is PluginHealth.HEALTHY
    assert resource_observation.actions[0].concurrency_token == "version-1"
    assert resource_observation.actions[0].lifecycle_impact is LifecycleImpact.HOT
    assert source_result.facts["pipewire.node.name"] == "open-cinema-test-source-main"
    assert plugin.source.signal_contract["content"] == "pcm"
    assert plugin.source.correlation_keys == ("pipewire.node.name",)


def test_plugin_ui_bootstrap_is_authenticated_cacheable_and_bounded(client) -> None:
    user = get_user_model().objects.create_user(username="plugin-page-user")
    anonymous = client.get("/api/plugin-platform/v2/ui")
    client.force_login(user)
    response = client.get("/api/plugin-platform/v2/ui")
    cached = client.get(
        "/api/plugin-platform/v2/ui",
        HTTP_IF_NONE_MATCH=response.headers["ETag"],
    )

    assert anonymous.status_code in {401, 403}
    assert response.status_code == 200
    assert response.json()["schemaVersion"] == 1
    assert response.headers["Cache-Control"].startswith("private")
    assert cached.status_code == 304


def test_runtime_discovery_excludes_unmanaged_environment_plugins(
    tmp_path, monkeypatch
) -> None:
    editable = tmp_path / "editable-plugin"
    editable.mkdir()

    class Distribution:
        def __init__(self, name, entry_name, source: Path | None = None):
            self.metadata = {"Name": name}
            self.entry_points = (
                SimpleNamespace(
                    group="open_cinema.plugins",
                    name=entry_name,
                    value=f"{entry_name}:Plugin",
                    dist=self,
                ),
            )
            self.source = source

        def read_text(self, filename):
            if filename != "direct_url.json" or self.source is None:
                return None
            return json.dumps(
                {
                    "url": self.source.as_uri(),
                    "dir_info": {"editable": True},
                }
            )

        def locate_file(self, filename):
            return tmp_path / "site-packages" / filename

    core = Distribution("open-cinema", "counter")
    unmanaged = Distribution("unmanaged-plugin", "unmanaged", editable)
    monkeypatch.setattr(
        "core.plugin_system.v2_registry.metadata.distributions",
        lambda **kwargs: () if kwargs.get("path") else (core, unmanaged),
    )
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ROOT", str(tmp_path / "plugins"))
    monkeypatch.delenv("OPEN_CINEMA_PLUGIN_ALLOW_EDITABLE", raising=False)
    monkeypatch.delenv("OPEN_CINEMA_PLUGIN_EDITABLE_DIRS", raising=False)

    assert [item.name for item in runtime_plugin_entry_points()] == ["counter"]

    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ALLOW_EDITABLE", "1")
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_EDITABLE_DIRS", str(editable))
    assert [item.name for item in runtime_plugin_entry_points()] == [
        "counter",
        "unmanaged",
    ]
