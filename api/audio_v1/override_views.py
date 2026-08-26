from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response

from api.models import ManualOverride
from core.orchestration.overrides import cancel_manual_override

from .base import (
    AudioAPIProblem,
    AudioV1APIView,
    paginated,
    parse_boolean,
    require_object,
)
from .representations import override_document


def _visible_overrides(request):
    queryset = ManualOverride.objects.all()
    if not (request.user.is_staff or request.user.is_superuser):
        queryset = queryset.filter(creator=request.user)
    return queryset


def _datetime(value: object, *, field: str, default=None):
    if value is None:
        return default
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or not timezone.is_aware(parsed):
        raise AudioAPIProblem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid-timestamp",
            "Invalid timestamp",
            f"{field} must be an ISO-8601 timestamp with an offset.",
        )
    return parsed


class OverrideListView(AudioV1APIView):
    def get(self, request):
        queryset = _visible_overrides(request)
        for parameter, field in (
            ("scopeType", "scope_type"),
            ("scopeId", "scope_id"),
            ("creatorId", "creator_id"),
        ):
            value = request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        active = request.query_params.get("active")
        if active is not None:
            active_value = parse_boolean(active, field="active")
            active_ids = [item.pk for item in queryset if item.is_active()]
            queryset = (
                queryset.filter(pk__in=active_ids)
                if active_value
                else queryset.exclude(pk__in=active_ids)
            )
        return paginated(request, queryset, override_document)

    def post(self, request):
        body = require_object(request.data)
        now = timezone.now()
        override = ManualOverride(
            scope_type=body.get("scopeType"),
            scope_id=body.get("scopeId", ""),
            value=body.get("value"),
            priority=body.get("priority", 100),
            creator=request.user,
            reason=body.get("reason", ""),
            starts_at=_datetime(body.get("startsAt"), field="startsAt", default=now),
            expires_at=_datetime(body.get("expiresAt"), field="expiresAt"),
        )
        override.full_clean()
        override.save()
        response = Response(
            override_document(override),
            status=status.HTTP_201_CREATED,
        )
        response["Location"] = f"/api/audio/v1/overrides/{override.pk}"
        return response


class OverrideCancelView(AudioV1APIView):
    def post(self, request, override_id):
        override = _visible_overrides(request).get(pk=override_id)
        cancelled = cancel_manual_override(
            override.pk,
            actor=request.user,
        )
        return Response(override_document(cancelled))
