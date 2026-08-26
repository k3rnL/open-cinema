from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings

from api.models import (
    AppliedPlanState,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    ResolvedPlan,
    ResolvedPlanMode,
    ShadowResolutionComparison,
    TransitionJournal,
    TransitionStatus,
)
from core.orchestration.activations import activate_graph
from core.orchestration.feature_flags import AudioOrchestrationFeatureFlags
from core.orchestration.resolver_inputs import (
    ResolverActivationInput,
    ResolverGraphRevisionInput,
)
from core.orchestration.shadow_resolution import (
    ShadowGraphResolver,
    ShadowResolutionDisabled,
    persist_shadow_resolution,
)
from core.orchestration.runtime_world import InMemoryWorldStore
from tests.test_endpoint_inventory_mapping import _snapshot
from tests.test_resolver_pipeline import _registry, _resolver_inputs

pytestmark = pytest.mark.django_db
SHADOW_FLAGS = AudioOrchestrationFeatureFlags(shadow_resolution=True)


def _database_inputs():
    inputs = _resolver_inputs()
    owner = get_user_model().objects.create_user(username="shadow-resolver")
    definition = GraphDefinition.objects.create(name="Shadow graph", owner=owner)
    revision = GraphRevision.objects.create(
        definition=definition,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=inputs.graph.document.to_dict(),
    )
    graph = ResolverGraphRevisionInput(
        definition_id=str(definition.pk),
        revision_id=str(revision.pk),
        revision_number=revision.revision_number,
        schema_version=revision.schema_version,
        content_digest=revision.content_digest,
        document=revision.content,
    )
    activation = ResolverActivationInput(
        activation_id="activation:shadow",
        definition_id=str(definition.pk),
        revision_id=str(revision.pk),
        desired_state_version=inputs.activation.desired_state_version,
        parameter_bindings=inputs.activation.parameter_bindings,
        scene_bindings=inputs.activation.scene_bindings,
    )
    return replace(inputs, graph=graph, activation=activation), definition, revision


def _live_copy(plan: ResolvedPlan) -> ResolvedPlan:
    return ResolvedPlan.objects.create(
        schema_version=plan.schema_version,
        graph_definition=plan.graph_definition,
        graph_revision=plan.graph_revision,
        desired_state_version=plan.desired_state_version,
        world_generation=plan.world_generation,
        world_sequence=plan.world_sequence,
        resolution_mode=ResolvedPlanMode.LIVE,
        status=plan.status,
        document=plan.document,
        explanation=plan.explanation,
    )


def test_shadow_resolution_persists_plan_and_comparison_without_driver_actions() -> None:
    inputs, definition, revision = _database_inputs()

    outcome = persist_shadow_resolution(
        inputs,
        graph_definition=definition,
        graph_revision=revision,
        registry=_registry(),
        flags=SHADOW_FLAGS,
    )

    plan = ResolvedPlan.objects.get(pk=outcome.shadow_plan_id)
    comparison = ShadowResolutionComparison.objects.get(pk=outcome.comparison_id)
    assert plan.resolution_mode == ResolvedPlanMode.SHADOW
    assert plan.plan_digest == outcome.plan_digest
    assert comparison.shadow_plan == plan
    assert comparison.baseline_plan is None
    assert comparison.equivalent is False
    assert comparison.differences["baselinePresent"] is False
    assert outcome.driver_actions == ()
    assert not AppliedPlanState.objects.exists()
    assert not TransitionJournal.objects.exists()

    applied = AppliedPlanState(
        graph_definition=definition,
        current_plan=plan,
    )
    with pytest.raises(ValidationError, match="shadow plan"):
        applied.full_clean()
    transition = TransitionJournal(
        graph_definition=definition,
        plan=plan,
        generation=1,
        correlation_id=plan.correlation_id,
        status=TransitionStatus.PENDING,
    )
    with pytest.raises(ValidationError, match="shadow plan"):
        transition.full_clean()


def test_identical_live_baseline_compares_equivalent() -> None:
    inputs, definition, revision = _database_inputs()
    first = persist_shadow_resolution(
        inputs,
        graph_definition=definition,
        graph_revision=revision,
        registry=_registry(),
        flags=SHADOW_FLAGS,
    )
    shadow = ResolvedPlan.objects.get(pk=first.shadow_plan_id)
    baseline = _live_copy(shadow)

    outcome = persist_shadow_resolution(
        inputs,
        graph_definition=definition,
        graph_revision=revision,
        baseline_plan=baseline,
        registry=_registry(),
        flags=SHADOW_FLAGS,
    )

    assert outcome.equivalent is True
    assert outcome.baseline_plan_id == baseline.pk
    assert outcome.differences["selectedEdgeIds"] == {"added": (), "removed": ()}
    assert outcome.driver_actions == ()


def test_changed_shadow_route_records_structured_difference() -> None:
    inputs, definition, revision = _database_inputs()
    first = persist_shadow_resolution(
        inputs,
        graph_definition=definition,
        graph_revision=revision,
        registry=_registry(),
        flags=SHADOW_FLAGS,
    )
    baseline = _live_copy(ResolvedPlan.objects.get(pk=first.shadow_plan_id))
    changed_activation = replace(
        inputs.activation,
        scene_bindings={"cinema": False},
        desired_state_version=inputs.activation.desired_state_version + 1,
    )
    changed = replace(inputs, activation=changed_activation)

    outcome = persist_shadow_resolution(
        changed,
        graph_definition=definition,
        graph_revision=revision,
        baseline_plan=baseline,
        registry=_registry(),
        flags=SHADOW_FLAGS,
    )

    assert outcome.equivalent is False
    assert outcome.differences["selectedEdgeIds"] == {
        "added": (),
        "removed": ("edge:in", "edge:out"),
    }
    assert outcome.driver_actions == ()


def test_disabled_shadow_mode_persists_nothing() -> None:
    inputs, definition, revision = _database_inputs()

    with pytest.raises(ShadowResolutionDisabled, match="disabled"):
        persist_shadow_resolution(
            inputs,
            graph_definition=definition,
            graph_revision=revision,
            registry=_registry(),
            flags=AudioOrchestrationFeatureFlags(),
        )

    assert not ResolvedPlan.objects.exists()
    assert not ShadowResolutionComparison.objects.exists()


@override_settings(
    AUDIO_ORCHESTRATION_FEATURES={
        "orchestration_api": True,
        "runtime_observation": True,
        "shadow_resolution": True,
        "processor_management": False,
        "live_reconciliation": False,
    }
)
def test_shadow_graph_resolver_builds_database_context_and_selects_live_baseline() -> None:
    _inputs, definition, revision = _database_inputs()
    activate_graph(definition=definition, revision=revision, expected_version=0)
    world = InMemoryWorldStore().install_runtime_snapshot(_snapshot())
    resolver = ShadowGraphResolver(registry=_registry())

    first = resolver.resolve(str(definition.pk), world)
    baseline = _live_copy(ResolvedPlan.objects.get(pk=first.shadow_plan_id))
    second = resolver.resolve(str(definition.pk), world)

    assert first.baseline_plan_id is None
    assert second.baseline_plan_id == baseline.pk
    assert second.driver_actions == ()
    assert ResolvedPlan.objects.filter(resolution_mode=ResolvedPlanMode.SHADOW).count() == 2
    assert ShadowResolutionComparison.objects.count() == 2
    assert not AppliedPlanState.objects.exists()
    assert not TransitionJournal.objects.exists()
