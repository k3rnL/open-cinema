from dataclasses import replace

import pytest

from core.orchestration.runtime_world import InMemoryWorldStore
from core.orchestration.state_correlation import (
    StateCorrelationError,
    correlate_orchestration_state,
)
from tests.factories import (
    AppliedPlanStateFactory,
    GraphActivationFactory,
    ResolvedPlanFactory,
)
from tests.test_endpoint_inventory_mapping import _snapshot

pytestmark = pytest.mark.django_db


def _correlated_values():
    activation = GraphActivationFactory(desired_state_version=3)
    runtime = _snapshot(generation=3)
    world = InMemoryWorldStore().install_runtime_snapshot(runtime)
    plan = ResolvedPlanFactory(
        graph_definition=activation.definition,
        graph_revision=activation.revision,
        desired_state_version=activation.desired_state_version,
        world_generation=runtime.generation,
        world_sequence=runtime.sequence,
    )
    applied = AppliedPlanStateFactory(
        graph_definition=activation.definition,
        current_plan=plan,
        transition_generation=4,
        correlation_id=plan.correlation_id,
    )
    return activation, world, plan, applied


def test_all_orchestration_representations_are_correlated_explicitly() -> None:
    activation, world, plan, applied = _correlated_values()

    correlation = correlate_orchestration_state(
        activation=activation,
        resolution_world=world,
        resolved_plan=plan,
        applied_state=applied,
    )
    document = correlation.document

    assert document["desired"]["revisionId"] == str(activation.revision_id)
    assert document["desired"]["desiredStateVersion"] == 3
    assert document["resolutionWorld"] == {
        "worldVersion": 1,
        "runtimeGeneration": runtime_generation(world),
        "runtimeSequence": world.runtime.sequence,
    }
    assert document["resolvedPlan"]["digest"] == plan.plan_digest
    assert document["transition"]["generation"] == 4
    assert document["appliedPlan"]["id"] == str(plan.pk)
    assert document["runtime"]["worldVersion"] == 1
    assert document["state"] == {
        "appliedMatchesResolved": True,
        "newerRuntimeObserved": False,
        "converged": True,
    }
    assert len(correlation.digest) == 64


def runtime_generation(world):
    return world.runtime.generation


def test_new_runtime_snapshot_is_visible_without_relabeling_old_plan() -> None:
    activation, resolution_world, plan, applied = _correlated_values()
    store = InMemoryWorldStore()
    store.install_runtime_snapshot(resolution_world.runtime)
    latest = store.install_runtime_snapshot(
        replace(resolution_world.runtime, sequence=resolution_world.runtime.sequence + 1)
    )

    correlation = correlate_orchestration_state(
        activation=activation,
        resolution_world=resolution_world,
        resolved_plan=plan,
        applied_state=applied,
        latest_runtime_world=latest,
    )

    assert correlation.document["resolutionWorld"]["worldVersion"] == 1
    assert correlation.document["runtime"]["worldVersion"] == 2
    assert correlation.document["state"]["newerRuntimeObserved"] is True
    assert correlation.document["state"]["converged"] is False


@pytest.mark.parametrize(
    "change",
    (
        {"desired_state_version": 99},
        {"world_sequence": 99},
    ),
)
def test_mismatched_resolution_inputs_are_rejected(change) -> None:
    activation, world, plan, applied = _correlated_values()
    for field, value in change.items():
        setattr(plan, field, value)

    with pytest.raises(StateCorrelationError):
        correlate_orchestration_state(
            activation=activation,
            resolution_world=world,
            resolved_plan=plan,
            applied_state=applied,
        )
