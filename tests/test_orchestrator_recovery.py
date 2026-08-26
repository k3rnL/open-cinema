from dataclasses import replace
from threading import Event
from types import SimpleNamespace

from django.db import DatabaseError
from django.test import override_settings
from wyreplumber.runtime import FrozenDict

from core.orchestration.desired_state_monitor import DesiredStateMonitor
from core.orchestration.orchestrator_lifecycle import DependencyHealth
from core.orchestration.orchestrator_service import OrchestratorService
from core.orchestration.runtime_event_consumer import (
    RuntimeEventBatchResult,
    RuntimeEventBatchStatus,
)
from core.orchestration.runtime_world import InMemoryWorldStore
from tests.test_endpoint_inventory_mapping import _snapshot


def _idle_batch():
    return RuntimeEventBatchResult(
        status=RuntimeEventBatchStatus.IDLE,
        event_count=0,
        first_sequence=None,
        last_sequence=None,
        world_version=None,
        reasons=(),
        causes=FrozenDict(),
    )


class EventPublisher:
    def __init__(self):
        self.events = []

    def publish(self, kind, payload, **identifiers):
        self.events.append((str(kind), payload, identifiers))


class RecordingBackoff:
    def __init__(self):
        self.attempts = 0
        self.resets = 0

    def next_delay(self):
        self.attempts += 1
        return 0

    def reset(self):
        self.resets += 1


class RecordingRuntimeProjectionStore:
    def __init__(self):
        self.publications = []

    def publish(self, world, *, health=None):
        self.publications.append((world, health))


class DesiredCoordinator:
    poll_seconds = 0.001

    def __init__(self, effects, *, redis_health=True):
        self.effects = list(effects)
        self.wakeup_healthy = redis_health
        self.last_wakeup_error = None if redis_health else "redis unavailable"
        self.forces = []
        self.closed = False

    def step(self, *, force=False):
        self.forces.append(force)
        effect = self.effects.pop(0) if self.effects else None
        if isinstance(effect, Exception):
            raise effect
        if callable(effect):
            return effect(self)
        return effect

    def close(self):
        self.closed = True


class RuntimeOwner:
    def __init__(
        self,
        world,
        stop_event,
        *,
        start_error=None,
        stop_after_batches=1,
        batch_status=RuntimeEventBatchStatus.IDLE,
        probe_error=None,
    ):
        self.world = world
        self.stop_event = stop_event
        self.start_error = start_error
        self.stop_after_batches = stop_after_batches
        self.batch_status = batch_status
        self.probe_error = probe_error
        self.starts = 0
        self.stops = 0
        self.batches = 0
        self.probes = 0

    @property
    def current(self):
        return self.world

    def start(self):
        self.starts += 1
        if self.start_error is not None:
            raise self.start_error
        return self.world

    def consume_event_batch(self, *, timeout):
        assert timeout > 0
        self.batches += 1
        if self.batches >= self.stop_after_batches:
            self.stop_event.set()
        batch = _idle_batch()
        if self.batch_status is RuntimeEventBatchStatus.IDLE:
            return batch
        return RuntimeEventBatchResult(
            status=self.batch_status,
            event_count=batch.event_count,
            first_sequence=batch.first_sequence,
            last_sequence=batch.last_sequence,
            world_version=batch.world_version,
            reasons=batch.reasons,
            causes=batch.causes,
        )

    def probe(self):
        self.probes += 1
        if self.probe_error is not None:
            raise self.probe_error

    def stop(self):
        self.stops += 1


def _world(generation):
    return InMemoryWorldStore().install_runtime_snapshot(_snapshot(generation=generation))


