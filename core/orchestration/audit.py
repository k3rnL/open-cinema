from __future__ import annotations

from django.conf import settings
from django.db import transaction

from api.models.orchestration import OrchestrationEvent


def record_orchestration_event(
    *,
    correlation_id,
    event_type: str,
    payload: dict[str, object] | None = None,
    severity="info",
    graph_definition=None,
) -> OrchestrationEvent:
    """Append one audit event and trim the global stream to its hard bound."""

    limit = settings.AUDIO_ORCHESTRATION_AUDIT_MAX_RECORDS
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("AUDIO_ORCHESTRATION_AUDIT_MAX_RECORDS must be positive")
    with transaction.atomic():
        event = OrchestrationEvent(
            correlation_id=correlation_id,
            graph_definition=graph_definition,
            event_type=event_type,
            severity=severity,
            payload={} if payload is None else payload,
        )
        event.full_clean()
        event.save(force_insert=True)
        excess = OrchestrationEvent.objects.count() - limit
        if excess > 0:
            expired = list(
                OrchestrationEvent.objects.order_by("sequence").values_list(
                    "sequence",
                    flat=True,
                )[:excess]
            )
            OrchestrationEvent.objects.filter(sequence__in=expired).delete()
        return event
