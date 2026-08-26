from __future__ import annotations

import logging
from threading import Event
from time import monotonic

from django.conf import settings
from django.db import DatabaseError

from .controller_lock import ControllerLock, ControllerLockState, ControllerLockStatus
from .orchestrator_lifecycle import (
    BoundedReconnectBackoff,
    DependencyHealth,
    OrchestratorLifecycle,
)
from .runtime_event_consumer import RuntimeEventBatchStatus

logger = logging.getLogger(__name__)


class OrchestratorService:
    """Long-lived process boundary extended by the following orchestration tasks."""

    def __init__(
        self,
        *,
        lock_path: str | None = None,
        lock_retry_seconds=None,
        runtime_owner_factory=None,
        connection_probe_seconds=None,
        desired_coordinator_factory=None,
        generation_coordinator=None,
        event_publisher_factory=None,
        runtime_projection_store_factory=None,
        shadow_resolver_factory=None,
        live_reconciler_factory=None,
        adapter_supervisor_factory=None,
        startup_recovery_factory=None,
        lifecycle=None,
        reconnect_backoff=None,
        catchup_max_passes=None,
        catchup_backoff=None,
        clock=monotonic,
    ) -> None:
        self.lock_path = lock_path or settings.AUDIO_ORCHESTRATOR_LOCK_PATH
        self.lock_retry_seconds = (
            settings.AUDIO_ORCHESTRATOR_LOCK_RETRY_SECONDS
            if lock_retry_seconds is None
            else lock_retry_seconds
        )
        if (
            isinstance(self.lock_retry_seconds, bool)
            or not isinstance(self.lock_retry_seconds, (int, float))
            or self.lock_retry_seconds <= 0
        ):
            raise ValueError("lock_retry_seconds must be a positive number")
        self.connection_probe_seconds = (
            settings.AUDIO_ORCHESTRATOR_CONNECTION_PROBE_SECONDS
            if connection_probe_seconds is None
            else connection_probe_seconds
        )
        if (
            isinstance(self.connection_probe_seconds, bool)
            or not isinstance(self.connection_probe_seconds, (int, float))
            or self.connection_probe_seconds <= 0
        ):
            raise ValueError("connection_probe_seconds must be a positive number")
        self.runtime_owner_factory = runtime_owner_factory
        self.desired_coordinator_factory = desired_coordinator_factory
        self.runtime_owner = None
        self.world_snapshot = None
        self.desired_snapshot = None
        if generation_coordinator is None:
            from .generation_guard import OrchestrationGenerationCoordinator

            generation_coordinator = OrchestrationGenerationCoordinator()
        self.generation_coordinator = generation_coordinator
        self.event_publisher_factory = event_publisher_factory
        self.event_publisher = None
        self.runtime_projection_store_factory = runtime_projection_store_factory
        self.runtime_projection_store = None
        self.shadow_resolver_factory = shadow_resolver_factory
        self.shadow_resolver = None
        self.live_reconciler_factory = live_reconciler_factory
        self.live_reconciler = None
        self.adapter_supervisor_factory = adapter_supervisor_factory
        self.adapter_supervisor = None
        self.startup_recovery_factory = startup_recovery_factory
        self.startup_recovery = None
        self.lifecycle = lifecycle or OrchestratorLifecycle()
        self.reconnect_backoff = reconnect_backoff or self._default_reconnect_backoff()
        catchup_configuration = settings.AUDIO_RECONCILIATION_CATCHUP
        self.catchup_max_passes = (
            catchup_configuration["max_passes"]
            if catchup_max_passes is None
            else catchup_max_passes
        )
        if (
            isinstance(self.catchup_max_passes, bool)
            or not isinstance(self.catchup_max_passes, int)
            or not 1 <= self.catchup_max_passes <= 64
        ):
            raise ValueError("catchup_max_passes must be an integer between 1 and 64")
        self.catchup_backoff = catchup_backoff or self._default_catchup_backoff()
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.clock = clock
        self.controller_status: ControllerLockStatus | None = None
        self._catchup_retry_at: float | None = None
        self._catchup_retry_cause: str | None = None

    def run(self, stop_event: Event) -> None:
        if not isinstance(stop_event, Event):
            raise TypeError("stop_event must be a threading.Event")
        lock = ControllerLock(self.lock_path)
        while not stop_event.is_set():
            self.controller_status = lock.acquire()
            if self.controller_status.state is ControllerLockState.ACTIVE:
                break
            logger.warning(
                "Orchestrator is standing by: %s",
                self.controller_status.to_document(),
            )
            stop_event.wait(timeout=float(self.lock_retry_seconds))
        if stop_event.is_set():
            return
        logger.info(
            "Orchestrator is the active controller: %s",
            self.controller_status.to_document(),
        )
        try:
            self.run_active_controller(stop_event)
        finally:
            self.controller_status = lock.release()

    def run_active_controller(self, stop_event: Event) -> None:
        """Run only while holding the deployment controller lock."""

        if self.runtime_owner_factory is None:
            self.runtime_owner_factory = self._default_runtime_owner
        desired_coordinator = (
            self.desired_coordinator_factory()
            if self.desired_coordinator_factory is not None
            else self._default_desired_coordinator()
        )
        self.event_publisher = (
            self.event_publisher_factory()
            if self.event_publisher_factory is not None
            else self._default_event_publisher()
        )
        self.runtime_projection_store = (
            self.runtime_projection_store_factory()
            if self.runtime_projection_store_factory is not None
            else self._default_runtime_projection_store()
        )
        if settings.AUDIO_ORCHESTRATION_FEATURES["runtime_observation"]:
            self.adapter_supervisor = (
                self.adapter_supervisor_factory()
                if self.adapter_supervisor_factory is not None
                else self._default_adapter_supervisor()
            )
        try:
            while not stop_event.is_set():
                self.runtime_owner = None
                try:
                    self.runtime_owner = self.runtime_owner_factory()
                    self._run_connected_session(stop_event, desired_coordinator)
                except Exception as error:
                    if stop_event.is_set():
                        break
                    delay = self.reconnect_backoff.next_delay()
                    reason = f"{type(error).__name__}: {error}"
                    self.lifecycle.dependency(
                        "pipewire",
                        DependencyHealth.UNAVAILABLE,
                        reason=reason,
                    )
                    health = self.lifecycle.reconnecting(
                        "wireplumber",
                        reason=reason,
                        next_retry_seconds=delay,
                    )
                    self._publish_health(health, cause="runtime-connection-failed")
                    logger.warning(
                        "Audio runtime unavailable; reconnecting in %.3f seconds: %s",
                        delay,
                        reason,
                    )
                    stop_event.wait(timeout=delay)
                finally:
                    if self.runtime_owner is not None:
                        try:
                            self.runtime_owner.stop()
                        except Exception as error:
                            logger.warning("Failed to stop audio runtime owner: %s", error)
        finally:
            if self.adapter_supervisor is not None:
                try:
                    self.adapter_supervisor.shutdown()
                except Exception as error:
                    logger.warning("Failed to stop managed audio adapters: %s", error)
            self._publish_health(self.lifecycle.stopping(), cause="shutdown-requested")
            try:
                desired_coordinator.close()
            except Exception as error:
                logger.warning("Failed to close desired-state wake-up listener: %s", error)
            self._publish_health(self.lifecycle.stopped(), cause="shutdown-complete")

    def _run_connected_session(self, stop_event: Event, desired_coordinator) -> None:
        """Run one runtime connection, always beginning with a coherent resnapshot."""

        self._clear_catchup_retry(reset_backoff=True)
        self.world_snapshot = self.runtime_owner.start()
        self.lifecycle.dependency("pipewire", DependencyHealth.READY)
        self.lifecycle.dependency("wireplumber", DependencyHealth.READY)
        self.reconnect_backoff.reset()
        if self.startup_recovery is None:
            self.startup_recovery = (
                self.startup_recovery_factory()
                if self.startup_recovery_factory is not None
                else self._default_startup_recovery()
            )
        recovered = self.startup_recovery.recover(self.world_snapshot)
        if recovered:
            logger.warning(
                "Recovered %s interrupted transition journal(s) against fresh "
                "runtime generation %s.",
                len(recovered),
                self.world_snapshot.runtime.generation,
            )
        self._reconcile_adapters()

        desired_result = self._poll_desired_state(desired_coordinator, force=True)
        self._update_redis_health(desired_coordinator)
        if desired_result is not None:
            self.desired_snapshot = desired_result.snapshot
            self._schedule_current_generations("orchestrator_started")
        self._publish_runtime_projection()
        self._publish_health(self.lifecycle.snapshot, cause="initial-snapshot")
        self._publish_event(
            "runtime",
            {
                "cause": "initial-snapshot",
                "worldVersion": self.world_snapshot.version,
                "runtimeGeneration": self.world_snapshot.runtime.generation,
                "runtimeSequence": self.world_snapshot.runtime.sequence,
            },
        )
        logger.info(
            "Active controller captured runtime world version %s at %s.",
            self.world_snapshot.version,
            self.world_snapshot.position,
        )

        desired_poll_seconds = getattr(
            desired_coordinator,
            "poll_seconds",
            self.connection_probe_seconds,
        )
        event_timeout = min(
            float(self.connection_probe_seconds),
            float(desired_poll_seconds),
        )
        next_connection_probe_at = self.clock() + float(self.connection_probe_seconds)
        while not stop_event.is_set():
            if self._run_due_catchup_retry():
                continue
            batch = self.runtime_owner.consume_event_batch(
                timeout=self._event_wait_timeout(event_timeout)
            )
            if batch.status is RuntimeEventBatchStatus.CLOSED:
                raise RuntimeError("WirePlumber runtime event queue closed")
            self.world_snapshot = self.runtime_owner.current
            now = self.clock()
            if now >= next_connection_probe_at:
                self.runtime_owner.probe()
                next_connection_probe_at = now + float(self.connection_probe_seconds)
            elif batch.world_version is not None:
                next_connection_probe_at = now + float(self.connection_probe_seconds)
            desired_result = self._poll_desired_state(desired_coordinator)
            self._update_redis_health(desired_coordinator)
            if desired_result is not None:
                self.desired_snapshot = desired_result.snapshot
            self._reconcile_adapters()
            self._publish_runtime_projection()
            if batch.world_version is not None or (
                desired_result is not None and desired_result.changed
            ):
                self._schedule_current_generations("runtime_or_desired_state_changed")
            if batch.world_version is not None:
                self._publish_event(
                    "runtime",
                    {
                        "cause": "event-batch",
                        "eventCount": batch.event_count,
                        "reasons": list(batch.reasons),
                        "worldVersion": batch.world_version,
                    },
                )
            if desired_result is not None and desired_result.changed:
                self._publish_event(
                    "progress",
                    {
                        "phase": "generation-scheduled",
                        "changedActivationIds": list(desired_result.changed_activation_ids),
                        "reasons": list(desired_result.reasons),
                    },
                )
            self._publish_health(self.lifecycle.snapshot, cause="health-refresh")
            logger.debug("Runtime event batch: %s", batch)

    def _reconcile_adapters(self) -> None:
        if self.adapter_supervisor is None or self.world_snapshot is None:
            return
        try:
            result = self.adapter_supervisor.reconcile(self.world_snapshot)
        except DatabaseError as error:
            self.lifecycle.dependency(
                "database",
                DependencyHealth.UNAVAILABLE,
                reason=f"{type(error).__name__}: {error}",
            )
            logger.warning("Audio adapter reconciliation database failure: %s", error)
            return
        except Exception as error:
            logger.exception("Audio adapter reconciliation failed: %s", error)
            return
        if result.started or result.stopped or result.restarted or result.failed:
            self._publish_event(
                "progress",
                {
                    "phase": "audio-adapters-reconciled",
                    "started": list(result.started),
                    "stopped": list(result.stopped),
                    "restarted": list(result.restarted),
                    "ready": list(result.ready),
                    "failed": list(result.failed),
                },
            )

    def _poll_desired_state(self, desired_coordinator, *, force=False):
        try:
            result = desired_coordinator.step(force=force)
        except DatabaseError as error:
            self.lifecycle.dependency(
                "database",
                DependencyHealth.UNAVAILABLE,
                reason=f"{type(error).__name__}: {error}",
            )
            logger.warning("Desired-state database poll failed: %s", error)
            return None
        self.lifecycle.dependency("database", DependencyHealth.READY)
        return result

    def _update_redis_health(self, desired_coordinator) -> None:
        if getattr(desired_coordinator, "wakeup_healthy", True):
            self.lifecycle.dependency("redis", DependencyHealth.READY)
            return
        self.lifecycle.dependency(
            "redis",
            DependencyHealth.UNAVAILABLE,
            reason=getattr(desired_coordinator, "last_wakeup_error", None),
        )

    def _publish_health(self, health, *, cause: str) -> None:
        payload = health.to_document()
        payload["cause"] = cause
        payload["controller"] = (
            self.controller_status.to_document() if self.controller_status is not None else None
        )
        self._publish_event("health", payload)

    def _publish_runtime_projection(self) -> None:
        if self.runtime_projection_store is None or self.world_snapshot is None:
            return
        try:
            self.runtime_projection_store.publish(
                self.world_snapshot,
                health=self.lifecycle.snapshot.to_document(),
            )
        except DatabaseError as error:
            self.lifecycle.dependency(
                "database",
                DependencyHealth.UNAVAILABLE,
                reason=f"{type(error).__name__}: {error}",
            )
            logger.warning("Runtime projection database publish failed: %s", error)
            return

    def _publish_event(self, kind, payload, **identifiers):
        if self.event_publisher is None:
            return None
        try:
            return self.event_publisher.publish(kind, payload, **identifiers)
        except Exception as error:
            logger.warning("Ephemeral %s event was not published: %s", kind, error)
            return None

    def _schedule_current_generations(self, cause: str) -> None:
        for catchup_pass in range(self.catchup_max_passes):
            runtime_advanced = self._schedule_current_generation_pass(cause)
            if not runtime_advanced:
                self._clear_catchup_retry(reset_backoff=True)
                return
            cause = "runtime_advanced_during_reconciliation"
        delay = self.catchup_backoff.next_delay()
        retry_at = self.clock() + delay
        if self._catchup_retry_at is None or retry_at < self._catchup_retry_at:
            self._catchup_retry_at = retry_at
            self._catchup_retry_cause = "runtime_catchup_retry"
        logger.warning(
            "Audio runtime kept advancing during %s reconciliation catch-up pass(es); "
            "retrying from a fresh snapshot in %.3f seconds.",
            self.catchup_max_passes,
            delay,
        )
        self._publish_event(
            "progress",
            {
                "phase": "reconciliation-catchup-retry-scheduled",
                "cause": cause,
                "catchupPasses": self.catchup_max_passes,
                "retryDelaySeconds": delay,
            },
        )

    def _event_wait_timeout(self, default_timeout: float) -> float:
        if self._catchup_retry_at is None:
            return default_timeout
        remaining = self._catchup_retry_at - self.clock()
        return min(default_timeout, max(0.001, remaining))

    def _catchup_retry_due(self) -> bool:
        return bool(self._catchup_retry_at is not None and self.clock() >= self._catchup_retry_at)

    def _run_due_catchup_retry(self) -> bool:
        if not self._catchup_retry_due():
            return False
        cause = self._catchup_retry_cause or "runtime_catchup_retry"
        self._catchup_retry_at = None
        self._catchup_retry_cause = None
        if self.runtime_owner is not None:
            self.world_snapshot = self.runtime_owner.current
        self._schedule_current_generations(cause)
        return True

    def _clear_catchup_retry(self, *, reset_backoff: bool) -> None:
        self._catchup_retry_at = None
        self._catchup_retry_cause = None
        if reset_backoff:
            self.catchup_backoff.reset()

    def _schedule_current_generation_pass(self, cause: str) -> bool:
        if self.world_snapshot is None or self.desired_snapshot is None:
            return False
        from .generation_guard import GenerationInput
        from .feature_flags import (
            get_audio_orchestration_feature_flags,
            live_graph_reconciliation_allowed,
        )

        flags = get_audio_orchestration_feature_flags()
        mutation_enabled = flags.audio_mutation_enabled
        shadow_enabled = flags.shadow_resolution and not mutation_enabled
        if not shadow_enabled and not mutation_enabled:
            return False
        if shadow_enabled and self.shadow_resolver is None:
            self.shadow_resolver = (
                self.shadow_resolver_factory()
                if self.shadow_resolver_factory is not None
                else self._default_shadow_resolver()
            )
        if mutation_enabled and self.live_reconciler is None:
            self.live_reconciler = (
                self.live_reconciler_factory()
                if self.live_reconciler_factory is not None
                else self._default_live_reconciler()
            )

        runtime_advanced = False
        for activation in self.desired_snapshot.activations.values():
            if shadow_enabled and not activation["enabled"]:
                continue
            if mutation_enabled and not live_graph_reconciliation_allowed(
                activation["definitionId"]
            ):
                continue
            scheduled = self.generation_coordinator.schedule(
                activation["definitionId"],
                GenerationInput(
                    desired_state_version=activation["desiredStateVersion"],
                    desired_digest=self.desired_snapshot.digest,
                    world_version=self.world_snapshot.version,
                    runtime_generation=self.world_snapshot.runtime.generation,
                    runtime_sequence=self.world_snapshot.runtime.sequence,
                ),
                cause=cause,
            )
            if not scheduled.scheduled:
                continue
            generation = scheduled.generation
            generation_world = self.world_snapshot
            try:
                from .generation_guard import GenerationPhase

                self.generation_coordinator.set_phase(
                    generation,
                    GenerationPhase.RESOLVING,
                )

                if shadow_enabled:
                    outcome = self.shadow_resolver.resolve(
                        activation["definitionId"],
                        self.world_snapshot,
                    )
                    self.generation_coordinator.record_resolved_plan(
                        generation,
                        outcome.plan_digest,
                    )
                    self.generation_coordinator.complete(generation)
                    self._publish_event(
                        "plan",
                        {
                            "phase": "shadow-resolution-complete",
                            "planId": str(outcome.shadow_plan_id),
                            "comparisonId": str(outcome.comparison_id),
                            "baselinePlanId": (
                                str(outcome.baseline_plan_id)
                                if outcome.baseline_plan_id is not None
                                else None
                            ),
                            "status": outcome.status,
                            "equivalent": outcome.equivalent,
                            "actionCount": len(outcome.driver_actions),
                        },
                        graph_definition_id=activation["definitionId"],
                    )
                    continue

                def before_mutation(plan):
                    self.generation_coordinator.record_resolved_plan(
                        generation,
                        plan.plan_digest,
                    )
                    self.generation_coordinator.require_current_before_unsafe_mutation(
                        generation,
                        operation="apply_live_resolved_plan",
                    )

                result = self.live_reconciler.reconcile(
                    activation["definitionId"],
                    generation_world,
                    before_mutation=before_mutation,
                )
                latest_world = None
                if self.runtime_owner is not None:
                    # Driver verification uses a fresh detached snapshot, but the
                    # authoritative owner store must also advance immediately so
                    # API/UI runtime state reflects our own mutations even when the
                    # native event was consumed during the binding confirmation.
                    latest_world = (
                        self.runtime_owner.refresh()
                        if result.action_count
                        else self.runtime_owner.current
                    )
                if latest_world is not None and latest_world.position != generation_world.position:
                    self.world_snapshot = latest_world
                    self._publish_runtime_projection()
                    # Reconciliation can refresh the authoritative runtime while
                    # merely proving that an already-satisfied processor topology
                    # remains healthy. That observation often advances the
                    # PipeWire sequence for an active stream, but it does not make
                    # the resolved no-op stale or require another immediate pass.
                    # Only outcomes that performed/failed a topology transition
                    # explicitly request catch-up.
                    runtime_advanced = runtime_advanced or bool(
                        getattr(result, "catchup_required", False)
                    )
                self.generation_coordinator.record_resolved_plan(
                    generation,
                    result.plan.plan_digest,
                )
                self.generation_coordinator.complete(generation)
                self._publish_event(
                    "plan",
                    {
                        "phase": "live-reconciliation-complete",
                        "planId": str(result.plan.pk),
                        "status": result.plan.status,
                        "applied": result.applied,
                        "actionCount": result.action_count,
                        "reason": result.reason,
                    },
                    graph_definition_id=activation["definitionId"],
                )
            except Exception as error:
                mode = "shadow-resolution" if shadow_enabled else "live-reconciliation"
                logger.exception(
                    "%s failed for graph %s.",
                    mode,
                    activation["definitionId"],
                )
                self._publish_event(
                    "progress",
                    {
                        "phase": f"{mode}-failed",
                        "error": f"{type(error).__name__}: {error}",
                    },
                    graph_definition_id=activation["definitionId"],
                )
        return runtime_advanced

    @staticmethod
    def _default_runtime_owner():
        from redis import Redis

        from .runtime_world import RedisWorldProjection, WyrePlumberRuntimeOwner

        configuration = settings.AUDIO_RUNTIME_REDIS_PROJECTION
        publisher = RedisWorldProjection(
            Redis.from_url(configuration["url"]),
            key=configuration["key"],
            ttl_seconds=configuration["ttl_seconds"],
            max_bytes=configuration["max_bytes"],
            max_endpoints=configuration["max_endpoints"],
        )
        return WyrePlumberRuntimeOwner(publisher=publisher)

    def _default_live_reconciler(self):
        from .live_reconciliation import LiveGraphReconciler
        from .managed_processor_controller import ManagedProcessorController

        return LiveGraphReconciler(
            lambda: self.runtime_owner.connection,
            processor_controller=ManagedProcessorController(),
            runtime_refresher=lambda: self.runtime_owner.refresh(),
        )

    @staticmethod
    def _default_shadow_resolver():
        from .shadow_resolution import ShadowGraphResolver

        return ShadowGraphResolver()

    @staticmethod
    def _default_adapter_supervisor():
        from .audio_adapter_supervisor import AudioAdapterSupervisor

        return AudioAdapterSupervisor()

    @staticmethod
    def _default_startup_recovery():
        from .startup_transition_recovery import StartupTransitionRecovery

        return StartupTransitionRecovery()

    @staticmethod
    def _default_desired_coordinator():
        from redis import Redis

        from .desired_state_monitor import (
            DesiredStateCoordinator,
            DesiredStateMonitor,
            RedisDesiredStateWakeupListener,
        )

        redis_configuration = settings.AUDIO_RUNTIME_REDIS_PROJECTION
        monitor_configuration = settings.AUDIO_DESIRED_STATE_MONITOR

        def listener_factory():
            return RedisDesiredStateWakeupListener(
                Redis.from_url(redis_configuration["url"]),
                monitor_configuration["channel"],
            )

        return DesiredStateCoordinator(
            DesiredStateMonitor(),
            poll_seconds=monitor_configuration["poll_seconds"],
            wakeup_listener_factory=listener_factory,
        )

    @staticmethod
    def _default_reconnect_backoff():
        configuration = settings.AUDIO_ORCHESTRATOR_RECONNECT
        return BoundedReconnectBackoff(
            initial_seconds=configuration["initial_seconds"],
            max_seconds=configuration["max_seconds"],
            multiplier=configuration["multiplier"],
            jitter_ratio=configuration["jitter_ratio"],
        )

    @staticmethod
    def _default_catchup_backoff():
        configuration = settings.AUDIO_RECONCILIATION_CATCHUP
        return BoundedReconnectBackoff(
            initial_seconds=configuration["retry_initial_seconds"],
            max_seconds=configuration["retry_max_seconds"],
            multiplier=configuration["retry_multiplier"],
            jitter_ratio=0.0,
        )

    @staticmethod
    def _default_event_publisher():
        from redis import Redis

        from .redis_events import OrchestrationRedisEventPublisher

        redis_configuration = settings.AUDIO_RUNTIME_REDIS_PROJECTION
        event_configuration = settings.AUDIO_REDIS_EVENT_STREAM
        return OrchestrationRedisEventPublisher(
            Redis.from_url(redis_configuration["url"]),
            stream_key=event_configuration["key"],
            max_entries=event_configuration["max_entries"],
            max_bytes=event_configuration["max_bytes"],
            ttl_seconds=event_configuration["ttl_seconds"],
        )

    @staticmethod
    def _default_runtime_projection_store():
        from .runtime_projection_store import DatabaseRuntimeProjectionStore

        return DatabaseRuntimeProjectionStore()
