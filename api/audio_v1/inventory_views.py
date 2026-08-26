from __future__ import annotations

import re
from collections.abc import Mapping

from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from wyreplumber.runtime import FrozenDict, freeze_json

from api.models import LogicalEndpoint, RuntimeProjection
from core.orchestration.endpoint_binding import (
    UnstableEndpointIdentityError,
    derive_reviewable_selector,
)
from core.orchestration.endpoint_inventory import (
    EndpointDirection,
    EndpointFormatSummary,
    EndpointLatencySummary,
    EndpointPortSummary,
    EndpointProfileSummary,
    EndpointRouteSummary,
    ObservedAudioValue,
    RuntimeEndpointCandidate,
    RuntimeEndpointReference,
    RuntimeProfileReference,
    RuntimeRouteReference,
)
from core.orchestration.endpoint_matching import match_endpoint_candidates
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from core.orchestration.endpoints import (
    LogicalEndpointUpdateConflict,
    update_logical_endpoint,
)

from .base import (
    AudioAPIProblem,
    AudioV1APIView,
    entity_tag,
    paginated,
    parse_precondition,
    require_object,
)
from .representations import endpoint_document, projection_document

_RUNTIME_KEY = re.compile(r"^runtime:(?P<generation>[0-9]+):node:(?P<node>[0-9]+)$")
_CANDIDATE_TYPES = ("endpoint", "endpoint-candidate")


def _observed(value: object) -> ObservedAudioValue:
    if not isinstance(value, Mapping):
        return ObservedAudioValue(value=None, known=False)
    return ObservedAudioValue(
        value=freeze_json(value.get("value")),
        known=bool(value.get("known", False)),
        choices=tuple(freeze_json(item) for item in value.get("choices", ())),
    )


def _format(value: object) -> EndpointFormatSummary:
    value = value if isinstance(value, Mapping) else {}
    return EndpointFormatSummary(
        content=str(value.get("content", "any")),
        media_type=_observed(value.get("mediaType")),
        media_subtype=_observed(value.get("mediaSubtype")),
        sample_format=_observed(value.get("sampleFormat")),
        rate=_observed(value.get("rate")),
        channels=_observed(value.get("channels")),
        positions=_observed(value.get("positions")),
        codec=_observed(value.get("codec")),
    )


def runtime_candidate_from_projection(projection: RuntimeProjection) -> RuntimeEndpointCandidate:
    payload = projection.payload
    runtime_key = payload.get("runtimeKey", projection.subject_key)
    matched = _RUNTIME_KEY.match(runtime_key) if isinstance(runtime_key, str) else None
    if matched is None:
        raise ValueError("endpoint projection has no valid opaque runtimeKey")
    generation = int(matched.group("generation"))
    node_id = int(matched.group("node"))
    device = payload.get("device") if isinstance(payload.get("device"), Mapping) else {}
    node_properties = payload.get("nodeProperties", {})
    device_properties = device.get("properties", {})
    capabilities = payload.get("audioCapabilities", {})
    if not isinstance(capabilities, Mapping):
        capabilities = {}
    profiles = []
    for index, item in enumerate(payload.get("profiles", ())):
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        profiles.append(
            EndpointProfileSummary(
                runtime=RuntimeProfileReference(generation, 0, index),
                name=item["name"],
                description=item.get("description"),
                priority=int(item.get("priority", 0)),
                availability=str(item.get("availability", "unknown")),
                active=bool(item.get("active", False)),
                classes=tuple(item.get("classes", ())),
                properties=FrozenDict(item.get("properties", {})),
            )
        )
    routes = []
    for index, item in enumerate(payload.get("routes", ())):
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        routes.append(
            EndpointRouteSummary(
                runtime=RuntimeRouteReference(generation, 0, index),
                name=item["name"],
                description=item.get("description"),
                direction=str(item.get("direction", payload.get("direction", "output"))),
                priority=int(item.get("priority", 0)),
                availability=str(item.get("availability", "unknown")),
                active=bool(item.get("active", False)),
                profile_names=tuple(item.get("profiles", ())),
                volume=item.get("volume"),
                mute=item.get("mute"),
                properties=FrozenDict(item.get("properties", {})),
            )
        )
    latency = capabilities.get("latency", {})
    if not isinstance(latency, Mapping):
        latency = {}
    return RuntimeEndpointCandidate(
        runtime=RuntimeEndpointReference(generation, node_id, None),
        direction=EndpointDirection(payload["direction"]),
        name=payload.get("name"),
        description=payload.get("description"),
        media_class=str(payload.get("mediaClass", "Audio/Unknown")),
        node_state=str(payload.get("state", "unknown")),
        node_error=payload.get("error"),
        node_properties=FrozenDict(node_properties),
        device_name=device.get("name"),
        device_description=device.get("description"),
        device_media_class=device.get("mediaClass"),
        device_properties=FrozenDict(device_properties),
        ports=tuple(
            EndpointPortSummary(
                name=item.get("name"),
                direction=str(item.get("direction", "unknown")),
                channel=item.get("channel"),
                properties=FrozenDict(item.get("properties", {})),
            )
            for item in payload.get("ports", ())
            if isinstance(item, Mapping)
        ),
        profiles=tuple(profiles),
        routes=tuple(routes),
        formats=tuple(_format(item) for item in capabilities.get("formats", ())),
        volume=capabilities.get("volume", payload.get("volume")),
        mute=capabilities.get("mute", payload.get("mute")),
        latency=EndpointLatencySummary(
            milliseconds=latency.get("milliseconds"),
            raw=latency.get("raw"),
            known=bool(latency.get("known", False)),
        ),
        is_default=bool(payload.get("default", False)),
        is_linked=bool(payload.get("linked", False)),
        has_active_signal=bool(payload.get("activeSignal", False)),
    )