def _service(
    stop_event,
    owners,
    desired,
    *,
    adapter_supervisor_factory=None,
    shadow_resolver_factory=None,
    clock=None,
):
    publisher = EventPublisher()
    backoff = RecordingBackoff()
    remaining = list(owners)
    projection_store = RecordingRuntimeProjectionStore()
    arguments = dict(
        runtime_owner_factory=lambda: remaining.pop(0),
        desired_coordinator_factory=lambda: desired,
        event_publisher_factory=lambda: publisher,
        runtime_projection_store_factory=lambda: projection_store,
        reconnect_backoff=backoff,
        connection_probe_seconds=0.01,
        adapter_supervisor_factory=adapter_supervisor_factory,
        shadow_resolver_factory=shadow_resolver_factory,
        startup_recovery_factory=lambda: SimpleNamespace(recover=lambda world: ()),
    )
    if clock is not None:
        arguments["clock"] = clock
    service = OrchestratorService(**arguments)
    service.run_active_controller(stop_event)
    return service, publisher, backoff, projection_store


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": False,
        "live_reconciliation": False,
    }
)
def test_active_graph_runs_shadow_generation_without_live_reconciler() -> None:
    definition_id = "00000000-0000-0000-0000-000000000001"
    activation = {
        "activationId": "00000000-0000-0000-0000-000000000002",
        "definitionId": definition_id,
        "revisionId": "00000000-0000-0000-0000-000000000003",
        "enabled": True,
        "desiredStateVersion": 1,
        "updatedAt": "2026-08-25T00:00:00+00:00",
    }

    class ShadowResolver:
        def __init__(self):
            self.calls = []

        def resolve(self, graph_definition_id, world):
            self.calls.append((graph_definition_id, world))
            return SimpleNamespace(
                shadow_plan_id="00000000-0000-0000-0000-000000000004",
                comparison_id="00000000-0000-0000-0000-000000000005",
                baseline_plan_id=None,
                status="resolved",
                plan_digest="a" * 64,
                equivalent=False,
                driver_actions=(),
            )

    stop_event = Event()
    resolver = ShadowResolver()
    desired = DesiredCoordinator((DesiredStateMonitor(query=lambda: (activation,)).poll(), None))
    owner = RuntimeOwner(_world(9), stop_event)

    service, publisher, _backoff, _projection = _service(
        stop_event,
        (owner,),
        desired,
        shadow_resolver_factory=lambda: resolver,
    )

    assert [(graph_id, world.runtime.generation) for graph_id, world in resolver.calls] == [
        (definition_id, 9)
    ]
    assert service.live_reconciler is None
    generation = service.generation_coordinator.current(definition_id)
    assert generation.status.value == "completed"
    assert generation.resolved_plan_digest == "a" * 64
    plan_event = next(payload for kind, payload, _ids in publisher.events if kind == "plan")
    assert plan_event["phase"] == "shadow-resolution-complete"
    assert plan_event["actionCount"] == 0


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": True,
        "live_reconciliation": True,
    },
    AUDIO_LIVE_GRAPH_ALLOWLIST=("graph:allowed",),
)
def test_limited_live_schedules_only_explicitly_allowlisted_graphs() -> None:
    class LiveReconciler:
        def __init__(self):
            self.calls = []

        def reconcile(self, definition_id, world, *, before_mutation):
            plan = SimpleNamespace(
                pk="00000000-0000-0000-0000-000000000004",
                plan_digest="b" * 64,
                status="resolved",
            )
            before_mutation(plan)
            self.calls.append((definition_id, world.runtime.generation))
            return SimpleNamespace(
                plan=plan,
                applied=True,
                action_count=0,
                reason="controlled",
            )

    activation = lambda definition_id: {
        "activationId": f"activation:{definition_id}",
        "definitionId": definition_id,
        "revisionId": f"revision:{definition_id}",
        "enabled": True,
        "desiredStateVersion": 1,
        "updatedAt": "2026-08-25T00:00:00+00:00",
    }
    reconciler = LiveReconciler()
    service = OrchestratorService(live_reconciler_factory=lambda: reconciler)
    service.world_snapshot = _world(9)
    service.desired_snapshot = SimpleNamespace(
        activations=FrozenDict(
            {
                "allowed": activation("graph:allowed"),
                "blocked": activation("graph:blocked"),
            }
        ),
        digest="desired-digest",
    )
    service.event_publisher = EventPublisher()

    service._schedule_current_generations("allowlist-test")

    assert reconciler.calls == [("graph:allowed", 9)]
    assert service.generation_coordinator.current("graph:blocked") is None


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": True,
        "live_reconciliation": True,
    },
    AUDIO_LIVE_GRAPH_ALLOWLIST=("graph:allowed",),
)
def test_live_reconciliation_catches_up_when_outcome_requests_it() -> None:
    definition_id = "graph:allowed"
    initial_world = _world(9)
    advanced_store = InMemoryWorldStore()
    advanced_store.install_runtime_snapshot(initial_world.runtime)
    advanced_world = advanced_store.install_runtime_snapshot(
        replace(initial_world.runtime, sequence=initial_world.runtime.sequence + 1)
    )

    class AdvancingRuntimeOwner:
        def __init__(self):
            self.world = initial_world

        @property
        def current(self):
            return self.world

    owner = AdvancingRuntimeOwner()

    class LiveReconciler:
        def __init__(self):
            self.calls = []

        def reconcile(self, graph_definition_id, world, *, before_mutation):
            self.calls.append((graph_definition_id, world.position))
            if len(self.calls) == 1:
                owner.world = advanced_world
            return SimpleNamespace(
                plan=SimpleNamespace(
                    pk=f"plan:{len(self.calls)}",
                    plan_digest=str(len(self.calls)) * 64,
                    status="resolved",
                ),
                applied=False,
                action_count=0,
                catchup_required=len(self.calls) == 1,
                reason="stale endpoint selection" if len(self.calls) == 1 else "converged",
            )

    activation = {
        "activationId": "activation:allowed",
        "definitionId": definition_id,
        "revisionId": "revision:allowed",
        "enabled": True,
        "desiredStateVersion": 1,
        "updatedAt": "2026-08-25T00:00:00+00:00",
    }
    reconciler = LiveReconciler()
    service = OrchestratorService(live_reconciler_factory=lambda: reconciler)
    service.runtime_owner = owner
    service.world_snapshot = initial_world
    service.desired_snapshot = SimpleNamespace(
        activations=FrozenDict({"allowed": activation}),
        digest="desired-digest",
    )
    service.event_publisher = EventPublisher()

    service._schedule_current_generations("runtime-event")

    assert reconciler.calls == [
        (definition_id, initial_world.position),
        (definition_id, advanced_world.position),
    ]
    assert service.world_snapshot is advanced_world
    generation = service.generation_coordinator.current(definition_id)
    assert generation.inputs.runtime_sequence == advanced_world.runtime.sequence
    assert generation.status.value == "completed"


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": True,
        "live_reconciliation": True,
    },
    AUDIO_LIVE_GRAPH_ALLOWLIST=("graph:allowed",),
)
def test_satisfied_noop_absorbs_observation_advance_without_catchup() -> None:
    definition_id = "graph:allowed"
    initial_world = _world(9)
    advanced_store = InMemoryWorldStore()
    advanced_store.install_runtime_snapshot(initial_world.runtime)
    advanced_world = advanced_store.install_runtime_snapshot(
        replace(initial_world.runtime, sequence=initial_world.runtime.sequence + 1)
    )

    class AdvancingRuntimeOwner:
        def __init__(self):
            self.world = initial_world

        @property
        def current(self):
            return self.world

    owner = AdvancingRuntimeOwner()

    class LiveReconciler:
        def __init__(self):
            self.calls = []

        def reconcile(self, graph_definition_id, world, *, before_mutation):
            self.calls.append((graph_definition_id, world.position))
            owner.world = advanced_world
            return SimpleNamespace(
                plan=SimpleNamespace(
                    pk="plan:noop",
                    plan_digest="n" * 64,
                    status="resolved",
                ),
                applied=False,
                action_count=0,
                catchup_required=False,
                reason="effective runtime plan is already satisfied",
            )

    activation = {
        "activationId": "activation:allowed",
        "definitionId": definition_id,
        "revisionId": "revision:allowed",
        "enabled": True,
        "desiredStateVersion": 1,
        "updatedAt": "2026-08-25T00:00:00+00:00",
    }
    reconciler = LiveReconciler()
    service = OrchestratorService(live_reconciler_factory=lambda: reconciler)
    service.runtime_owner = owner
    service.world_snapshot = initial_world
    service.desired_snapshot = SimpleNamespace(
        activations=FrozenDict({"allowed": activation}),
        digest="desired-digest",
    )
    service.event_publisher = EventPublisher()

    service._schedule_current_generations("runtime-event")

    assert reconciler.calls == [(definition_id, initial_world.position)]
    assert service.world_snapshot is advanced_world
    assert service._catchup_retry_at is None


