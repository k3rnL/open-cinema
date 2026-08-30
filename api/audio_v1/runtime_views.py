from __future__ import annotations

from django.core.exceptions import PermissionDenied
from rest_framework.response import Response

from api.models import DiagnosticRecord, OrchestrationEvent, RuntimeProjection
from core.orchestration.feature_flags import get_audio_orchestration_feature_flags

from .base import AudioV1APIView
from .managed_resources import managed_resource_documents
from .representations import event_document, projection_document, timestamp


def _is_admin(user) -> bool:
    return bool(user.is_staff or user.is_superuser)


def _projection_queryset(request, *, types=None):
    queryset = RuntimeProjection.objects.filter(is_current=True)
    requested = request.query_params.get("types")
    if requested:
        queryset = queryset.filter(
            projection_type__in=tuple(item.strip() for item in requested.split(",") if item.strip())
        )
    elif types is not None:
        queryset = queryset.filter(projection_type__in=types)
    subject = request.query_params.get("subject")
    if subject:
        queryset = queryset.filter(subject_key=subject)
    generation = request.query_params.get("generation")
    if generation:
        queryset = queryset.filter(world_generation=generation)
    return queryset.order_by("projection_type", "subject_key")


class RuntimeSnapshotView(AudioV1APIView):
    def get(self, request):
        queryset = _projection_queryset(request)
        latest = queryset.order_by("-world_generation", "-world_sequence").first()
        items = [projection_document(item, admin=_is_admin(request.user)) for item in queryset]
        return Response(
            {
                "representation": "observedRuntime",
                "runtimeAvailable": latest is not None,
                "worldGeneration": latest.world_generation if latest else None,
                "worldSequence": latest.world_sequence if latest else None,
                "items": items,
            }
        )


class ManagedResourceView(AudioV1APIView):
    def get(self, request):
        return Response({"schemaVersion": 1, "items": managed_resource_documents(request.user)})


class ProcessorHealthView(AudioV1APIView):
    def get(self, request):
        queryset = _projection_queryset(
            request,
            types=("processor", "processor-health"),
        )
        return Response(
            {
                "items": [
                    projection_document(item, admin=_is_admin(request.user)) for item in queryset
                ]
            }
        )


class OrchestrationReadinessView(AudioV1APIView):
    def get(self, request):
        flags = get_audio_orchestration_feature_flags()
        runtime = (
            RuntimeProjection.objects.filter(is_current=True)
            .order_by("-world_generation", "-world_sequence")
            .first()
        )
        health = RuntimeProjection.objects.filter(
            is_current=True,
            projection_type__in=("health", "orchestration-health"),
        ).first()
        processors = RuntimeProjection.objects.filter(
            is_current=True,
            projection_type__in=("processor", "processor-health"),
        )
        processor_documents = [item.payload for item in processors]
        processors_ready = (
            all(item.get("ready", False) for item in processor_documents)
            if processor_documents
            else True
        )
        runtime_ready = bool(
            runtime is not None and (health is None or health.payload.get("ready"))
        )
        blockers = list(flags.live_control_blockers)
        if not runtime_ready:
            blockers.append("runtime_unavailable")
        if not processors_ready:
            blockers.append("processor_unavailable")
        return Response(
            {
                "ready": not blockers,
                "diagnosticsAvailable": True,
                "desiredEditingAvailable": True,
                "liveControlsAvailable": not blockers,
                "blockers": blockers,
                "features": flags.as_dict(),
                "runtime": {
                    "available": runtime is not None,
                    "worldGeneration": runtime.world_generation if runtime else None,
                    "worldSequence": runtime.world_sequence if runtime else None,
                },
                "processorsReady": processors_ready,
            }
        )


class DiagnosticBundleView(AudioV1APIView):
    def get(self, request):
        if not _is_admin(request.user):
            raise PermissionDenied("Diagnostic bundles contain administrative runtime properties.")
        try:
            limit = min(max(int(request.query_params.get("limit", 100)), 1), 500)
        except (TypeError, ValueError):
            limit = 100
        projections = RuntimeProjection.objects.order_by("-created_at")[:limit]
        events = OrchestrationEvent.objects.order_by("-sequence")[:limit]
        diagnostics = DiagnosticRecord.objects.order_by("-sequence")[:limit]
        return Response(
            {
                "schemaVersion": 1,
                "administrative": True,
                "generatedAt": timestamp(
                    max(
                        [item.created_at for item in projections],
                        default=None,
                    )
                ),
                "runtimeProjections": [
                    projection_document(item, admin=True) for item in projections
                ],
                "events": [event_document(item, admin=True) for item in events],
                "diagnostics": [
                    {
                        "sequence": item.sequence,
                        "id": str(item.id),
                        "correlationId": (
                            str(item.correlation_id) if item.correlation_id else None
                        ),
                        "category": item.category,
                        "severity": item.severity,
                        "payload": item.payload,
                        "capturedAt": timestamp(item.captured_at),
                    }
                    for item in diagnostics
                ],
            }
        )
