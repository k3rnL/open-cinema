from dataclasses import replace

import pytest
from wyreplumber.runtime import (
    AudioPropertiesValue,
    NodeState,
    NodeValue,
    ParameterValue,
    PortDirection,
    PortValue,
)

from api.models import EndpointAudioLevel, LogicalEndpoint, MasterAudioLevel
from core.orchestration.endpoint_inventory import map_runtime_endpoints
from core.orchestration.live_reconciliation import LiveGraphReconciler
from tests.factories.orchestration import UserFactory
from tests.test_endpoint_inventory_mapping import _snapshot

pytestmark = pytest.mark.django_db


def _selector(name: str) -> dict[str, object]:
    return {
        "version": 1,
        "match": "all",
        "predicates": [{"path": "node.name", "operator": "exact", "value": name}],
    }


def _endpoint(owner, name: str, direction: str, node_name: str) -> LogicalEndpoint:
    return LogicalEndpoint.objects.create(
        owner=owner,
        name=name,
        direction=direction,
        selector=_selector(node_name),
    )


def _runtime_with_headset(*, generation: int = 3):
    runtime = _snapshot(generation=generation)
    return replace(
        runtime,
        nodes=(
            *runtime.nodes,
            NodeValue(
                id=11,
                name="bluez_output.headset",
                description="Headset",
                media_class="Audio/Sink",
                state=NodeState.IDLE,
                input_port_ids=(104,),
            ),
        ),
        ports=(
            *runtime.ports,
            PortValue(104, 11, PortDirection.INPUT, name="playback_FL", channel="FL"),
        ),
        parameters=(
            ParameterValue(
                "node",
                10,
                "Props",
                "rw",
                (AudioPropertiesValue(volume=0.6, mute=False),),
            ),
            ParameterValue(
                "node",
                11,
                "Props",
                "rw",
                (AudioPropertiesValue(volume=0.6, mute=False),),
            ),
            ParameterValue(
                "node",
                20,
                "Props",
                "rw",
                (AudioPropertiesValue(volume=0.9, mute=False),),
            ),
        ),
    )


def _candidate_map(runtime):
    return {candidate.name: candidate for candidate in map_runtime_endpoints(runtime).candidates}


def _reconciler() -> LiveGraphReconciler:
    return LiveGraphReconciler(lambda: None, adapter=object())


def test_calculates_input_and_multiple_output_levels_with_endpoint_mute() -> None:
    owner = UserFactory()
    source = _endpoint(owner, "Phone", "input", "bluez_input.phone")
    speakers = _endpoint(owner, "Speakers", "output", "alsa_output.usb-room")
    headset = _endpoint(owner, "Headset", "output", "bluez_output.headset")
    MasterAudioLevel.objects.create(level=0.5)
    EndpointAudioLevel.objects.create(endpoint=source, level=0.7)
    EndpointAudioLevel.objects.create(endpoint=speakers, level=0.8)
    EndpointAudioLevel.objects.create(endpoint=headset, level=0.6, muted=True)
    candidates = _candidate_map(_runtime_with_headset())
    by_key = {item.runtime_key: item for item in candidates.values()}
    bindings = {
        str(source.pk): candidates["bluez_input.phone"].runtime_key,
        str(speakers.pk): candidates["alsa_output.usb-room"].runtime_key,
        str(headset.pk): candidates["bluez_output.headset"].runtime_key,
    }
    graph = {
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(source.pk)},
            },
            {
                "id": "speakers",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(speakers.pk)},
            },
            {
                "id": "headset",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(headset.pk)},
            },
        ]
    }
    edges = {
        "to-speakers": {
            "from": {"node": "source"},
            "to": {"node": "speakers"},
        },
        "to-headset": {
            "from": {"node": "source"},
            "to": {"node": "headset"},
        },
    }

    actions = _reconciler()._audio_level_actions(
        graph=graph,
        edges=edges,
        selected_edge_ids=("to-speakers", "to-headset"),
        selections={},
        bindings=bindings,
        candidates=by_key,
        plan_digest="multi-output",
    )

    values = {
        (
            item.action.identity.resource_id,
            item.action.command.operation,
        ): item.action.command.arguments
        for item in actions
    }
    assert values[(str(source.pk), "set-endpoint-volume")]["volume"] == 0.7
    assert values[(str(speakers.pk), "set-endpoint-volume")]["volume"] == 0.4
    assert values[(str(headset.pk), "set-endpoint-volume")]["volume"] == 0.3
    assert values[(str(headset.pk), "set-endpoint-mute")]["mute"] is True
    assert len(actions) == 4
    assert all(item.phase.value == "configure" for item in actions)

    master = MasterAudioLevel.objects.get(pk=1)
    master.muted = True
    master.update_version += 1
    master.save()
    master_muted = _reconciler()._audio_level_actions(
        graph=graph,
        edges=edges,
        selected_edge_ids=("to-speakers", "to-headset"),
        selections={},
        bindings=bindings,
        candidates=by_key,
        plan_digest="master-muted",
    )
    muted_outputs = {
        item.action.identity.resource_id
        for item in master_muted
        if item.action.command.operation == "set-endpoint-mute"
    }
    assert muted_outputs == {str(speakers.pk), str(headset.pk)}


