import json

import pytest

from core.plugin_system import ApplicationPlugin, ProcessingPlugin
from plugin.counter.api.plugin import CounterApplicationPlugin
from plugin.counter.models import CounterLog

pytestmark = pytest.mark.django_db


def test_bundled_counter_uses_application_manifest_without_audio_processing() -> None:
    plugin = CounterApplicationPlugin()

    assert isinstance(plugin, ApplicationPlugin)
    assert not isinstance(plugin, ProcessingPlugin)
    assert plugin.manifest.plugin_id == "counter"
    assert plugin.manifest.model_packages == ("plugin.counter.models",)
    assert plugin.manifest.automation_ids == ("counter.current-value",)
    assert not hasattr(plugin, "get_audio_backend")


def test_bundled_application_routes_models_and_automation_remain_independent(client) -> None:
    CounterLog.objects.create(action="RESET", value=4, comment="fixture")

    initial = client.get("/api/plugins/counter/")
    incremented = client.post(
        "/api/plugins/counter/increment",
        data=json.dumps({"comment": "application plugin contract"}),
        content_type="application/json",
    )
    plugin = CounterApplicationPlugin()

    assert initial.status_code == 200
    assert initial.json()["value"] == 4
    assert incremented.status_code == 200
    assert incremented.json()["new_value"] == 5
    assert CounterLog.objects.first().value == 5
    assert plugin.automation_hooks()["counter.current-value"]() == 5
