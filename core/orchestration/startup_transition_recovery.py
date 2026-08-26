from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    OrchestrationEvent,
    OrchestrationEventSeverity,
    TransitionJournal,
    TransitionStatus,
)

from .runtime_world import OrchestratorWorldSnapshot
from .transition_journal import TransitionJournalStore
from .wireplumber_driver import OPEN_CINEMA_LINK_OWNER


@dataclass(frozen=True, slots=True)
class StartupTransitionRecoveryResult:
    journal_id: str
    graph_definition_id: str
    generation: int
    status: str
    remaining_owned_link_ids: tuple[int, ...]


class StartupTransitionRecovery:
    """Close journals interrupted across a controller/runtime connection boundary."""

    def __init__(self, store: TransitionJournalStore | None = None) -> None:
        self.store = store or TransitionJournalStore()

    def recover(
        self,
        world: OrchestratorWorldSnapshot,
    ) -> tuple[StartupTransitionRecoveryResult, ...]:
        if not isinstance(world, OrchestratorWorldSnapshot):
            raise TypeError("world must be an OrchestratorWorldSnapshot")
        results = []
        for directive in self.store.recover_incomplete():
            journal = TransitionJournal.objects.get(pk=directive.journal_id)
            prefix = f"{directive.graph_definition_id}:"
            remaining = tuple(
                sorted(
                    link.id
                    for link in world.runtime.links
                    if link.owner == OPEN_CINEMA_LINK_OWNER
                    and isinstance(link.desired_id, str)
                    and link.desired_id.startswith(prefix)
                )
            )
            safe = not remaining
            terminal_status = (
                TransitionStatus.CANCELLED if safe else TransitionStatus.FAILED
            )
            summary = {
                "outcome": (
                    "interrupted-controller-boundary-clean"
                    if safe
                    else "interrupted-owned-resources-remain"
                ),
                "reason": directive.reason,
                "recoveryMode": directive.mode.value,
                "freshRuntimeGeneration": world.runtime.generation,
                "freshRuntimeSequence": world.runtime.sequence,
                "remainingOwnedLinkIds": list(remaining),
            }
            recovered = self.store.finish_recovery(
                journal,
                status=terminal_status,
                summary=summary,
            )
            with transaction.atomic():
                state = (
                    AppliedPlanState.objects.select_for_update()
                    .filter(graph_definition_id=directive.graph_definition_id)
                    .first()
                )
                if state is not None and state.status == AppliedPlanStatus.APPLYING:
                    state.status = (
                        AppliedPlanStatus.DEGRADED if safe else AppliedPlanStatus.FAILED
                    )
                    state.last_error = {
                        "code": (
                            "transition-interrupted-clean"
                            if safe
                            else "transition-interrupted-owned-resources-remain"
                        ),
                        "message": (
                            "The previous controller stopped mid-transition; a fresh "
                            "runtime snapshot verified that its connection-owned links "
                            "were removed."
                            if safe
                            else "The previous controller stopped mid-transition and "
                            "owned links remain in the fresh runtime snapshot."
                        ),
                        "journalId": str(recovered.pk),
                        "remainingOwnedLinkIds": list(remaining),
                    }
                    state.save(update_fields=("status", "last_error", "updated_at"))
                OrchestrationEvent.objects.create(
                    correlation_id=recovered.correlation_id,
                    graph_definition_id=directive.graph_definition_id,
                    event_type="transition-startup-recovery",
                    severity=(
                        OrchestrationEventSeverity.WARNING
                        if safe
                        else OrchestrationEventSeverity.ERROR
                    ),
                    payload={
                        "journalId": str(recovered.pk),
                        "generation": recovered.generation,
                        "status": recovered.status,
                        **summary,
                    },
                )
            results.append(
                StartupTransitionRecoveryResult(
                    journal_id=str(recovered.pk),
                    graph_definition_id=str(directive.graph_definition_id),
                    generation=recovered.generation,
                    status=recovered.status,
                    remaining_owned_link_ids=remaining,
                )
            )
        return tuple(results)
