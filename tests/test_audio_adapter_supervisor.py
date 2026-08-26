from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from api.models import ManagedAudioAdapter, ManagedAudioAdapterRuntimeState
from core.orchestration.audio_adapter_driver import AdapterProcessObservation, adapter_node_name
from core.orchestration.audio_adapter_supervisor import AudioAdapterSupervisor
from core.orchestration.audio_adapters import ROC_RECEIVER, normalize_adapter_configuration
from tests.factories.orchestration import UserFactory

pytestmark = pytest.mark.django_db


class Clock:
    def __init__(self):
        self.value = datetime(2026, 8, 23, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class Runtime:
    def __init__(self):
        self.running = True
        self.stop_count = 0
        self.progress = {}

    def poll(self):
        return AdapterProcessObservation(
            self.running,
            123 if self.running else None,
            None if self.running else 1,
            dict(self.progress),
            {} if self.running else {"code": "crashed", "detail": "crashed"},
        )

    def stop(self):
        self.stop_count += 1
        self.running = False
        return dict(self.progress)


class Driver:
    def __init__(self, media_root):
        self.media_root = media_root
        self.started = []
        self.runtimes = []

    def start(self, adapter_id, name, kind, configuration):
        runtime = Runtime()
        self.started.append((str(adapter_id), name, kind, configuration))
        self.runtimes.append(runtime)
        return runtime


def _world(adapter=None):
    candidates = []
    if adapter is not None:
        candidates.append(
            SimpleNamespace(
                name=adapter_node_name(adapter.pk),
                node_properties={"open-cinema.adapter.id": str(adapter.pk)},
                runtime_key="runtime:1:node:42",
            )
        )
    return SimpleNamespace(endpoints=SimpleNamespace(candidates=tuple(candidates)))


def _adapter(tmp_path):
    return ManagedAudioAdapter.objects.create(
        owner=UserFactory(),
        name="ROC input",
        kind=ROC_RECEIVER,
        configuration=normalize_adapter_configuration(
            ROC_RECEIVER,
            {"localAddress": "0.0.0.0"},
        ),
        enabled=True,
    )


def test_supervisor_starts_once_waits_for_node_and_correlates(tmp_path):
    adapter = _adapter(tmp_path)
    driver = Driver(tmp_path)
    supervisor = AudioAdapterSupervisor(driver=driver)

    first = supervisor.reconcile(_world())
    second = supervisor.reconcile(_world(adapter))

    assert first.started == (str(adapter.pk),)
    assert second.ready == (str(adapter.pk),)
    assert len(driver.started) == 1
    state = ManagedAudioAdapterRuntimeState.objects.get(adapter=adapter)
    assert state.lifecycle == "ready"
    assert state.runtime_key == "runtime:1:node:42"
    assert state.runtime_generation == 1


def test_supervisor_restarts_on_configuration_or_explicit_generation(tmp_path):
    adapter = _adapter(tmp_path)
    driver = Driver(tmp_path)
    supervisor = AudioAdapterSupervisor(driver=driver)
    supervisor.reconcile(_world())
    first_runtime = driver.runtimes[-1]

    adapter.configuration = {**adapter.configuration, "latencyMs": 500}
    adapter.save(update_fields=["configuration", "updated_at"])
    changed = supervisor.reconcile(_world())
    adapter.restart_generation += 1
    adapter.save(update_fields=["restart_generation", "updated_at"])
    explicit = supervisor.reconcile(_world())

    assert changed.restarted == (str(adapter.pk),)
    assert explicit.restarted == (str(adapter.pk),)
    assert first_runtime.stop_count == 1
    assert len(driver.started) == 3


def test_supervisor_disable_and_shutdown_leave_no_children(tmp_path):
    adapter = _adapter(tmp_path)
    driver = Driver(tmp_path)
    supervisor = AudioAdapterSupervisor(driver=driver)
    supervisor.reconcile(_world())
    adapter.enabled = False
    adapter.save(update_fields=["enabled", "updated_at"])

    result = supervisor.reconcile(_world())

    assert result.stopped == (str(adapter.pk),)
    assert supervisor.owned_ids == ()
    assert ManagedAudioAdapterRuntimeState.objects.get(adapter=adapter).lifecycle == "stopped"

    adapter.enabled = True
    adapter.save(update_fields=["enabled", "updated_at"])
    supervisor.reconcile(_world())
    supervisor.shutdown()
    assert supervisor.owned_ids == ()
    assert driver.runtimes[-1].stop_count == 1


def test_crash_uses_bounded_backoff_and_never_duplicates(tmp_path):
    adapter = _adapter(tmp_path)
    clock = Clock()
    driver = Driver(tmp_path)
    supervisor = AudioAdapterSupervisor(
        driver=driver,
        clock=clock,
        retry_initial_seconds=1,
        retry_max_seconds=2,
        retry_multiplier=2,
    )
    supervisor.reconcile(_world())
    driver.runtimes[-1].running = False

    failed = supervisor.reconcile(_world())
    waiting = supervisor.reconcile(_world())
    clock.advance(1)
    retried = supervisor.reconcile(_world())

    assert failed.failed == (str(adapter.pk),)
    assert waiting.started == ()
    assert retried.started == (str(adapter.pk),)
    assert len(driver.started) == 2
