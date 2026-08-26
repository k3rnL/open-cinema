from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from api.models import (
    AudioAdapterHealth,
    AudioAdapterLifecycle,
    ManagedAudioAdapter,
    ManagedAudioAdapterRuntimeState,
)

from .audio_adapter_driver import (
    AudioAdapterDriver,
    adapter_configuration_digest,
    adapter_node_name,
)
from .audio_adapters import normalize_adapter_configuration


@dataclass(slots=True)
class _OwnedRuntime:
    runtime: object
    digest: str
    generation: int


@dataclass(frozen=True, slots=True)
class AdapterSupervisorResult:
    started: tuple[str, ...]
    stopped: tuple[str, ...]
    restarted: tuple[str, ...]
    ready: tuple[str, ...]
    failed: tuple[str, ...]


class AudioAdapterSupervisor:
    """Single-controller reconciler for endpoint-producing child resources."""

    def __init__(
        self,
        *,
        driver: AudioAdapterDriver | None = None,
        clock=timezone.now,
        retry_initial_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        retry_multiplier: float | None = None,
    ) -> None:
        lifecycle = settings.AUDIO_ADAPTER_LIFECYCLE
        self.driver = driver or AudioAdapterDriver()
        self.clock = clock
        self.retry_initial_seconds = float(
            retry_initial_seconds
            if retry_initial_seconds is not None
            else lifecycle["retry_initial_seconds"]
        )
        self.retry_max_seconds = float(
            retry_max_seconds
            if retry_max_seconds is not None
            else lifecycle["retry_max_seconds"]
        )
        self.retry_multiplier = float(
            retry_multiplier
            if retry_multiplier is not None
            else lifecycle["retry_multiplier"]
        )
        self._owned: dict[str, _OwnedRuntime] = {}
        self._attempts: dict[str, int] = {}

    @property
    def owned_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._owned))

    @staticmethod
    def _runtime_candidate(world, adapter_id: str, expected_node_name: str):
        if world is None:
            return None
        for candidate in world.endpoints.candidates:
            properties = candidate.node_properties
            if (
                str(properties.get("open-cinema.adapter.id", "")) == adapter_id
                or candidate.name == expected_node_name
            ):
                return candidate
        return None

    @staticmethod
    def _write_state(adapter, **values) -> ManagedAudioAdapterRuntimeState:
        state, _ = ManagedAudioAdapterRuntimeState.objects.get_or_create(adapter=adapter)
        changed = []
        for name, value in values.items():
            if getattr(state, name) != value:
                setattr(state, name, value)
                changed.append(name)
        if changed:
            state.save(update_fields=[*changed, "updated_at"])
        return state

    def _backoff(self, adapter, error: dict[str, object]) -> None:
        identity = str(adapter.pk)
        attempt = self._attempts.get(identity, 0)
        delay = min(
            self.retry_max_seconds,
            self.retry_initial_seconds * (self.retry_multiplier**attempt),
        )
        self._attempts[identity] = attempt + 1
        previous = ManagedAudioAdapterRuntimeState.objects.filter(adapter=adapter).first()
        self._write_state(
            adapter,
            lifecycle=AudioAdapterLifecycle.BACKOFF,
            health=AudioAdapterHealth.UNHEALTHY,
            process_id=None,
            runtime_key=None,
            progress=(previous.progress if previous is not None else {}),
            retry_at=self.clock() + timedelta(seconds=delay),
            last_error=error,
            observed_at=self.clock(),
        )

    def _stop(self, adapter, owned: _OwnedRuntime, *, error=None) -> dict[str, object]:
        self._write_state(
            adapter,
            lifecycle=AudioAdapterLifecycle.STOPPING,
            health=AudioAdapterHealth.UNKNOWN,
            runtime_key=None,
            observed_at=self.clock(),
        )
        progress = owned.runtime.stop()
        self._write_state(
            adapter,
            lifecycle=AudioAdapterLifecycle.STOPPED,
            health=AudioAdapterHealth.UNKNOWN,
            process_id=None,
            runtime_key=None,
            progress=progress,
            retry_at=None,
            last_error=error or {},
            observed_at=self.clock(),
        )
        return progress

    def reconcile(self, world) -> AdapterSupervisorResult:
        adapters = {str(adapter.pk): adapter for adapter in ManagedAudioAdapter.objects.all()}
        started: list[str] = []
        stopped: list[str] = []
        restarted: list[str] = []
        ready: list[str] = []
        failed: list[str] = []

        for identity, owned in tuple(self._owned.items()):
            adapter = adapters.get(identity)
            desired_digest = (
                adapter_configuration_digest(
                    adapter.kind,
                    adapter.configuration,
                    adapter.restart_generation,
                )
                if adapter is not None and adapter.enabled
                else None
            )
            if desired_digest == owned.digest:
                continue
            if adapter is not None:
                self._stop(adapter, owned)
                (restarted if adapter.enabled else stopped).append(identity)
            else:
                owned.runtime.stop()
                stopped.append(identity)
            self._owned.pop(identity, None)
            self._attempts.pop(identity, None)

        now = self.clock()
        for identity, adapter in adapters.items():
            state, _ = ManagedAudioAdapterRuntimeState.objects.get_or_create(adapter=adapter)
            if not adapter.enabled:
                if identity not in self._owned and state.lifecycle != AudioAdapterLifecycle.STOPPED:
                    self._write_state(
                        adapter,
                        lifecycle=AudioAdapterLifecycle.STOPPED,
                        health=AudioAdapterHealth.UNKNOWN,
                        process_id=None,
                        runtime_key=None,
                        retry_at=None,
                        observed_at=now,
                    )
                continue
            owned = self._owned.get(identity)
            if owned is not None:
                observation = owned.runtime.poll()
                if not observation.running:
                    self._owned.pop(identity, None)
                    self._backoff(adapter, observation.error)
                    failed.append(identity)
                    continue
                expected = adapter_node_name(adapter.pk)
                candidate = self._runtime_candidate(world, identity, expected)
                lifecycle = (
                    AudioAdapterLifecycle.READY
                    if candidate is not None
                    else AudioAdapterLifecycle.STARTING
                )
                self._write_state(
                    adapter,
                    lifecycle=lifecycle,
                    health=(
                        AudioAdapterHealth.HEALTHY
                        if candidate is not None
                        else AudioAdapterHealth.UNKNOWN
                    ),
                    process_id=observation.process_id,
                    runtime_key=(candidate.runtime_key if candidate is not None else None),
                    progress=observation.progress,
                    retry_at=None,
                    last_error={},
                    observed_at=now,
                )
                if candidate is not None:
                    self._attempts.pop(identity, None)
                    ready.append(identity)
                continue
            if state.retry_at is not None and state.retry_at > now:
                continue
            try:
                configuration = normalize_adapter_configuration(
                    adapter.kind,
                    adapter.configuration,
                    media_root=self.driver.media_root,
                )
                runtime = self.driver.start(
                    adapter.pk,
                    adapter.name,
                    adapter.kind,
                    configuration,
                )
                observation = runtime.poll()
                generation = state.runtime_generation + 1
                digest = adapter_configuration_digest(
                    adapter.kind,
                    adapter.configuration,
                    adapter.restart_generation,
                )
                self._owned[identity] = _OwnedRuntime(runtime, digest, generation)
                self._write_state(
                    adapter,
                    lifecycle=AudioAdapterLifecycle.STARTING,
                    health=AudioAdapterHealth.UNKNOWN,
                    process_id=observation.process_id,
                    runtime_generation=generation,
                    configuration_digest=digest,
                    expected_node_name=adapter_node_name(adapter.pk),
                    runtime_key=None,
                    progress=observation.progress,
                    retry_at=None,
                    last_error={},
                    started_at=now,
                    observed_at=now,
                )
                started.append(identity)
            except Exception as error:
                self._backoff(
                    adapter,
                    {
                        "code": "adapter-start-failed",
                        "type": type(error).__name__,
                        "detail": str(error),
                    },
                )
                failed.append(identity)
        return AdapterSupervisorResult(
            tuple(sorted(started)),
            tuple(sorted(stopped)),
            tuple(sorted(restarted)),
            tuple(sorted(ready)),
            tuple(sorted(failed)),
        )

    def shutdown(self) -> None:
        adapters = {str(adapter.pk): adapter for adapter in ManagedAudioAdapter.objects.all()}
        for identity, owned in tuple(self._owned.items()):
            adapter = adapters.get(identity)
            if adapter is not None:
                self._stop(adapter, owned)
            else:
                owned.runtime.stop()
            self._owned.pop(identity, None)
        self._attempts.clear()
