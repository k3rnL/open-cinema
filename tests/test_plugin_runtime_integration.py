from __future__ import annotations

import json
import platform
from time import sleep

import pytest
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.urls import clear_url_caches, path
from django.utils import timezone

from api import urls as api_urls
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
    PluginRuntimeResult,
    RuntimePluginIdentity,
    RuntimeStatus,
    parse_plugin_manifest,
)
from core.plugin_system.integration import PluginAutomationRegistry, plugin_api_urlpatterns

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
        return RuntimePluginIdentity("test.runtime", "open-cinema-test-runtime", "1.0.0")

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
        return ManagedResourceObservation(self._result("observe"), timezone.now().isoformat(), 1000)

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
        return RuntimePluginIdentity("test.runtime", "open-cinema-test-runtime", "1.0.0")

    def capabilities(self):
        return self.resource, self.source


def test_managed_resource_and_audio_source_contracts_are_typed_and_core_bounded() -> None:
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
