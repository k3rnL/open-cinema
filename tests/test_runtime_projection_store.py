from dataclasses import replace

import pytest

from api.models import (
    EndpointAudioLevel,
    LogicalEndpoint,
    ManagedAudioAdapter,
    ManagedAudioAdapterRuntimeState,
    MasterAudioLevel,
    RuntimeProjection,
)
from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from core.orchestration.runtime_projection_store import (
    DatabaseRuntimeProjectionStore,
    _json_document,
)
from core.orchestration.runtime_world import InMemoryWorldStore
from tests.test_endpoint_inventory_mapping import _snapshot
from tests.factories.orchestration import UserFactory
from wyreplumber.runtime import FrozenDict, NodeState, NodeValue
from wyreplumber.runtime import AudioPropertiesValue, ParameterValue

pytestmark = pytest.mark.django_db


def _world(*, generation=3, source_id=20, sink_id=10):
    return InMemoryWorldStore().install_runtime_snapshot(
        _snapshot(generation=generation, source_id=source_id, sink_id=sink_id)
    )


def test_publish_exposes_current_endpoint_candidates_and_runtime_health() -> None:
    store = DatabaseRuntimeProjectionStore()

    result = store.publish(_world(), health={"ready": True, "state": "ready"})

    assert result.created == 3
    assert result.retired == 0
    assert (
        RuntimeProjection.objects.filter(
            projection_type="endpoint-candidate", is_current=True
        ).count()
        == 2
    )
    health = RuntimeProjection.objects.get(projection_type="orchestration-health", is_current=True)
    assert health.payload["ready"] is True
    assert health.payload["counts"]["endpoints"] == 2


def test_publish_exposes_effective_observed_and_applying_audio_level_state() -> None:
    owner = UserFactory()
    endpoint = LogicalEndpoint.objects.create(
        owner=owner,
        name="Main speakers",
        direction="output",
        selector={
            "version": 1,
            "match": "all",
            "predicates": [
                {
                    "path": "node.name",
                    "operator": "exact",
                    "value": "alsa_output.usb-room",
                }
            ],
        },
    )
    MasterAudioLevel.objects.create(level=0.8)
    EndpointAudioLevel.objects.create(endpoint=endpoint, level=0.5)
    runtime = replace(
        _snapshot(),
        parameters=(
            ParameterValue(
                "node",
                10,
                "Props",
                "rw",
                (AudioPropertiesValue(volume=0.6, mute=False),),
            ),
        ),
    )
    world = InMemoryWorldStore().install_runtime_snapshot(runtime)

    result = DatabaseRuntimeProjectionStore().publish(world)

    assert result.created == 5
    projected = RuntimeProjection.objects.get(
        projection_type="audio-level", subject_key=f"endpoint:{endpoint.pk}"
    ).payload
    assert projected["desired"] == {"level": 0.5, "muted": False}
    assert projected["effective"] == {"level": 0.4, "muted": False}
    assert projected["observed"] == {"level": 0.6, "muted": False, "known": True}
    assert projected["capabilities"]["volume"]["writable"] is True
    assert projected["active"] is True
    assert projected["applying"] is True
    master = RuntimeProjection.objects.get(
        projection_type="audio-level", subject_key="master"
    ).payload
    assert master["observed"]["outputs"][0]["endpointId"] == str(endpoint.pk)
    assert master["applying"] is True


def test_publish_retires_previous_world_and_is_idempotent() -> None:
    store = DatabaseRuntimeProjectionStore()
    first = _world(generation=3)
    store.publish(first, health={"ready": True})

    unchanged = store.publish(first, health={"ready": True})
    updated = store.publish(_world(generation=4, source_id=220, sink_id=110))

    assert unchanged.created == 0
    assert unchanged.unchanged == 3
    assert updated.created == 3
    assert updated.retired == 3
    assert RuntimeProjection.objects.filter(is_current=True).count() == 3
    assert RuntimeProjection.objects.filter(is_current=False).count() == 3
    assert set(
        RuntimeProjection.objects.filter(
            projection_type="endpoint-candidate", is_current=True
        ).values_list("world_generation", flat=True)
    ) == {4}


def test_health_heartbeat_fields_do_not_create_projection_history() -> None:
    store = DatabaseRuntimeProjectionStore()
    world = _world()
    store.publish(
        world,
        health={"ready": True, "sequence": 1, "lastSuccessAt": "2026-08-22T12:00:00Z"},
    )

    result = store.publish(
        world,
        health={"ready": True, "sequence": 2, "lastSuccessAt": "2026-08-22T12:00:01Z"},
    )

    assert result.created == 0
    assert result.unchanged == 3
    assert RuntimeProjection.objects.filter(projection_type="orchestration-health").count() == 1


def test_json_container_normalization_prevents_false_projection_changes() -> None:
    assert _json_document({"positions": ("FL", "FR")}) == {"positions": ["FL", "FR"]}


