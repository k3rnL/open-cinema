from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock


class GenerationStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ABORTED = "aborted"
    COMPLETED = "completed"


class GenerationPhase(StrEnum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    PLANNING = "planning"
    APPLYING_SAFE = "applying-safe"
    APPLYING_UNSAFE = "applying-unsafe"
    VERIFYING = "verifying"


@dataclass(frozen=True, slots=True)
class GenerationInput:
    desired_state_version: int
    desired_digest: str
    world_version: int
    runtime_generation: int
    runtime_sequence: int

    def __post_init__(self) -> None:
        for name in (
            "desired_state_version",
            "world_version",
            "runtime_generation",
            "runtime_sequence",
        ):
            value = getattr(self, name)
            minimum = 0 if name == "runtime_sequence" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if not isinstance(self.desired_digest, str) or not self.desired_digest:
            raise ValueError("desired_digest must be a non-empty string")


@dataclass(frozen=True, slots=True)
class OrchestrationGeneration:
    graph_scope: str
    generation: int
    inputs: GenerationInput
    cause: str
    status: GenerationStatus = GenerationStatus.ACTIVE
    phase: GenerationPhase = GenerationPhase.QUEUED
    superseded_by: int | None = None
    resolved_plan_digest: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationScheduleResult:
    generation: OrchestrationGeneration
    scheduled: bool
    superseded_generation: int | None


class StaleGenerationAbort(RuntimeError):
    def __init__(
        self,
        generation: OrchestrationGeneration,
        *,
        operation: str,
    ) -> None:
        self.generation = generation
        self.operation = operation
        super().__init__(
            f"generation {generation.generation} for {generation.graph_scope!r} "
            f"is {generation.status.value} before unsafe operation {operation!r}; "
            f"superseding generation is {generation.superseded_by}"
        )


class OrchestrationGenerationCoordinator:
    """Fence unsafe work while allowing superseded pure resolution to finish."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generations: dict[tuple[str, int], OrchestrationGeneration] = {}
        self._current: dict[str, int] = {}

    @staticmethod
    def _scope(value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("graph_scope must be a non-empty string")
        return value

    def current(self, graph_scope: str) -> OrchestrationGeneration | None:
        graph_scope = self._scope(graph_scope)
        with self._lock:
            generation = self._current.get(graph_scope)
            return self._generations[(graph_scope, generation)] if generation is not None else None

    def get(self, graph_scope: str, generation: int) -> OrchestrationGeneration:
        graph_scope = self._scope(graph_scope)
        with self._lock:
            try:
                return self._generations[(graph_scope, generation)]
            except KeyError as error:
                raise KeyError(
                    f"unknown orchestration generation {graph_scope}:{generation}"
                ) from error

    def schedule(
        self,
        graph_scope: str,
        inputs: GenerationInput,
        *,
        cause: str,
    ) -> GenerationScheduleResult:
        graph_scope = self._scope(graph_scope)
        if not isinstance(inputs, GenerationInput):
            raise TypeError("inputs must be a GenerationInput")
        if not isinstance(cause, str) or not cause:
            raise ValueError("cause must be a non-empty string")
        with self._lock:
            current_number = self._current.get(graph_scope)
            current = (
                self._generations[(graph_scope, current_number)]
                if current_number is not None
                else None
            )
            if (
                current is not None
                and current.inputs == inputs
                and current.status is GenerationStatus.ACTIVE
            ):
                return GenerationScheduleResult(current, False, None)
            next_number = (current_number or 0) + 1
            superseded = None
            if current is not None and current.status is GenerationStatus.ACTIVE:
                superseded = current.generation
                self._generations[(graph_scope, current.generation)] = replace(
                    current,
                    status=GenerationStatus.SUPERSEDED,
                    superseded_by=next_number,
                )
            generation = OrchestrationGeneration(
                graph_scope=graph_scope,
                generation=next_number,
                inputs=inputs,
                cause=cause,
            )
            self._generations[(graph_scope, next_number)] = generation
            self._current[graph_scope] = next_number
            return GenerationScheduleResult(generation, True, superseded)

    def set_phase(
        self,
        generation: OrchestrationGeneration,
        phase: GenerationPhase,
    ) -> OrchestrationGeneration:
        if not isinstance(generation, OrchestrationGeneration):
            raise TypeError("generation must be an OrchestrationGeneration")
        phase = GenerationPhase(phase)
        with self._lock:
            actual = self.get(generation.graph_scope, generation.generation)
            if actual.status is not GenerationStatus.ACTIVE:
                return actual
            updated = replace(actual, phase=phase)
            self._generations[(actual.graph_scope, actual.generation)] = updated
            return updated

    def record_resolved_plan(
        self,
        generation: OrchestrationGeneration,
        plan_digest: str,
    ) -> OrchestrationGeneration:
        if not isinstance(plan_digest, str) or not plan_digest:
            raise ValueError("plan_digest must be a non-empty string")
        with self._lock:
            actual = self.get(generation.graph_scope, generation.generation)
            updated = replace(actual, resolved_plan_digest=plan_digest)
            self._generations[(actual.graph_scope, actual.generation)] = updated
            return updated

    def require_current_before_unsafe_mutation(
        self,
        generation: OrchestrationGeneration,
        *,
        operation: str,
        observed_inputs: GenerationInput | None = None,
        changed_cause: str = "inputs_changed_before_mutation",
    ) -> OrchestrationGeneration:
        if not isinstance(generation, OrchestrationGeneration):
            raise TypeError("generation must be an OrchestrationGeneration")
        if not isinstance(operation, str) or not operation:
            raise ValueError("operation must be a non-empty string")
        with self._lock:
            actual = self.get(generation.graph_scope, generation.generation)
            if observed_inputs is not None and observed_inputs != actual.inputs:
                self.schedule(
                    actual.graph_scope,
                    observed_inputs,
                    cause=changed_cause,
                )
                actual = self.get(actual.graph_scope, actual.generation)
            current = self.current(actual.graph_scope)
            if (
                actual.status is not GenerationStatus.ACTIVE
                or current is None
                or current.generation != actual.generation
            ):
                aborted = replace(actual, status=GenerationStatus.ABORTED)
                self._generations[(actual.graph_scope, actual.generation)] = aborted
                raise StaleGenerationAbort(aborted, operation=operation)
            applying = replace(actual, phase=GenerationPhase.APPLYING_UNSAFE)
            self._generations[(actual.graph_scope, actual.generation)] = applying
            return applying

    def may_execute_actions(self, generation: OrchestrationGeneration) -> bool:
        with self._lock:
            actual = self.get(generation.graph_scope, generation.generation)
            current = self.current(actual.graph_scope)
            return bool(
                actual.status is GenerationStatus.ACTIVE
                and current is not None
                and current.generation == actual.generation
            )

    def complete(
        self,
        generation: OrchestrationGeneration,
    ) -> OrchestrationGeneration:
        with self._lock:
            actual = self.get(generation.graph_scope, generation.generation)
            if not self.may_execute_actions(actual):
                raise StaleGenerationAbort(actual, operation="complete_generation")
            completed = replace(actual, status=GenerationStatus.COMPLETED)
            self._generations[(actual.graph_scope, actual.generation)] = completed
            return completed
