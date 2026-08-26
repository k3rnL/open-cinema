import uuid

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    DiagnosticRecord,
    GraphActivation,
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
    LogicalEndpoint,
    LogicalEndpointDirection,
    ManualOverride,
    ManualOverrideScope,
    OrchestrationEvent,
    ResolvedPlan,
    ResolvedPlanStatus,
    RuntimeProjection,
    TransitionJournal,
    TransitionPhase,
    TransitionStatus,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda number: f"orchestration-user-{number}")


class GraphDefinitionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GraphDefinition

    name = factory.Sequence(lambda number: f"Audio graph {number}")
    owner = factory.SubFactory(UserFactory)
    labels = factory.LazyFunction(dict)


class GraphRevisionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GraphRevision

    definition = factory.SubFactory(GraphDefinitionFactory)
    revision_number = factory.Sequence(lambda number: number + 1)
    state = GraphRevisionState.PUBLISHED
    author = factory.LazyAttribute(lambda revision: revision.definition.owner)
    content = factory.LazyFunction(lambda: {"nodes": [], "edges": []})
    validation_summary = factory.LazyFunction(dict)
    published_at = factory.LazyFunction(timezone.now)


class GraphActivationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GraphActivation

    revision = factory.SubFactory(GraphRevisionFactory)
    definition = factory.LazyAttribute(lambda activation: activation.revision.definition)
    parameter_bindings = factory.LazyFunction(dict)
    scene_bindings = factory.LazyFunction(dict)
    activated_at = factory.LazyFunction(timezone.now)


class LogicalEndpointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LogicalEndpoint

    name = factory.Sequence(lambda number: f"Main speakers {number}")
    owner = factory.SubFactory(UserFactory)
    direction = LogicalEndpointDirection.OUTPUT
    selector = factory.LazyFunction(lambda: {"mediaClass": "Audio/Sink"})


class ManualOverrideFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ManualOverride

    scope_type = ManualOverrideScope.ROUTE
    scope_id = factory.Sequence(lambda number: f"route-{number}")
    value = "main-speakers"
    creator = factory.SubFactory(UserFactory)
    reason = "Factory-created explicit user choice"


class ResolvedPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ResolvedPlan

    graph_revision = factory.SubFactory(GraphRevisionFactory)
    graph_definition = factory.LazyAttribute(
        lambda plan: plan.graph_revision.definition
    )
    desired_state_version = factory.Sequence(lambda number: number + 1)
    world_generation = 1
    world_sequence = factory.Sequence(lambda number: number)
    status = ResolvedPlanStatus.RESOLVED
    document = factory.LazyFunction(lambda: {"selectedPaths": []})
    explanation = factory.LazyFunction(dict)


class AppliedPlanStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AppliedPlanState

    current_plan = factory.SubFactory(ResolvedPlanFactory)
    graph_definition = factory.LazyAttribute(
        lambda state: state.current_plan.graph_definition
    )
    status = AppliedPlanStatus.CONVERGED
    correlation_id = factory.LazyAttribute(lambda state: state.current_plan.correlation_id)


class TransitionJournalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TransitionJournal

    plan = factory.SubFactory(ResolvedPlanFactory)
    graph_definition = factory.LazyAttribute(lambda journal: journal.plan.graph_definition)
    generation = factory.Sequence(lambda number: number + 1)
    correlation_id = factory.LazyAttribute(lambda journal: journal.plan.correlation_id)
    phase = TransitionPhase.COMPLETED
    status = TransitionStatus.SUCCEEDED
    entries = factory.LazyFunction(list)
    completed_at = factory.LazyFunction(timezone.now)


class OrchestrationEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrchestrationEvent

    correlation_id = factory.LazyFunction(uuid.uuid4)
    graph_definition = factory.SubFactory(GraphDefinitionFactory)
    event_type = "resolution.completed"
    payload = factory.LazyFunction(dict)


class DiagnosticRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DiagnosticRecord

    correlation_id = factory.LazyFunction(uuid.uuid4)
    category = "wireplumber.event"
    payload = factory.LazyFunction(dict)


class RuntimeProjectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RuntimeProjection

    projection_type = "endpoint"
    subject_key = factory.Sequence(lambda number: f"endpoint-{number}")
    world_generation = 1
    world_sequence = factory.Sequence(lambda number: number)
    payload = factory.LazyFunction(dict)
    observed_at = factory.LazyFunction(timezone.now)