def _candidate_records(direction: str | None = None):
    queryset = RuntimeProjection.objects.filter(
        is_current=True,
        projection_type__in=_CANDIDATE_TYPES,
    )
    records = []
    for projection in queryset.order_by("subject_key"):
        try:
            candidate = runtime_candidate_from_projection(projection)
        except (KeyError, TypeError, ValueError):
            continue
        if direction is None or candidate.direction.value == direction:
            records.append((projection, candidate))
    return records


def _validate_selector(document: object) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise AudioAPIProblem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "selector-invalid",
            "Selector invalid",
            "A selector must be an object.",
        )
    result = parse_endpoint_selector(document)
    if not result.valid:
        raise AudioAPIProblem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "selector-invalid",
            "Selector invalid",
            "The endpoint selector is invalid.",
            errors=[
                {"path": issue.path, "code": issue.code, "message": issue.message}
                for issue in result.issues
            ],
        )
    return dict(document)


def _match_document(endpoint, records):
    selector_document = endpoint.explicit_binding or endpoint.selector
    validation = parse_endpoint_selector(selector_document)
    if not validation.valid:
        return {
            "status": "invalid_selector",
            "selectedRuntimeKey": None,
            "tiedRuntimeKeys": [],
            "diagnostics": [],
            "selectorIssues": [
                {"path": item.path, "code": item.code, "message": item.message}
                for item in validation.issues
            ],
        }
    result = match_endpoint_candidates(
        validation.selector,
        [candidate for _, candidate in records],
    )
    return {
        "status": result.status.value,
        "selectedRuntimeKey": (
            result.selected.runtime_key if result.selected is not None else None
        ),
        "tiedRuntimeKeys": [item.runtime_key for item in result.tied],
        "diagnostics": [
            {
                "runtimeKey": item.runtime_key,
                "name": item.name,
                "matched": item.matched_selector,
                "score": item.score,
                "predicates": [
                    {
                        "path": evidence.path,
                        "operator": evidence.operator,
                        "matched": evidence.matched,
                    }
                    for evidence in item.predicates
                ],
                "acceptedEvidence": list(item.accepted_evidence),
                "rejectedEvidence": list(item.rejected_evidence),
            }
            for item in result.diagnostics
        ],
        "selectorIssues": [],
    }


class EndpointListView(AudioV1APIView):
    def get(self, request):
        queryset = LogicalEndpoint.objects.visible_to(request.user)
        direction = request.query_params.get("direction")
        if direction is not None:
            if direction not in {"input", "output"}:
                raise AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-filter",
                    "Invalid filter",
                    "direction must be input or output.",
                )
            queryset = queryset.filter(direction=direction)
        for field in ("tag", "group"):
            value = request.query_params.get(field)
            if value:
                attribute = f"{field}s"
                selected = [item.pk for item in queryset if value in getattr(item, attribute)]
                queryset = queryset.filter(pk__in=selected)
        return paginated(request, queryset, endpoint_document)

    def post(self, request):
        body = require_object(request.data)
        selector = _validate_selector(body.get("selector"))
        endpoint = LogicalEndpoint(
            name=body.get("name", ""),
            owner=request.user,
            direction=body.get("direction"),
            selector=selector,
            tags=body.get("tags", []),
            groups=body.get("groups", []),
            policy_metadata=body.get("policyMetadata", {}),
            explicit_binding=(
                _validate_selector(body["explicitBinding"])
                if body.get("explicitBinding") is not None
                else None
            ),
            last_known_summary=body.get("lastKnown", {}),
        )
        endpoint.full_clean()
        try:
            endpoint.save()
        except IntegrityError as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "endpoint-conflict",
                "Endpoint conflict",
                "An endpoint with this name already exists for the owner.",
            ) from error
        response = Response(endpoint_document(endpoint), status=status.HTTP_201_CREATED)
        response["ETag"] = entity_tag(endpoint.update_version)
        response["Location"] = f"/api/audio/v1/endpoints/{endpoint.pk}"
        return response


