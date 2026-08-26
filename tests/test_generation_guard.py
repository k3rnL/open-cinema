import pytest

from core.orchestration.generation_guard import (
    GenerationInput,
    GenerationPhase,
    GenerationStatus,
    OrchestrationGenerationCoordinator,
    StaleGenerationAbort,
)


def _inputs(*, desired=1, world=1, sequence=10):
    return GenerationInput(
        desired_state_version=desired,
        desired_digest=f"desired:{desired}",
        world_version=world,
        runtime_generation=3,
        runtime_sequence=sequence,
    )


def test_identical_inputs_do_not_schedule_duplicate_generation() -> None:
    coordinator = OrchestrationGenerationCoordinator()

    first = coordinator.schedule("graph:main", _inputs(), cause="startup")
    duplicate = coordinator.schedule("graph:main", _inputs(), cause="duplicate-event")

    assert first.scheduled is True
    assert duplicate.scheduled is False
    assert duplicate.generation.generation == 1


@pytest.mark.parametrize(
    "phase",
    (GenerationPhase.RESOLVING, GenerationPhase.APPLYING_SAFE),
)
def test_changed_observation_schedules_superseding_generation_during_work(phase) -> None:
    coordinator = OrchestrationGenerationCoordinator()
    first = coordinator.schedule("graph:main", _inputs(), cause="startup").generation
    coordinator.set_phase(first, phase)

    second = coordinator.schedule(
        "graph:main",
        _inputs(world=2, sequence=11),
        cause="runtime_changed",
    )

    superseded = coordinator.get("graph:main", 1)
    assert second.scheduled is True
    assert second.superseded_generation == 1
    assert second.generation.generation == 2
    assert superseded.status is GenerationStatus.SUPERSEDED
    assert superseded.superseded_by == 2


def test_superseded_resolution_may_record_plan_but_cannot_execute_it() -> None:
    coordinator = OrchestrationGenerationCoordinator()
    first = coordinator.schedule("graph:main", _inputs(), cause="startup").generation
    coordinator.set_phase(first, GenerationPhase.RESOLVING)
    coordinator.schedule(
        "graph:main",
        _inputs(world=2, sequence=11),
        cause="runtime_changed",
    )

    resolved = coordinator.record_resolved_plan(first, "plan:old")

    assert resolved.resolved_plan_digest == "plan:old"
    assert coordinator.may_execute_actions(resolved) is False
    with pytest.raises(StaleGenerationAbort) as caught:
        coordinator.require_current_before_unsafe_mutation(
            resolved,
            operation="set-stream-target",
        )
    assert caught.value.generation.status is GenerationStatus.ABORTED
    assert caught.value.generation.superseded_by == 2


def test_last_second_precondition_change_schedules_successor_and_aborts() -> None:
    coordinator = OrchestrationGenerationCoordinator()
    first = coordinator.schedule("graph:main", _inputs(), cause="startup").generation

    with pytest.raises(StaleGenerationAbort):
        coordinator.require_current_before_unsafe_mutation(
            first,
            operation="create-managed-link",
            observed_inputs=_inputs(desired=2),
        )

    assert coordinator.current("graph:main").generation == 2
    assert coordinator.current("graph:main").inputs.desired_state_version == 2


def test_current_generation_can_cross_unsafe_fence_and_complete() -> None:
    coordinator = OrchestrationGenerationCoordinator()
    generation = coordinator.schedule(
        "graph:main",
        _inputs(),
        cause="startup",
    ).generation

    applying = coordinator.require_current_before_unsafe_mutation(
        generation,
        operation="set-stream-target",
        observed_inputs=_inputs(),
    )
    completed = coordinator.complete(applying)

    assert applying.phase is GenerationPhase.APPLYING_UNSAFE
    assert completed.status is GenerationStatus.COMPLETED