def test_publish_ignores_older_snapshot_within_controller_lifetime() -> None:
    store = DatabaseRuntimeProjectionStore()
    current = _world(generation=4)
    store.publish(current)

    result = store.publish(_world(generation=3))

    assert result.ignored is True
    assert RuntimeProjection.objects.filter(is_current=True, world_generation=4).count() == 3


def test_empty_endpoint_world_keeps_runtime_available_and_retires_candidates() -> None:
    store = DatabaseRuntimeProjectionStore()
    store.publish(_world())
    empty_runtime = replace(
        _snapshot(generation=4),
        nodes=(),
        ports=(),
        links=(),
    )
    empty_world = InMemoryWorldStore().install_runtime_snapshot(empty_runtime)

    result = store.publish(empty_world)

    assert result.created == 1
    assert not RuntimeProjection.objects.filter(
        projection_type="endpoint-candidate", is_current=True
    ).exists()
    assert RuntimeProjection.objects.filter(
        projection_type="orchestration-health", is_current=True
    ).exists()


def test_managed_adapter_projection_includes_local_lifecycle() -> None:
    adapter = ManagedAudioAdapter.objects.create(
        owner=UserFactory(),
        name="Managed ROC output",
        kind="roc-sender",
        configuration={},
        enabled=True,
    )
    ManagedAudioAdapterRuntimeState.objects.create(
        adapter=adapter,
        lifecycle="ready",
        health="healthy",
        runtime_generation=3,
    )
    snapshot = _snapshot()
    node = NodeValue(
        id=77,
        name=f"open-cinema-adapter-{adapter.pk}",
        description=adapter.name,
        media_class="Audio/Sink",
        state=NodeState.RUNNING,
        properties=FrozenDict(
            {
                "node.name": f"open-cinema-adapter-{adapter.pk}",
                "open-cinema.owner": "open-cinema.adapter-supervisor.v1",
                "open-cinema.adapter.id": str(adapter.pk),
                "open-cinema.adapter.kind": "roc-sender",
                "open-cinema.adapter.direction": "output",
            }
        ),
    )
    world = InMemoryWorldStore().install_runtime_snapshot(
        replace(snapshot, nodes=(*snapshot.nodes, node))
    )

    DatabaseRuntimeProjectionStore().publish(world)

    projection = RuntimeProjection.objects.get(
        projection_type="endpoint-candidate",
        subject_key=f"runtime:{snapshot.generation}:node:77",
        is_current=True,
    )
    assert projection.payload["origin"] == "managed-adapter"
    assert projection.payload["managedAdapter"]["localReady"] is True
    assert projection.payload["managedAdapter"]["runtimeGeneration"] == 3


def test_native_processor_nodes_have_stable_resource_and_health_projections() -> None:
    snapshot = _snapshot()
    capture, playback = CamillaDSPDeploymentPolicy().runtime_identities(0)
    nodes = tuple(
        NodeValue(
            id=node_id,
            name=identity.node_name,
            media_class="Audio/Sink",
            state=NodeState.IDLE,
            properties=FrozenDict(
                {
                    "node.name": identity.node_name,
                    "node.group": identity.node_group_name,
                }
            ),
        )
        for node_id, identity in ((70, capture), (71, playback))
    )
    world = InMemoryWorldStore().install_runtime_snapshot(
        replace(snapshot, nodes=(*snapshot.nodes, *nodes))
    )

    result = DatabaseRuntimeProjectionStore().publish(world)

    assert result.created == 6
    resources = RuntimeProjection.objects.filter(
        projection_type="managed-resource", is_current=True
    ).order_by("subject_key")
    assert [item.subject_key for item in resources] == [
        "processor:camilladsp:camilladsp-0:capture",
        "processor:camilladsp:camilladsp-0:playback",
    ]
    assert resources[0].payload["runtimeKeyEphemeral"] is True
    health = RuntimeProjection.objects.get(projection_type="processor-health", is_current=True)
    assert health.subject_key == "processor:camilladsp:camilladsp-0"
    assert health.payload["ready"] is True


def test_unlinked_suspended_processor_nodes_remain_available() -> None:
    snapshot = _snapshot()
    capture, playback = CamillaDSPDeploymentPolicy().runtime_identities(0)
    nodes = tuple(
        NodeValue(
            id=node_id,
            name=identity.node_name,
            media_class="Audio/Sink",
            state=NodeState.SUSPENDED,
            properties=FrozenDict(
                {
                    "node.name": identity.node_name,
                    "node.group": identity.node_group_name,
                }
            ),
        )
        for node_id, identity in ((70, capture), (71, playback))
    )
    world = InMemoryWorldStore().install_runtime_snapshot(
        replace(snapshot, nodes=(*snapshot.nodes, *nodes))
    )

    DatabaseRuntimeProjectionStore().publish(world)

    resources = RuntimeProjection.objects.filter(
        projection_type="managed-resource", is_current=True
    )
    assert all(item.payload["ready"] is True for item in resources)
    health = RuntimeProjection.objects.get(projection_type="processor-health", is_current=True)
    assert health.payload["ready"] is True
    assert health.payload["health"] == "healthy"