def test_route_switch_reapplies_master_to_each_new_runtime_identity() -> None:
    owner = UserFactory()
    source = _endpoint(owner, "Phone", "input", "bluez_input.phone")
    speakers = _endpoint(owner, "Speakers", "output", "alsa_output.usb-room")
    headset = _endpoint(owner, "Headset", "output", "bluez_output.headset")
    MasterAudioLevel.objects.create(level=0.5)
    runtime = _runtime_with_headset()
    candidates = _candidate_map(runtime)
    by_key = {item.runtime_key: item for item in candidates.values()}
    bindings = {
        str(source.pk): candidates["bluez_input.phone"].runtime_key,
        str(speakers.pk): candidates["alsa_output.usb-room"].runtime_key,
        str(headset.pk): candidates["bluez_output.headset"].runtime_key,
    }
    graph = {
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(source.pk)},
            },
            {"id": "output", "type": "core.ordered-selector", "configuration": {}},
        ]
    }
    edges = {"route": {"from": {"node": "source"}, "to": {"node": "output"}}}

    def selected(endpoint):
        return {
            "output": {
                "selected": [{"referenceId": str(endpoint.pk)}],
            }
        }

    to_headset = _reconciler()._audio_level_actions(
        graph=graph,
        edges=edges,
        selected_edge_ids=("route",),
        selections=selected(headset),
        bindings=bindings,
        candidates=by_key,
        plan_digest="headset",
    )
    to_speakers = _reconciler()._audio_level_actions(
        graph=graph,
        edges=edges,
        selected_edge_ids=("route",),
        selections=selected(speakers),
        bindings=bindings,
        candidates=by_key,
        plan_digest="speakers",
    )

    assert [item.action.identity.resource_id for item in to_headset] == [str(headset.pk)]
    assert [item.action.identity.resource_id for item in to_speakers] == [str(speakers.pk)]
    assert to_headset[0].action.command.arguments["runtimeKey"].endswith(":node:11")
    assert to_speakers[0].action.command.arguments["runtimeKey"].endswith(":node:10")


def test_explicit_input_mute_can_be_cleared_while_source_is_not_selected() -> None:
    owner = UserFactory()
    source = _endpoint(owner, "Phone", "input", "bluez_input.phone")
    EndpointAudioLevel.objects.create(endpoint=source, level=0.9, muted=False)
    runtime = replace(
        _runtime_with_headset(),
        parameters=tuple(
            (
                replace(
                    parameter,
                    values=(AudioPropertiesValue(volume=0.9, mute=True),),
                )
                if parameter.owner_id == 20
                else parameter
            )
            for parameter in _runtime_with_headset().parameters
        ),
    )
    candidates = _candidate_map(runtime)
    candidate = candidates["bluez_input.phone"]

    actions = _reconciler()._audio_level_actions(
        graph={"nodes": []},
        edges={},
        selected_edge_ids=(),
        selections={},
        bindings={str(source.pk): candidate.runtime_key},
        candidates={candidate.runtime_key: candidate},
        plan_digest="inactive-input-unmute",
    )

    assert len(actions) == 1
    assert actions[0].action.identity.resource_id == str(source.pk)
    assert actions[0].action.command.operation == "set-endpoint-mute"
    assert actions[0].action.command.arguments["mute"] is False


def test_confirmed_state_is_idempotent_and_drift_or_recreation_produces_one_action() -> None:
    owner = UserFactory()
    source = _endpoint(owner, "Phone", "input", "bluez_input.phone")
    sink = _endpoint(owner, "Speakers", "output", "alsa_output.usb-room")
    MasterAudioLevel.objects.create(level=0.6)
    graph = {
        "nodes": [
            {
                "id": "source",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(source.pk)},
            },
            {
                "id": "sink",
                "type": "core.endpoint-reference",
                "configuration": {"logicalEndpointId": str(sink.pk)},
            },
        ]
    }
    edges = {"route": {"from": {"node": "source"}, "to": {"node": "sink"}}}

    def planned(runtime):
        candidates = _candidate_map(runtime)
        by_key = {item.runtime_key: item for item in candidates.values()}
        bindings = {
            str(source.pk): candidates["bluez_input.phone"].runtime_key,
            str(sink.pk): candidates["alsa_output.usb-room"].runtime_key,
        }
        return _reconciler()._audio_level_actions(
            graph=graph,
            edges=edges,
            selected_edge_ids=("route",),
            selections={},
            bindings=bindings,
            candidates=by_key,
            plan_digest="drift",
        )

    confirmed = _runtime_with_headset()
    assert planned(confirmed) == ()

    drifted = replace(
        confirmed,
        sequence=confirmed.sequence + 1,
        parameters=tuple(
            (
                replace(
                    parameter,
                    values=(AudioPropertiesValue(volume=0.3, mute=False),),
                )
                if parameter.owner_id == 10
                else parameter
            )
            for parameter in confirmed.parameters
        ),
    )
    drift_actions = planned(drifted)
    assert len(drift_actions) == 1
    assert drift_actions[0].action.command.arguments["volume"] == 0.6

    restarted = _runtime_with_headset(generation=4)
    recreated = replace(
        restarted,
        parameters=tuple(
            (
                replace(
                    parameter,
                    values=(AudioPropertiesValue(volume=0.3, mute=False),),
                )
                if parameter.owner_id == 10
                else parameter
            )
            for parameter in restarted.parameters
        ),
    )
    recreated_actions = planned(recreated)
    assert len(recreated_actions) == 1
    assert recreated_actions[0].action.command.arguments["runtimeKey"] == "runtime:4:node:10"
