from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from typing import cast

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from api.models import (
    EndpointAudioLevel,
    LogicalEndpoint,
    MasterAudioLevel,
    OrchestrationEvent,
    RuntimeProjection,
)
from core.orchestration.endpoint_matching import EndpointMatchStatus, match_endpoint_candidates
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from core.orchestration.endpoint_inventory import RuntimeEndpointCandidate
from core.orchestration.desired_state_monitor import publish_audio_level_wakeup

from .base import (
    AudioAPIProblem,
    AudioV1APIView,
    entity_tag,
    parse_precondition,
    require_object,
)
from .inventory_views import _candidate_records


def master_audio_level() -> MasterAudioLevel:
    try:
        value, _ = MasterAudioLevel.objects.get_or_create(pk=1)
    except IntegrityError:
        value = MasterAudioLevel.objects.get(pk=1)
    return value


def endpoint_audio_level(endpoint: LogicalEndpoint) -> EndpointAudioLevel:
    try:
        value, _ = EndpointAudioLevel.objects.get_or_create(endpoint=endpoint)
    except IntegrityError:
        value = EndpointAudioLevel.objects.get(endpoint=endpoint)
    return value


def _timestamp(value) -> str | None:
    return value.isoformat() if value is not None else None


def _latest_runtime_version() -> str | None:
    projection = (
        RuntimeProjection.objects.filter(is_current=True)
        .order_by("-world_generation", "-world_sequence")
        .first()
    )
    return (
        f"{projection.world_generation}:{projection.world_sequence}"
        if projection is not None
        else None
    )


def _master_document(value: MasterAudioLevel) -> dict[str, object]:
    projection = RuntimeProjection.objects.filter(
        is_current=True,
        projection_type="audio-level",
        subject_key="master",
    ).first()
    runtime = projection.payload if projection is not None else {}
    return {
        "schemaVersion": 1,
        "scope": "master-output",
        "desired": {"level": value.level, "muted": value.muted},
        "effective": runtime.get("effective", {"level": value.level, "muted": value.muted}),
        "observed": runtime.get("observed", {"outputs": [], "known": False}),
        "writable": True,
        "applying": bool(runtime.get("applying", False)),
        "degraded": runtime.get("degraded", []),
        "runtimeVersion": (
            f"{projection.world_generation}:{projection.world_sequence}"
            if projection is not None
            else _latest_runtime_version()
        ),
        "updateVersion": value.update_version,
        "updatedAt": _timestamp(value.updated_at),
    }


def _endpoint_resolution(endpoint: LogicalEndpoint) -> dict[str, object]:
    records = _candidate_records(endpoint.direction)
    validation = parse_endpoint_selector(endpoint.explicit_binding or endpoint.selector)
    if not validation.valid:
        return {
            "availability": "invalid",
            "candidate": None,
            "projection": None,
            "runtimeVersion": None,
            "reason": "The endpoint selector is invalid.",
        }
    result = match_endpoint_candidates(validation.selector, [candidate for _, candidate in records])
    if result.status is not EndpointMatchStatus.MATCHED or result.selected is None:
        availability = (
            "ambiguous" if result.status is EndpointMatchStatus.AMBIGUOUS else "unavailable"
        )
        return {
            "availability": availability,
            "candidate": None,
            "projection": None,
            "runtimeVersion": None,
            "reason": (
                "More than one runtime device matches this logical endpoint."
                if availability == "ambiguous"
                else "The logical endpoint is not currently connected."
            ),
        }
    projection = next(
        item for item, candidate in records if candidate.runtime_key == result.selected.runtime_key
    )
    return {
        "availability": "available",
        "candidate": result.selected,
        "projection": projection,
        # The mutation guard protects the ephemeral node selected for this logical
        # endpoint.  A world sequence advances for unrelated observations too, so
        # using it here made an otherwise unchanged device stale every few seconds.
        # The runtime key already contains the runtime generation and node id and
        # therefore changes exactly when the operation target is recreated.
        "runtimeVersion": result.selected.runtime_key,
        "reason": None,
    }


