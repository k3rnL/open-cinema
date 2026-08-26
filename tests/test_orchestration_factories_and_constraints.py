import pytest
from django.db import IntegrityError, connection, transaction

from api.models import AppliedPlanState, DiagnosticRecord, RuntimeProjection
from tests.factories import (
    AppliedPlanStateFactory,
    DiagnosticRecordFactory,
    GraphActivationFactory,
    GraphDefinitionFactory,
    GraphRevisionFactory,
    LogicalEndpointFactory,
    ManualOverrideFactory,
    OrchestrationEventFactory,
    ResolvedPlanFactory,
    RuntimeProjectionFactory,
    TransitionJournalFactory,
)


pytestmark = pytest.mark.django_db


def test_orchestration_factories_create_every_persisted_resource() -> None:
    resources = (
        GraphDefinitionFactory(),
        GraphRevisionFactory(),
        GraphActivationFactory(),
        LogicalEndpointFactory(),
        ManualOverrideFactory(),
        ResolvedPlanFactory(),
        AppliedPlanStateFactory(),
        TransitionJournalFactory(),
        OrchestrationEventFactory(),
        DiagnosticRecordFactory(),
        RuntimeProjectionFactory(),
    )

    assert all(resource.pk is not None for resource in resources)
    activation = resources[2]
    assert activation.revision.definition_id == activation.definition_id
    applied = resources[6]
    assert applied.current_plan.graph_definition_id == applied.graph_definition_id


def test_named_database_constraints_are_installed() -> None:
    expected_by_table = {
        "api_graphdefinition": {
            "api_graph_definition_owner_name_unique",
            "api_graph_definition_name_nonempty",
        },
        "api_graphrevision": {
            "api_graph_revision_number_unique",
            "api_graph_revision_published_timestamp",
            "api_graph_revision_digest_nonempty",
            "api_graph_revision_update_version_positive",
        },
        "api_graphactivation": {"api_graph_activation_version_positive"},
        "api_logicalendpoint": {
            "api_logical_endpoint_owner_name_unique",
            "api_logical_endpoint_version_positive",
            "api_logical_endpoint_name_nonempty",
        },
        "api_manualoverride": {
            "api_manual_override_expiry_after_start",
            "api_manual_override_cancellation_pair",
            "api_manual_override_scope_nonempty",
        },
        "api_resolvedplan": {
            "api_resolved_plan_desired_positive",
            "api_resolved_plan_digest_nonempty",
        },
        "api_appliedplanstate": {"api_applied_plan_distinct_rollback"},
        "api_transitionjournal": {
            "api_transition_graph_generation_unique",
            "api_transition_generation_positive",
        },
        "api_orchestrationevent": {"api_orchestration_event_type_nonempty"},
        "api_diagnosticrecord": {"api_diagnostic_category_nonempty"},
        "api_runtimeprojection": {
            "api_runtime_projection_current_unique",
            "api_runtime_projection_generation_positive",
            "api_runtime_projection_subject_nonempty",
        },
    }

    with connection.cursor() as cursor:
        for table, expected in expected_by_table.items():
            installed = connection.introspection.get_constraints(cursor, table)
            assert expected <= installed.keys()


def test_database_rejects_unsafe_rollback_and_projection_duplicates() -> None:
    plan = ResolvedPlanFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        AppliedPlanState.objects.create(
            graph_definition=plan.graph_definition,
            current_plan=plan,
            previous_plan=plan,
        )

    RuntimeProjectionFactory(
        projection_type="endpoint",
        subject_key="unique-current",
        is_current=True,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimeProjectionFactory(
            projection_type="endpoint",
            subject_key="unique-current",
            is_current=True,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        DiagnosticRecord.objects.create(category="", payload={})
