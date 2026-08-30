import pytest

from api.models import EndpointAudioLevel, LogicalEndpoint, MasterAudioLevel
from core.orchestration.desired_state_monitor import (
    DesiredStateCoordinator,
    DesiredStateMonitor,
    RedisDesiredStateWakeupListener,
)
from tests.factories import GraphActivationFactory


def _activation(version=1):
    return {
        "activationId": "activation:main",
        "definitionId": "graph:main",
        "revisionId": f"revision:main:{version}",
        "desiredStateVersion": version,
        "updatedAt": f"2026-08-22T16:00:0{version}Z",
    }


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Wakeups:
    def __init__(self, values):
        self.values = list(values)
        self.closed = False

    def poll(self):
        return self.values.pop(0) if self.values else False

    def close(self):
        self.closed = True


def test_periodic_database_poll_detects_change_when_wakeup_is_lost() -> None:
    documents = [_activation(1)]
    clock = Clock()
    wakeups = Wakeups((False, False, False))
    coordinator = DesiredStateCoordinator(
        DesiredStateMonitor(query=lambda: documents),
        poll_seconds=5,
        wakeup_listener=wakeups,
        clock=clock,
    )

    initial = coordinator.step()
    documents[:] = [_activation(2)]
    clock.now = 4.9
    early = coordinator.step()
    clock.now = 5.0
    detected = coordinator.step()

    assert initial.changed is True
    assert early is None
    assert detected.changed is True
    assert detected.snapshot.activations["activation:main"]["desiredStateVersion"] == 2
    assert detected.reasons == ("desired_state_version_advanced",)


def test_wakeup_causes_immediate_database_poll_but_is_not_state() -> None:
    documents = [_activation(1)]
    clock = Clock()
    coordinator = DesiredStateCoordinator(
        DesiredStateMonitor(query=lambda: documents),
        poll_seconds=60,
        wakeup_listener=Wakeups((False, True)),
        clock=clock,
    )
    coordinator.step()
    documents[:] = [_activation(2)]
    clock.now = 0.1

    result = coordinator.step()

    assert result.changed is True
    assert result.snapshot.activations["activation:main"]["revisionId"] == ("revision:main:2")


def test_redis_listener_reconnects_without_blocking_authoritative_database_poll() -> None:
    documents = [_activation(1)]
    clock = Clock()
    attempts = []
    wakeups = Wakeups((False,))

    def listener_factory():
        attempts.append("connect")
        if len(attempts) == 1:
            raise ConnectionError("redis restarting")
        return wakeups

    coordinator = DesiredStateCoordinator(
        DesiredStateMonitor(query=lambda: documents),
        poll_seconds=60,
        wakeup_listener_factory=listener_factory,
        clock=clock,
    )

    initial = coordinator.step(force=True)
    documents[:] = [_activation(2)]
    recovered = coordinator.step(force=True)

    assert initial.changed is True
    assert recovered.changed is True
    assert recovered.snapshot.activations["activation:main"]["desiredStateVersion"] == 2
    assert attempts == ["connect", "connect"]
    assert coordinator.wakeup_healthy is True
    assert coordinator.last_wakeup_error is None
    coordinator.close()
    assert wakeups.closed is True


def test_monitor_reports_removal_and_version_regression_explicitly() -> None:
    documents = [_activation(2), {**_activation(1), "activationId": "other"}]
    monitor = DesiredStateMonitor(query=lambda: documents)
    monitor.poll()
    documents[:] = [_activation(1)]

    result = monitor.poll()

    assert result.changed_activation_ids == ("activation:main", "other")
    assert result.reasons == (
        "activation_removed",
        "desired_state_version_regressed",
    )


def test_redis_listener_treats_messages_only_as_boolean_hints() -> None:
    class PubSub:
        def __init__(self):
            self.messages = [None, {"type": "message", "data": b"untrusted"}]
            self.subscribed = None
            self.closed = False

        def subscribe(self, channel):
            self.subscribed = channel

        def get_message(self, timeout):
            return self.messages.pop(0)

        def close(self):
            self.closed = True

    pubsub = PubSub()
    client = type(
        "Redis",
        (),
        {"pubsub": lambda _self, **_kwargs: pubsub},
    )()
    listener = RedisDesiredStateWakeupListener(client, "desired")

    assert listener.poll() is False
    assert listener.poll() is True
    assert pubsub.subscribed == "desired"
    listener.close()
    assert pubsub.closed is True


@pytest.mark.django_db
def test_default_monitor_reads_authoritative_activation_versions_from_database() -> None:
    activation = GraphActivationFactory(desired_state_version=7)

    result = DesiredStateMonitor().poll()

    document = result.snapshot.activations[str(activation.pk)]
    assert document["definitionId"] == str(activation.definition_id)
    assert document["revisionId"] == str(activation.revision_id)
    assert document["desiredStateVersion"] == 7


@pytest.mark.django_db
def test_default_monitor_keeps_disabled_activation_as_versioned_desired_state() -> None:
    activation = GraphActivationFactory(desired_state_version=8, enabled=False)

    result = DesiredStateMonitor().poll()

    document = result.snapshot.activations[str(activation.pk)]
    assert document["enabled"] is False
    assert document["revisionId"] is None
    assert document["desiredStateVersion"] == 8


@pytest.mark.django_db
def test_default_monitor_schedules_active_graphs_when_audio_level_intent_changes() -> None:
    activation = GraphActivationFactory(desired_state_version=4)
    endpoint = LogicalEndpoint.objects.create(
        owner=activation.definition.owner,
        name="Main speakers",
        direction="output",
        selector={
            "version": 1,
            "match": "all",
            "predicates": [{"path": "node.name", "operator": "exact", "value": "main-output"}],
        },
    )
    master = MasterAudioLevel.objects.create(level=0.8)
    EndpointAudioLevel.objects.create(endpoint=endpoint, level=0.5)
    monitor = DesiredStateMonitor()
    initial = monitor.poll()
    master.level = 0.7
    master.update_version += 1
    master.save()

    changed = monitor.poll()

    activation_id = str(activation.pk)
    assert initial.snapshot.activations[activation_id]["audioLevels"]["master"]["level"] == 0.8
    assert changed.changed_activation_ids == (activation_id,)
    assert changed.reasons == ("audio_level_intent_changed",)
    assert [
        item.to_dict()
        for item in changed.snapshot.activations[activation_id]["audioLevels"]["endpoints"]
    ] == [
        {
            "endpointId": str(endpoint.pk),
            "level": 0.5,
            "muted": False,
            "updateVersion": 1,
        }
    ]
