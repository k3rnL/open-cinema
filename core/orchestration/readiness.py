from __future__ import annotations

from dataclasses import dataclass

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    GraphActivation,
    TransitionJournal,
    TransitionStatus,
)


@dataclass(frozen=True, slots=True)
class OrchestrationReadinessReport:
    ready: bool
    failures: tuple[str, ...]
    active_graphs: int
    converged_graphs: int
    unfinished_transitions: int
    pending_migrations: int

    def to_document(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "ready": self.ready,
            "failures": list(self.failures),
            "activeGraphs": self.active_graphs,
            "convergedGraphs": self.converged_graphs,
            "unfinishedTransitions": self.unfinished_transitions,
            "pendingMigrations": self.pending_migrations,
        }


def inspect_orchestration_readiness() -> OrchestrationReadinessReport:
    """Read only authoritative state needed by appliance readiness."""

    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        if cursor.fetchone() != (1,):
            raise RuntimeError("database readiness query returned an unexpected result")

    executor = MigrationExecutor(connection)
    pending_migrations = executor.migration_plan(executor.loader.graph.leaf_nodes())
    failures: list[str] = []
    if pending_migrations:
        failures.append(f"{len(pending_migrations)} database migration(s) are pending")

    activations = tuple(
        GraphActivation.objects.select_related("definition").order_by("definition_id")
    )
    states = {
        str(state.graph_definition_id): state
        for state in AppliedPlanState.objects.select_related("current_plan")
    }
    active_graphs = 0
    converged_graphs = 0
    for activation in activations:
        identity = str(activation.definition_id)
        state = states.get(identity)
        if state is not None and state.status == AppliedPlanStatus.APPLYING:
            failures.append(f"graph {identity} still has an applying plan state")
        if not activation.enabled:
            continue
        active_graphs += 1
        if state is None:
            failures.append(f"active graph {identity} has no applied plan state")
            continue
        if state.status != AppliedPlanStatus.CONVERGED:
            failures.append(
                f"active graph {identity} is {state.status}, not {AppliedPlanStatus.CONVERGED}"
            )
            continue
        if state.current_plan is None:
            failures.append(f"active graph {identity} has no current plan")
            continue
        if state.current_plan.desired_state_version != activation.desired_state_version:
            failures.append(
                f"active graph {identity} applied desired version "
                f"{state.current_plan.desired_state_version}, expected "
                f"{activation.desired_state_version}"
            )
            continue
        if state.last_error:
            failures.append(f"active graph {identity} retains a reconciliation error")
            continue
        converged_graphs += 1

    unfinished_statuses = (TransitionStatus.PENDING, TransitionStatus.RUNNING)
    unfinished_transitions = TransitionJournal.objects.filter(
        status__in=unfinished_statuses
    ).count()
    if unfinished_transitions:
        failures.append(
            f"{unfinished_transitions} transition journal(s) are unfinished"
        )

    return OrchestrationReadinessReport(
        ready=not failures,
        failures=tuple(failures),
        active_graphs=active_graphs,
        converged_graphs=converged_graphs,
        unfinished_transitions=unfinished_transitions,
        pending_migrations=len(pending_migrations),
    )
