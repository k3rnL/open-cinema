from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from api.models import ManagedAudioAdapter, ManagedAudioAdapterRuntimeState
from core.orchestration.audio_adapters import (
    ADAPTER_SCHEMA_VERSION,
    AudioAdapterConfigurationError,
    adapter_type,
    adapter_type_catalogue,
    normalize_adapter_configuration,
)
from core.orchestration.audit import record_orchestration_event
from core.orchestration.desired_state_monitor import publish_adapter_state_wakeup

from .base import (
    AudioAPIProblem,
    AudioV1APIView,
    entity_tag,
    paginated,
    parse_precondition,
    require_object,
)
from .representations import audio_adapter_document


def _adapter_for(request, adapter_id, *, lock=False):
    queryset = ManagedAudioAdapter.objects.visible_to(request.user).select_related(
        "runtime_state"
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset.get(pk=adapter_id)


def _configuration(kind, value):
    try:
        return normalize_adapter_configuration(kind, require_object(value, field="configuration"))
    except AudioAdapterConfigurationError as error:
        raise AudioAPIProblem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "adapter-configuration-invalid",
            "Adapter configuration invalid",
            str(error),
            errors=[
                {
                    "path": error.field,
                    "code": "invalid-adapter-configuration",
                    "message": str(error),
                }
            ],
        ) from error


def _record_intent(adapter, event_type: str, actor_id, *, changes=()):
    correlation_id = uuid.uuid4()
    adapter_id = str(adapter.pk)
    update_version = adapter.update_version
    record_orchestration_event(
        correlation_id=correlation_id,
        event_type=event_type,
        payload={
            "resource": "audio-adapter",
            "adapterId": str(adapter.pk),
            "actorId": str(actor_id),
            "kind": adapter.kind,
            "enabled": adapter.enabled,
            "updateVersion": adapter.update_version,
            "changes": sorted(changes),
        },
    )
    transaction.on_commit(
        lambda: publish_adapter_state_wakeup(
            adapter_id=adapter_id,
            update_version=update_version,
        )
    )


def _conflict(current):
    return AudioAPIProblem(
        status.HTTP_412_PRECONDITION_FAILED,
        "adapter-precondition-failed",
        "Adapter changed",
        "The adapter changed after it was fetched.",
        current_version=current.update_version,
    )


class AdapterTypeCatalogueView(AudioV1APIView):
    def get(self, request):
        return Response({"schemaVersion": ADAPTER_SCHEMA_VERSION, "items": adapter_type_catalogue()})


class AdapterListView(AudioV1APIView):
    def get(self, request):
        queryset = ManagedAudioAdapter.objects.visible_to(request.user).select_related(
            "runtime_state"
        )
        kind = request.query_params.get("kind")
        if kind:
            adapter_type(kind)
            queryset = queryset.filter(kind=kind)
        return paginated(request, queryset, audio_adapter_document)

    def post(self, request):
        body = require_object(request.data)
        unknown = set(body) - {"name", "kind", "schemaVersion", "configuration", "enabled"}
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                f"Unsupported adapter fields: {', '.join(sorted(unknown))}.",
            )
        if body.get("schemaVersion", ADAPTER_SCHEMA_VERSION) != ADAPTER_SCHEMA_VERSION:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unsupported-schema-version",
                "Unsupported schema version",
                "Only adapter schema version 1 is supported.",
            )
        kind = body.get("kind")
        adapter_type(kind)
        adapter = ManagedAudioAdapter(
            owner=request.user,
            name=body.get("name", ""),
            kind=kind,
            configuration=_configuration(kind, body.get("configuration")),
            enabled=body.get("enabled", False),
        )
        try:
            with transaction.atomic():
                adapter.full_clean()
                adapter.save(force_insert=True)
                ManagedAudioAdapterRuntimeState.objects.create(adapter=adapter)
                _record_intent(adapter, "audio-adapter.created", request.user.pk, changes=body)
        except IntegrityError as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "adapter-conflict",
                "Adapter conflict",
                "An adapter with this name already exists for the owner.",
            ) from error
        response = Response(audio_adapter_document(adapter), status=status.HTTP_201_CREATED)
        response["ETag"] = entity_tag(adapter.update_version)
        response["Location"] = f"/api/audio/v1/adapters/{adapter.pk}"
        return response


class AdapterDetailView(AudioV1APIView):
    def get(self, request, adapter_id):
        adapter = _adapter_for(request, adapter_id)
        response = Response(audio_adapter_document(adapter))
        response["ETag"] = entity_tag(adapter.update_version)
        return response

    def patch(self, request, adapter_id):
        expected = parse_precondition(request, minimum=1)
        body = require_object(request.data)
        unknown = set(body) - {"name", "configuration", "enabled"}
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                f"Unsupported adapter fields: {', '.join(sorted(unknown))}.",
            )
        with transaction.atomic():
            adapter = _adapter_for(request, adapter_id, lock=True)
            if adapter.update_version != expected:
                raise _conflict(adapter)
            if "name" in body:
                adapter.name = body["name"]
            if "configuration" in body:
                adapter.configuration = _configuration(adapter.kind, body["configuration"])
            if "enabled" in body:
                if not isinstance(body["enabled"], bool):
                    raise AudioAPIProblem(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "adapter-enabled-invalid",
                        "Adapter enabled state invalid",
                        "enabled must be a boolean.",
                    )
                adapter.enabled = body["enabled"]
            adapter.update_version += 1
            try:
                adapter.full_clean()
                adapter.save()
            except DjangoValidationError:
                raise
            except IntegrityError as error:
                raise AudioAPIProblem(
                    status.HTTP_409_CONFLICT,
                    "adapter-conflict",
                    "Adapter conflict",
                    "An adapter with this name already exists for the owner.",
                ) from error
            _record_intent(adapter, "audio-adapter.updated", request.user.pk, changes=body)
        adapter = _adapter_for(request, adapter_id)
        response = Response(audio_adapter_document(adapter))
        response["ETag"] = entity_tag(adapter.update_version)
        return response

    def delete(self, request, adapter_id):
        expected = parse_precondition(request, minimum=1)
        with transaction.atomic():
            adapter = _adapter_for(request, adapter_id, lock=True)
            if adapter.update_version != expected:
                raise _conflict(adapter)
            if adapter.enabled:
                raise AudioAPIProblem(
                    status.HTTP_409_CONFLICT,
                    "adapter-still-enabled",
                    "Adapter is still enabled",
                    "Disable the adapter before deleting it.",
                )
            _record_intent(adapter, "audio-adapter.deleted", request.user.pk)
            adapter.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdapterRestartView(AudioV1APIView):
    def post(self, request, adapter_id):
        expected = parse_precondition(request, minimum=1)
        require_object(request.data or {})
        with transaction.atomic():
            adapter = _adapter_for(request, adapter_id, lock=True)
            if adapter.update_version != expected:
                raise _conflict(adapter)
            if not adapter.enabled:
                raise AudioAPIProblem(
                    status.HTTP_409_CONFLICT,
                    "adapter-disabled",
                    "Adapter is disabled",
                    "Enable the adapter before requesting a restart.",
                )
            adapter.restart_generation += 1
            adapter.update_version += 1
            adapter.save(update_fields=["restart_generation", "update_version", "updated_at"])
            _record_intent(adapter, "audio-adapter.restart-requested", request.user.pk)
        adapter = _adapter_for(request, adapter_id)
        response = Response(audio_adapter_document(adapter))
        response["ETag"] = entity_tag(adapter.update_version)
        return response
