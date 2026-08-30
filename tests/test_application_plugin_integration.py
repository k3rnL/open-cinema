from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import clear_url_caches

from api import urls as api_urls
from core.plugin_system import (
    AdminUICapability,
    ApiCapability,
    AutomationCapability,
    OpenCinemaPlugin,
    PluginDistributionRegistry,
    parse_plugin_manifest,
)
from core.plugin_system.integration import PluginAutomationRegistry, plugin_api_urlpatterns
from plugin.counter.api.plugin import CounterPlugin

pytestmark = pytest.mark.django_db


@pytest.fixture
def counter_runtime():
    manifest_path = Path(__file__).parents[1] / "plugin" / "counter" / "open-cinema-plugin.toml"
    manifest = parse_plugin_manifest(manifest_path.read_text())
    plugin = CounterPlugin()
    registry = PluginDistributionRegistry()
    record = registry.register(manifest, plugin)
    registry.start_enabled()
    patterns = plugin_api_urlpatterns(registry)
    original_length = len(api_urls.urlpatterns)
    api_urls.urlpatterns.extend(patterns)
    clear_url_caches()
    try:
        yield plugin, registry, record
    finally:
        del api_urls.urlpatterns[original_length:]
        clear_url_caches()


def test_bundled_counter_is_one_composite_v2_distribution(counter_runtime, settings) -> None:
    plugin, registry, record = counter_runtime

    assert isinstance(plugin, OpenCinemaPlugin)
    assert plugin.identity.plugin_id == "counter"
    assert plugin.identity.distribution_id == "open-cinema"
    assert [type(item.contribution) for item in record.capabilities] == [
        ApiCapability,
        AutomationCapability,
        AdminUICapability,
    ]
    assert record.health.value == "healthy"
    assert "plugin.counter" not in settings.INSTALLED_APPS
    assert (
        registry.catalogue_document()["plugins"][0]["capabilities"][2]["schemaMetadata"][
            "descriptor"
        ]["pages"][0]["template"]
        == "overview"
    )


def test_bundled_counter_routes_storage_and_automation_share_one_identity(
    client, counter_runtime
) -> None:
    _, registry, record = counter_runtime
    user = get_user_model().objects.create_user(username="counter-user")
    client.force_login(user)

    initial = client.get("/api/plugins/counter/")
    incremented = client.post(
        "/api/plugins/counter/increment",
        data=json.dumps({"comment": "version-2 composite plugin"}),
        content_type="application/json",
    )
    history = client.get("/api/plugins/counter/history")
    automations = PluginAutomationRegistry(registry)
    automations.refresh()

    assert initial.status_code == 200, [item.message for item in record.capabilities[0].diagnostics]
    assert initial.json()["value"] == 0
    assert incremented.status_code == 200, [
        item.message for item in record.capabilities[0].diagnostics
    ]
    assert incremented.json()["newValue"] == 1
    assert history.status_code == 200
    assert history.json()["history"][0]["comment"] == "version-2 composite plugin"
    assert automations.ids() == ("counter.current-value",)
    assert automations.invoke("counter.current-value") == 1
