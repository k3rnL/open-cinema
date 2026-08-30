from dataclasses import replace
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from wyreplumber.runtime import FrozenDict

from api.models import LogicalEndpoint, PluginInstance
from core.plugin_system.managed_source_identity import managed_source_endpoint_id
from core.plugin_system.managed_sources import ManagedPluginSourceReconciler
from core.orchestration.endpoint_inventory import EndpointInventorySnapshot
from core.orchestration.resolution_context import _managed_source_activity
from core.orchestration.resolver_inputs import ResolverLogicalEndpointInput
from core.plugin_system.v2_contracts import (
    ManagedAudioSourceCapability,
    ManagedResourceObservation,
    PluginActionDescriptor,
    PluginDesiredState,
    PluginRuntimeResult,
    RuntimeStatus,
)
from tests.test_endpoint_binding import _candidate


class FakeSourceProvider:
    def __init__(self) -> None:
        self.running = False
        self.generation = None
        self.activations = 0
        self.reconfigurations = 0
        self.deactivations = 0

    def _result(self):
        return PluginRuntimeResult(
            RuntimeStatus.READY if self.running else RuntimeStatus.UNAVAILABLE,
            facts={
                "lifecycle": "running" if self.running else "stopped",
                "health": "healthy",
                "generation": self.generation,
                "playbackState": "idle",
            },
        )

    def prepare(self, context):
        return PluginRuntimeResult(RuntimeStatus.READY)

    def observe(self, context):
        return ManagedResourceObservation(
            self._result(),
            "2026-08-29T00:00:00+00:00",
            1000,
            (
                PluginActionDescriptor(
                    "restart",
                    "Restart",
                    self.running,
                    reason=None if self.running else "The source is stopped.",
                ),
            ),
        )

    def activate(self, context):
        self.running = True
        self.generation = "generation-1"
        self.activations += 1
        return self._result()

    def reconfigure(self, context):
        self.reconfigurations += 1
        self.generation = f"generation-{self.reconfigurations + 1}"
        return self._result()

    def deactivate(self, context):
        self.running = False
        self.deactivations += 1
        return self._result()

    def cleanup(self, context):
        self.running = False
        return self._result()


def _world(generation="generation-1"):
    candidate = SimpleNamespace(
        node_properties=FrozenDict(
            {
                "open-cinema.plugin.id": "test.spotify",
                "open-cinema.instance.id": "living-room",
                "open-cinema.generation": generation,
            }
        ),
        direction=SimpleNamespace(value="input"),
        runtime_key="runtime:7:node:42",
        has_active_signal=False,
        volume_writable=True,
        mute_writable=True,
    )
    return SimpleNamespace(
        endpoints=SimpleNamespace(candidates=(candidate,)),
        runtime=SimpleNamespace(generation=7, sequence=11),
    )


@pytest.mark.django_db
def test_orchestrator_owns_managed_source_lifecycle_and_endpoint():
    user = get_user_model().objects.create_user(username="managed-source-owner")
    provider = FakeSourceProvider()
    capability = ManagedAudioSourceCapability(
        "test.spotify.sources",
        source_type="test.spotify.source",
        provider=provider,
        instance_schema={"type": "object"},
        signal_contract={"content": "pcm"},
        correlation_keys=("open-cinema.instance.id",),
    )
    capability_record = SimpleNamespace(contribution=capability)
    record = SimpleNamespace(
        manifest=SimpleNamespace(plugin_id="test.spotify"),
        desired_state=PluginDesiredState.ENABLED,
        capabilities=[capability_record],
    )
    registry = SimpleNamespace(records=(record,))
    instance = PluginInstance.objects.create(
        plugin_id="test.spotify",
        capability_id="test.spotify.sources",
        instance_id="living-room",
        display_name="Living room Spotify",
        owner=user,
        configuration_version=1,
        configuration={"name": "Living room"},
        desired_state="enabled",
    )

    result = ManagedPluginSourceReconciler(registry).reconcile(_world(), force=True)

    assert result.started == ("living-room",)
    assert result.changed == ("living-room",)
    assert provider.activations == 1
    instance.refresh_from_db()
    assert instance.observed_state == "started"
    assert instance.runtime_facts["routeAvailable"] is True
    assert instance.runtime_facts["pipewireCorrelation"] == "ready"
    endpoint_id = managed_source_endpoint_id("test.spotify", "test.spotify.sources", "living-room")
    endpoint = LogicalEndpoint.objects.get(pk=endpoint_id)
    assert endpoint.owner == user
    assert endpoint.policy_metadata["managedSource"] is True
    assert endpoint.selector["predicates"][1]["value"] == "test.spotify"