class EndpointDetailView(AudioV1APIView):
    def get(self, request, endpoint_id):
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        response = Response(endpoint_document(endpoint))
        response["ETag"] = entity_tag(endpoint.update_version)
        return response

    def patch(self, request, endpoint_id):
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        body = require_object(request.data)
        names = {
            "name": "name",
            "direction": "direction",
            "selector": "selector",
            "tags": "tags",
            "groups": "groups",
            "policyMetadata": "policy_metadata",
            "explicitBinding": "explicit_binding",
            "lastKnown": "last_known_summary",
        }
        unknown = set(body) - set(names)
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                f"Unsupported endpoint fields: {', '.join(sorted(unknown))}.",
            )
        changes = {names[name]: value for name, value in body.items()}
        if "selector" in changes:
            changes["selector"] = _validate_selector(changes["selector"])
        if changes.get("explicit_binding") is not None and "explicit_binding" in changes:
            changes["explicit_binding"] = _validate_selector(changes["explicit_binding"])
        try:
            endpoint = update_logical_endpoint(
                endpoint.pk,
                actor=request.user,
                expected_version=parse_precondition(request, minimum=1),
                **changes,
            )
        except LogicalEndpointUpdateConflict as error:
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "endpoint-precondition-failed",
                "Endpoint changed",
                str(error),
                current_version=error.actual_version,
            ) from error
        response = Response(endpoint_document(endpoint))
        response["ETag"] = entity_tag(endpoint.update_version)
        return response


class EndpointCandidateListView(AudioV1APIView):
    def get(self, request):
        direction = request.query_params.get("direction")
        capability = request.query_params.get("capability")
        records = _candidate_records(direction)
        if capability:
            allowed = {"volume", "mute", "pcm", "encoded"}
            if capability not in allowed:
                raise AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-filter",
                    "Invalid filter",
                    f"capability must be one of {', '.join(sorted(allowed))}.",
                )
            records = [
                item
                for item in records
                if (
                    getattr(item[1], capability) is not None
                    if capability in {"volume", "mute"}
                    else any(fmt.content == capability for fmt in item[1].formats)
                )
            ]
        return Response(
            {
                "items": [
                    projection_document(item, admin=request.user.is_staff)
                    for item, _candidate in records
                ],
                "runtimeAvailable": bool(records),
            }
        )


class EndpointCandidateExplanationView(AudioV1APIView):
    def get(self, request, endpoint_id):
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        records = _candidate_records(endpoint.direction)
        return Response(
            {
                "endpoint": endpoint_document(endpoint),
                "resolution": _match_document(endpoint, records),
                "world": {
                    "generation": max(
                        (projection.world_generation for projection, _ in records),
                        default=None,
                    ),
                    "sequence": max(
                        (projection.world_sequence for projection, _ in records),
                        default=None,
                    ),
                    "runtimeAvailable": bool(records),
                },
            }
        )


class SelectorPreviewView(AudioV1APIView):
    def post(self, request):
        body = require_object(request.data)
        selector = _validate_selector(body.get("selector"))
        direction = body.get("direction")
        temporary = type("EndpointPreview", (), {})()
        temporary.selector = selector
        temporary.explicit_binding = None
        return Response(
            {
                "selector": selector,
                "resolution": _match_document(temporary, _candidate_records(direction)),
                "persistentDesiredChange": False,
            }
        )


class EndpointBindingView(AudioV1APIView):
    def post(self, request, endpoint_id):
        endpoint = LogicalEndpoint.objects.visible_to(request.user).get(pk=endpoint_id)
        expected = parse_precondition(request, minimum=1)
        body = require_object(request.data)
        runtime_key = body.get("runtimeKey")
        review = None
        if runtime_key is None:
            selector = None
        else:
            records = _candidate_records(endpoint.direction)
            candidate = next(
                (candidate for _, candidate in records if candidate.runtime_key == runtime_key),
                None,
            )
            if candidate is None:
                raise AudioAPIProblem(
                    status.HTTP_409_CONFLICT,
                    "runtime-candidate-unavailable",
                    "Runtime candidate unavailable",
                    "The selected runtime candidate disappeared; refresh the inventory.",
                )
            try:
                derived = derive_reviewable_selector(candidate)
            except UnstableEndpointIdentityError as error:
                raise AudioAPIProblem(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "unstable-endpoint-identity",
                    "Endpoint identity is unstable",
                    str(error),
                ) from error
            selector = derived.document
            review = {
                "confidence": derived.confidence.value,
                "warnings": list(derived.warnings),
                "evidence": [
                    {
                        "tier": int(item.tier),
                        "kind": item.kind.value,
                        "path": item.path,
                        "value": item.value,
                    }
                    for item in derived.evidence
                ],
            }
        try:
            updated = update_logical_endpoint(
                endpoint.pk,
                actor=request.user,
                expected_version=expected,
                explicit_binding=selector,
            )
        except LogicalEndpointUpdateConflict as error:
            raise AudioAPIProblem(
                status.HTTP_412_PRECONDITION_FAILED,
                "endpoint-precondition-failed",
                "Endpoint changed",
                str(error),
                current_version=error.actual_version,
            ) from error
        response = Response(
            {
                "endpoint": endpoint_document(updated),
                "selectorReview": review,
                "persistentDesiredChange": True,
            }
        )
        response["ETag"] = entity_tag(updated.update_version)
        return response