def _endpoint_document(endpoint: LogicalEndpoint, value: EndpointAudioLevel) -> dict[str, object]:
    master = master_audio_level()
    resolution = _endpoint_resolution(endpoint)
    candidate = cast(RuntimeEndpointCandidate | None, resolution["candidate"])
    output = endpoint.direction == "output"
    effective_level = value.level * master.level if output else value.level
    effective_muted = value.muted or (master.muted if output else False)
    observed_level = candidate.volume if candidate is not None else None
    observed_muted = candidate.mute if candidate is not None else None
    volume_writable = bool(candidate is not None and candidate.volume_writable)
    mute_writable = bool(candidate is not None and candidate.mute_writable)
    differences = bool(
        candidate is not None
        and (
            (
                volume_writable
                and observed_level is not None
                and abs(float(observed_level) - float(effective_level)) > 0.0001
            )
            or (mute_writable and observed_muted != effective_muted)
        )
    )
    degraded = []
    if resolution["reason"]:
        degraded.append(
            {"code": f"endpoint-{resolution['availability']}", "detail": resolution["reason"]}
        )
    return {
        "schemaVersion": 1,
        "scope": "device-level" if output else "input-level",
        "endpointId": str(endpoint.pk),
        "direction": endpoint.direction,
        "availability": resolution["availability"],
        "desired": {"level": value.level, "muted": value.muted},
        "master": (
            {"level": master.level, "muted": master.muted, "updateVersion": master.update_version}
            if output
            else None
        ),
        "effective": {"level": effective_level, "muted": effective_muted},
        "observed": {
            "level": observed_level,
            "muted": observed_muted,
            "known": candidate is not None
            and observed_level is not None
            and observed_muted is not None,
        },
        "capabilities": {
            "volume": {
                "readable": candidate is not None and observed_level is not None,
                "writable": volume_writable,
            },
            "mute": {
                "readable": candidate is not None and observed_muted is not None,
                "writable": mute_writable,
            },
        },
        "applying": differences,
        "degraded": degraded,
        "runtimeVersion": resolution["runtimeVersion"],
        "updateVersion": value.update_version,
        "updatedAt": _timestamp(value.updated_at),
    }


def _validated_changes(body: Mapping[str, object], *, endpoint: bool) -> dict[str, object]:
    allowed = {"level", "muted"}
    if endpoint:
        allowed.add("runtimeVersion")
    unknown = set(body) - allowed
    if unknown:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "unknown-fields",
            "Unknown fields",
            f"Unsupported audio-level fields: {', '.join(sorted(unknown))}.",
        )
    changes = {key: body[key] for key in ("level", "muted") if key in body}
    if not changes:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "empty-update",
            "Empty update",
            "At least one of level or muted is required.",
        )
    if "level" in changes:
        level = changes["level"]
        if (
            isinstance(level, bool)
            or not isinstance(level, (int, float))
            or not math.isfinite(float(level))
            or not 0 <= float(level) <= 1
        ):
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "level-out-of-range",
                "Audio level is invalid",
                "level must be a finite number between zero and one inclusive.",
            )
        changes["level"] = float(level)
    if "muted" in changes and not isinstance(changes["muted"], bool):
        raise AudioAPIProblem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "mute-invalid",
            "Mute state is invalid",
            "muted must be a boolean.",
        )
    return changes


def _require_staff(user) -> None:
    if not (user.is_staff or user.is_superuser):
        raise PermissionDenied("Only staff administrators may change persistent audio level.")


def _event(user, event_type: str, payload: dict[str, object]) -> None:
    OrchestrationEvent.objects.create(
        correlation_id=uuid.uuid4(),
        event_type=event_type,
        payload={**payload, "actorId": str(user.pk)},
    )


