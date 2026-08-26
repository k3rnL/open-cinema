from __future__ import annotations

import json
import time

from django.db.models import Q
from django.http import StreamingHttpResponse
from rest_framework import status

from api.models import GraphDefinition, OrchestrationEvent, RuntimeProjection

from .base import AudioAPIProblem, AudioV1APIView, parse_boolean
from .representations import event_document, projection_document

_EVENT_KINDS = {"runtime", "plan", "transition", "endpoint", "processor", "health"}


def _kind(event_type: str) -> str:
    lowered = event_type.lower()
    if "reconciliation" in lowered:
        return "transition"
    for kind in ("transition", "endpoint", "processor", "health", "plan"):
        if kind in lowered:
            return kind
    return "runtime"


def _sse(*, event: str, data: object, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    encoded = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    lines.extend(f"data: {line}" for line in encoded.splitlines() or ("",))
    return "\n".join(lines) + "\n\n"


def _events_for(request):
    queryset = OrchestrationEvent.objects.select_related("graph_definition")
    if not (request.user.is_staff or request.user.is_superuser):
        queryset = queryset.filter(
            Q(graph_definition__owner=request.user) | Q(graph_definition__isnull=True)
        )
    graph_id = request.query_params.get("graphId")
    if graph_id:
        GraphDefinition.objects.visible_to(request.user).get(pk=graph_id)
        queryset = queryset.filter(graph_definition_id=graph_id)
    return queryset


def _snapshot(request) -> dict[str, object]:
    admin = bool(request.user.is_staff or request.user.is_superuser)
    projections = RuntimeProjection.objects.filter(is_current=True).order_by(
        "projection_type", "subject_key"
    )
    latest = projections.order_by("-world_generation", "-world_sequence").first()
    return {
        "schemaVersion": 1,
        "reason": "event-gap",
        "replaceLocalState": True,
        "worldGeneration": latest.world_generation if latest else None,
        "worldSequence": latest.world_sequence if latest else None,
        "runtimeAvailable": latest is not None,
        "projections": [projection_document(item, admin=admin) for item in projections],
    }


class OrchestrationEventStreamView(AudioV1APIView):
    def get(self, request):
        raw_cursor = request.headers.get("Last-Event-ID")
        cursor_was_supplied = raw_cursor is not None
        if raw_cursor is None:
            raw_cursor = request.query_params.get("after", "0")
            cursor_was_supplied = "after" in request.query_params
        try:
            cursor = int(raw_cursor)
        except (TypeError, ValueError) as error:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "invalid-event-cursor",
                "Invalid event cursor",
                "Last-Event-ID and after must be non-negative event sequences.",
            ) from error
        if cursor < 0:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "invalid-event-cursor",
                "Invalid event cursor",
                "The event cursor must not be negative.",
            )
        requested_kinds = {
            item.strip()
            for item in request.query_params.get("types", "").split(",")
            if item.strip()
        }
        unknown = requested_kinds - _EVENT_KINDS
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "invalid-event-filter",
                "Invalid event filter",
                f"Unknown event kinds: {', '.join(sorted(unknown))}.",
            )
        follow = parse_boolean(
            request.query_params.get("follow", "true"),
            field="follow",
        )
        queryset = _events_for(request)
        oldest = queryset.order_by("sequence").values_list("sequence", flat=True).first()
        newest = queryset.order_by("-sequence").values_list("sequence", flat=True).first()
        gap = bool(cursor_was_supplied and oldest is not None and cursor < oldest - 1)
        admin = bool(request.user.is_staff or request.user.is_superuser)

        def stream():
            nonlocal cursor
            yield "retry: 2000\n\n"
            if gap:
                cursor = newest or cursor
                yield _sse(
                    event="snapshot",
                    event_id=cursor,
                    data=_snapshot(request),
                )
            while True:
                delivered = False
                for event in queryset.filter(sequence__gt=cursor).order_by("sequence")[:500]:
                    cursor = event.sequence
                    event_kind = _kind(event.event_type)
                    if requested_kinds and event_kind not in requested_kinds:
                        continue
                    delivered = True
                    yield _sse(
                        event=event_kind,
                        event_id=event.sequence,
                        data=event_document(event, admin=admin),
                    )
                if not follow:
                    return
                if not delivered:
                    yield ": keep-alive\n\n"
                time.sleep(1)

        response = StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["Connection"] = "keep-alive"
        response["Open-Cinema-Event-Cursor"] = str(newest or cursor)
        response["Open-Cinema-Event-Gap"] = "true" if gap else "false"
        return response