@pytest.mark.django_db
def test_reconcile_restarts_changed_instance_and_stops_disabled_instance():
    user = get_user_model().objects.create_user(username="managed-source-reconfigure")
    provider = FakeSourceProvider()
    provider.running = True
    provider.generation = "generation-1"
    capability = ManagedAudioSourceCapability(
        "test.spotify.sources",
        source_type="test.spotify.source",
        provider=provider,
        instance_schema={"type": "object"},
        signal_contract={"content": "pcm"},
        correlation_keys=("open-cinema.instance.id",),
    )
    registry = SimpleNamespace(
        records=(
            SimpleNamespace(
                manifest=SimpleNamespace(plugin_id="test.spotify"),
                desired_state=PluginDesiredState.ENABLED,
                capabilities=[SimpleNamespace(contribution=capability)],
            ),
        )
    )
    instance = PluginInstance.objects.create(
        plugin_id="test.spotify",
        capability_id="test.spotify.sources",
        instance_id="living-room",
        display_name="Living room Spotify",
        owner=user,
        configuration_version=1,
        configuration={"name": "Living room"},
        desired_state="enabled",
        update_version=2,
    )
    reconciler = ManagedPluginSourceReconciler(registry)
    reconciler._applied_versions[("test.spotify", "test.spotify.sources", "living-room")] = 1

    restarted = reconciler.reconcile(_world("generation-2"), force=True)
    assert restarted.restarted == ("living-room",)
    assert provider.reconfigurations == 1

    instance.refresh_from_db()
    instance.desired_state = "disabled"
    instance.update_version += 1
    instance.save(update_fields=("desired_state", "update_version", "updated_at"))
    stopped = reconciler.reconcile(_world("generation-2"), force=True)
    assert stopped.stopped == ("living-room",)
    assert provider.deactivations == 1
    instance.refresh_from_db()
    assert instance.observed_state == "stopped"
    assert instance.runtime_facts["routeAvailable"] is False


@pytest.mark.django_db
def test_managed_source_uses_a_stable_suffix_when_a_user_device_has_the_same_name():
    user = get_user_model().objects.create_user(username="managed-source-name-collision")
    LogicalEndpoint.objects.create(
        name="Living room Spotify",
        owner=user,
        direction="input",
        selector={"version": 1, "match": "all", "predicates": []},
    )
    provider = FakeSourceProvider()
    capability = ManagedAudioSourceCapability(
        "test.spotify.sources",
        source_type="test.spotify.source",
        provider=provider,
        instance_schema={"type": "object"},
        signal_contract={"content": "pcm"},
        correlation_keys=("open-cinema.instance.id",),
    )
    registry = SimpleNamespace(
        records=(
            SimpleNamespace(
                manifest=SimpleNamespace(plugin_id="test.spotify"),
                desired_state=PluginDesiredState.ENABLED,
                capabilities=[SimpleNamespace(contribution=capability)],
            ),
        )
    )
    PluginInstance.objects.create(
        plugin_id="test.spotify",
        capability_id="test.spotify.sources",
        instance_id="living-room",
        display_name="Living room Spotify",
        owner=user,
        configuration_version=1,
        configuration={"name": "Living room"},
        desired_state="enabled",
    )

    ManagedPluginSourceReconciler(registry).reconcile(_world(), force=True)

    managed = LogicalEndpoint.objects.get(
        pk=managed_source_endpoint_id("test.spotify", "test.spotify.sources", "living-room")
    )
    assert managed.name.startswith("Living room Spotify · spotify · ")


def test_provider_playback_activity_overlays_the_exact_correlated_stream_and_version():
    candidate = replace(_candidate("bluez_input.phone"), has_active_signal=False)
    inventory = EndpointInventorySnapshot(3, 9, "2026-08-29T00:00:00Z", (candidate,))
    endpoint = ResolverLogicalEndpointInput(
        endpoint_id="spotify-endpoint",
        name="Living room Spotify",
        direction="input",
        selector={"version": 1, "match": "all", "predicates": []},
        policy_metadata={
            "managedSource": True,
            "pluginId": "test.spotify",
            "capabilityId": "test.spotify.sources",
            "instanceId": "living-room",
        },
    )
    facts = {
        "generation": "generation-1",
        "pipewireCorrelation": "ready",
        "routeAvailable": True,
        "activeSignal": True,
        "playbackState": "playing",
        "correlatedRuntimeKey": candidate.runtime_key,
        "events": {"lastSequence": 7},
    }
    instance = SimpleNamespace(
        plugin_id="test.spotify",
        capability_id="test.spotify.sources",
        instance_id="living-room",
        update_version=2,
        runtime_facts=facts,
    )

    playing, playing_version = _managed_source_activity((endpoint,), inventory, (instance,))
    idle, idle_version = _managed_source_activity(
        (endpoint,),
        inventory,
        (
            SimpleNamespace(
                **{
                    **instance.__dict__,
                    "runtime_facts": {**facts, "activeSignal": False, "playbackState": "paused"},
                }
            ),
        ),
    )

    assert playing.candidates[0].has_active_signal is True
    assert idle.candidates[0].has_active_signal is False
    assert playing_version != idle_version