def test_catchup_exhaustion_wakes_itself_after_runtime_becomes_quiet() -> None:
    now = [10.0]

    class CatchupBackoff:
        def __init__(self):
            self.attempts = 0
            self.resets = 0

        def next_delay(self):
            self.attempts += 1
            return 0.5

        def reset(self):
            self.resets += 1

    backoff = CatchupBackoff()
    service = OrchestratorService(
        catchup_max_passes=2,
        catchup_backoff=backoff,
        clock=lambda: now[0],
    )
    service.event_publisher = EventPublisher()
    outcomes = iter((True, True, False))
    causes = []

    def generation_pass(cause):
        causes.append(cause)
        return next(outcomes)

    service._schedule_current_generation_pass = generation_pass

    service._schedule_current_generations("runtime-event")

    assert causes == ["runtime-event", "runtime_advanced_during_reconciliation"]
    assert backoff.attempts == 1
    assert service._event_wait_timeout(5.0) == 0.5
    assert service._run_due_catchup_retry() is False

    now[0] = 10.5

    assert service._run_due_catchup_retry() is True
    assert causes[-1] == "runtime_catchup_retry"
    assert service._catchup_retry_at is None
    assert backoff.resets == 1
    progress = [
        payload
        for kind, payload, _identifiers in service.event_publisher.events
        if kind == "progress"
    ]
    assert progress == [
        {
            "phase": "reconciliation-catchup-retry-scheduled",
            "cause": "runtime_advanced_during_reconciliation",
            "catchupPasses": 2,
            "retryDelaySeconds": 0.5,
        }
    ]


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": False,
        "processor_management": False,
        "live_reconciliation": False,
    }
)
def test_active_controller_reconciles_and_cleans_up_adapter_supervisor() -> None:
    class Supervisor:
        def __init__(self):
            self.worlds = []
            self.shutdowns = 0

        def reconcile(self, world):
            self.worlds.append(world)
            return SimpleNamespace(started=(), stopped=(), restarted=(), ready=(), failed=())

        def shutdown(self):
            self.shutdowns += 1

    stop_event = Event()
    supervisor = Supervisor()
    desired = DesiredCoordinator((DesiredStateMonitor(query=lambda: ()).poll(), None))
    owner = RuntimeOwner(_world(8), stop_event)

    _service(
        stop_event,
        (owner,),
        desired,
        adapter_supervisor_factory=lambda: supervisor,
    )

    assert len(supervisor.worlds) == 2
    assert supervisor.shutdowns == 1