class MasterAudioLevelView(AudioV1APIView):
    def get(self, request):
        value = master_audio_level()
        response = Response(_master_document(value))
        response["ETag"] = entity_tag(value.update_version)
        return response

    def patch(self, request):
        _require_staff(request.user)
        changes = _validated_changes(require_object(request.data), endpoint=False)
        expected = parse_precondition(request, minimum=1)
        with transaction.atomic():
            master_audio_level()
            value = MasterAudioLevel.objects.select_for_update().get(pk=1)
            if value.update_version != expected:
                raise AudioAPIProblem(
                    status.HTTP_412_PRECONDITION_FAILED,
                    "audio-level-precondition-failed",
                    "Master audio level changed",
                    "Refresh the master audio level before changing it.",
                    current_version=value.update_version,
                )
            for field, field_value in changes.items():
                setattr(value, field, field_value)
            value.update_version += 1
            value.full_clean()
            value.save()
            _event(
                request.user,
                "audio-level.master-intent",
                {
                    "desired": {"level": value.level, "muted": value.muted},
                    "updateVersion": value.update_version,
                },
            )
            transaction.on_commit(
                lambda: publish_audio_level_wakeup(
                    scope_id="master", update_version=value.update_version
                )
            )
        response = Response(_master_document(value))
        response["ETag"] = entity_tag(value.update_version)
        return response


class EndpointAudioLevelView(AudioV1APIView):
    def get(self, request, endpoint_id):
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        value = endpoint_audio_level(endpoint)
        response = Response(_endpoint_document(endpoint, value))
        response["ETag"] = entity_tag(value.update_version)
        return response

    def patch(self, request, endpoint_id):
        _require_staff(request.user)
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        body = require_object(request.data)
        changes = _validated_changes(body, endpoint=True)
        resolution = _endpoint_resolution(endpoint)
        if resolution["candidate"] is None:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                f"endpoint-{resolution['availability']}",
                "Endpoint cannot be controlled",
                str(resolution["reason"]),
            )
        submitted_runtime = body.get("runtimeVersion")
        if submitted_runtime != resolution["runtimeVersion"]:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "runtime-version-stale",
                "Runtime observation changed",
                "Refresh the endpoint before changing its level.",
            )
        candidate = resolution["candidate"]
        if "level" in changes and not candidate.volume_writable:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "endpoint-volume-read-only",
                "Device level is read-only",
                "The current runtime candidate does not advertise writable volume.",
            )
        if "muted" in changes and not candidate.mute_writable:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "endpoint-mute-read-only",
                "Device mute is read-only",
                "The current runtime candidate does not advertise writable mute.",
            )
        expected = parse_precondition(request, minimum=1)
        with transaction.atomic():
            endpoint_audio_level(endpoint)
            value = EndpointAudioLevel.objects.select_for_update().get(endpoint=endpoint)
            if value.update_version != expected:
                raise AudioAPIProblem(
                    status.HTTP_412_PRECONDITION_FAILED,
                    "audio-level-precondition-failed",
                    "Endpoint audio level changed",
                    "Refresh the endpoint audio level before changing it.",
                    current_version=value.update_version,
                )
            for field, field_value in changes.items():
                setattr(value, field, field_value)
            value.update_version += 1
            value.full_clean()
            value.save()
            _event(
                request.user,
                "audio-level.endpoint-intent",
                {
                    "endpointId": str(endpoint.pk),
                    "direction": endpoint.direction,
                    "desired": {"level": value.level, "muted": value.muted},
                    "updateVersion": value.update_version,
                },
            )
            transaction.on_commit(
                lambda: publish_audio_level_wakeup(
                    scope_id=f"endpoint:{endpoint.pk}",
                    update_version=value.update_version,
                )
            )
        response = Response(_endpoint_document(endpoint, value))
        response["ETag"] = entity_tag(value.update_version)
        return response