def test_pipewire_and_wireplumber_restart_reconnects_and_resnapshots() -> None:
    stop_event = Event()
    failed_pipewire = RuntimeOwner(
        _world(1),
        stop_event,
        start_error=RuntimeError("PipeWire socket unavailable"),
    )
    disconnected_wireplumber = RuntimeOwner(
        _world(2),
        stop_event,
        stop_after_batches=2,
        batch_status=RuntimeEventBatchStatus.CLOSED,
    )
    recovered = RuntimeOwner(_world(3), stop_event)
    desired = DesiredCoordinator((DesiredStateMonitor(query=lambda: ()).poll(), None))

    service, publisher, backoff, projection_store = _service(
        stop_event,
        (failed_pipewire, disconnected_wireplumber, recovered),
        desired,
    )

    assert [owner.starts for owner in (failed_pipewire, disconnected_wireplumber, recovered)] == [
        1,
        1,
        1,
    ]
    assert [owner.stops for owner in (failed_pipewire, disconnected_wireplumber, recovered)] == [
        1,
        1,
        1,
    ]
    assert backoff.attempts == 2
    assert backoff.resets == 2
    assert service.world_snapshot.runtime.generation == 3
    assert [world.runtime.generation for world, _health in projection_store.publications] == [
        2,
        3,
        3,
    ]
    assert service.lifecycle.snapshot.dependencies["pipewire"]["health"] == (
        DependencyHealth.READY.value
    )
    assert service.lifecycle.snapshot.dependencies["wireplumber"]["health"] == (
        DependencyHealth.READY.value
    )
    assert desired.forces[0] is True
    health_states = [
        payload["state"] for kind, payload, _identifiers in publisher.events if kind == "health"
    ]
    assert health_states.count("reconnecting") == 2
    assert "ready" in health_states
    assert health_states[-2:] == ["stopping", "stopped"]


def test_periodic_probe_detects_a_silent_stale_pipewire_connection() -> None:
    class AdvancingClock:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            self.value += 1.0
            return self.value

    stop_event = Event()
    stale = RuntimeOwner(
        _world(2),
        stop_event,
        stop_after_batches=100,
        probe_error=RuntimeError("WirePlumber runtime is not ready"),
    )
    recovered = RuntimeOwner(_world(3), stop_event)
    desired = DesiredCoordinator((DesiredStateMonitor(query=lambda: ()).poll(), None, None))

    service, _publisher, backoff, _projection_store = _service(
        stop_event,
        (stale, recovered),
        desired,
        clock=AdvancingClock(),
    )

    assert stale.probes == 1
    assert [stale.starts, recovered.starts] == [1, 1]
    assert backoff.attempts == 1
    assert service.world_snapshot.runtime.generation == 3


def test_database_restart_pauses_readiness_then_recovers_without_runtime_reconnect() -> None:
    stop_event = Event()
    desired_snapshot = DesiredStateMonitor(query=lambda: ()).poll()
    desired = DesiredCoordinator((DatabaseError("database restarting"), desired_snapshot, None))
    owner = RuntimeOwner(_world(4), stop_event, stop_after_batches=2)

    service, publisher, backoff, _projection_store = _service(stop_event, (owner,), desired)

    assert backoff.attempts == 0
    assert owner.starts == 1
    assert service.lifecycle.snapshot.dependencies["database"]["health"] == (
        DependencyHealth.READY.value
    )
    health = [payload for kind, payload, _identifiers in publisher.events if kind == "health"]
    assert any(
        event["dependencies"]["database"]["health"] == "unavailable" and event["ready"] is False
        for event in health
    )
    assert any(
        event["dependencies"]["database"]["health"] == "ready" and event["ready"] is True
        for event in health
    )


def test_redis_restart_is_degraded_but_non_authoritative_and_recovers() -> None:
    stop_event = Event()
    desired_snapshot = DesiredStateMonitor(query=lambda: ()).poll()

    def redis_recovers(coordinator):
        coordinator.wakeup_healthy = True
        coordinator.last_wakeup_error = None
        return None

    desired = DesiredCoordinator(
        (desired_snapshot, redis_recovers),
        redis_health=False,
    )
    owner = RuntimeOwner(_world(5), stop_event)

    service, publisher, backoff, _projection_store = _service(stop_event, (owner,), desired)

    assert backoff.attempts == 0
    assert owner.starts == 1
    assert service.lifecycle.snapshot.dependencies["redis"]["health"] == (
        DependencyHealth.READY.value
    )
    health = [payload for kind, payload, _identifiers in publisher.events if kind == "health"]
    redis_down = next(
        event for event in health if event["dependencies"]["redis"]["health"] == "unavailable"
    )
    assert redis_down["state"] == "degraded"
    assert redis_down["ready"] is True
    assert any(event["dependencies"]["redis"]["health"] == "ready" for event in health)
    assert desired.closed is True
    assert service.lifecycle.snapshot.live is False
