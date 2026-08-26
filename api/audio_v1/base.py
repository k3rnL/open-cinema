from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import (
    ObjectDoesNotExist,
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from core.orchestration.feature_flags import get_audio_orchestration_feature_flags

from . import API_MEDIA_TYPE, API_VERSION, PROBLEM_MEDIA_TYPE


class AudioJSONRenderer(JSONRenderer):
    media_type = API_MEDIA_TYPE


class AudioAPIProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        *,
        errors: object | None = None,
        current_version: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors
        self.current_version = current_version
        super().__init__(detail)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return str(value) if isinstance(value, exceptions.ErrorDetail) else value


def problem_response(request, problem: AudioAPIProblem) -> Response:
    document: dict[str, object] = {
        "type": f"https://open-cinema.invalid/problems/{problem.code}",
        "title": problem.title,
        "status": problem.status_code,
        "detail": problem.detail,
        "code": problem.code,
        "instance": request.path,
        "apiVersion": API_VERSION,
    }
    if problem.errors is not None:
        document["errors"] = _plain(problem.errors)
    if problem.current_version is not None:
        document["currentVersion"] = problem.current_version
    return Response(
        document,
        status=problem.status_code,
        content_type=PROBLEM_MEDIA_TYPE,
    )


def require_object(value: object, *, field: str = "body") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-request",
            "Invalid request",
            f"{field} must be a JSON object.",
        )
    return value


def parse_boolean(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise AudioAPIProblem(
        status.HTTP_400_BAD_REQUEST,
        "invalid-filter",
        "Invalid filter",
        f"{field} must be true or false.",
    )


def parse_precondition(request, *, minimum: int = 0) -> int:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise AudioAPIProblem(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "precondition-required",
            "Precondition required",
            "This operation requires If-Match with the last observed numeric version.",
        )
    candidate = raw.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    try:
        version = int(candidate)
    except (TypeError, ValueError) as error:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-precondition",
            "Invalid precondition",
            "If-Match must contain one numeric entity version.",
        ) from error
    if version < minimum:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-precondition",
            "Invalid precondition",
            f"If-Match version must be at least {minimum}.",
        )
    return version


def entity_tag(version: int) -> str:
    return f'"{version}"'


def paginated(request, queryset, serializer, *, maximum: int = 100) -> Response:
    try:
        limit = int(request.query_params.get("limit", 25))
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError) as error:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-pagination",
            "Invalid pagination",
            "limit and offset must be integers.",
        ) from error
    if not 1 <= limit <= maximum or offset < 0:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-pagination",
            "Invalid pagination",
            f"limit must be between 1 and {maximum}; offset must not be negative.",
        )
    total = queryset.count()
    end = offset + limit
    items = [serializer(item) for item in queryset[offset:end]]
    return Response(
        {
            "items": items,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "nextOffset": offset + limit if offset + limit < total else None,
            },
        }
    )


class AudioV1APIView(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (AudioJSONRenderer, JSONRenderer)

    def initial(self, request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        requested = request.headers.get("Open-Cinema-API-Version")
        if requested is not None and requested != str(API_VERSION):
            raise AudioAPIProblem(
                status.HTTP_406_NOT_ACCEPTABLE,
                "unsupported-api-version",
                "Unsupported API version",
                f"This endpoint supports API version {API_VERSION}.",
            )
        if not get_audio_orchestration_feature_flags().orchestration_api:
            raise AudioAPIProblem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "orchestration-api-disabled",
                "Orchestration API unavailable",
                "The versioned audio orchestration API is disabled by rollout policy.",
            )

    def handle_exception(self, exc):
        if isinstance(exc, AudioAPIProblem):
            return problem_response(self.request, exc)
        if isinstance(exc, DjangoValidationError):
            errors = getattr(exc, "message_dict", None) or getattr(exc, "messages", [str(exc)])
            return problem_response(
                self.request,
                AudioAPIProblem(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "validation-failed",
                    "Validation failed",
                    "The submitted resource is not valid.",
                    errors=errors,
                ),
            )
        if isinstance(exc, ObjectDoesNotExist):
            return problem_response(
                self.request,
                AudioAPIProblem(
                    status.HTTP_404_NOT_FOUND,
                    "not-found",
                    "Not found",
                    "The requested audio orchestration resource was not found.",
                ),
            )
        if isinstance(exc, DjangoPermissionDenied):
            return problem_response(
                self.request,
                AudioAPIProblem(
                    status.HTTP_403_FORBIDDEN,
                    "forbidden",
                    "Forbidden",
                    str(exc) or "You cannot access this resource.",
                ),
            )
        if isinstance(exc, (TypeError, ValueError)):
            return problem_response(
                self.request,
                AudioAPIProblem(
                    status.HTTP_400_BAD_REQUEST,
                    "invalid-request",
                    "Invalid request",
                    str(exc),
                ),
            )
        if isinstance(exc, exceptions.APIException):
            response = super().handle_exception(exc)
            titles = {
                status.HTTP_400_BAD_REQUEST: "Invalid request",
                status.HTTP_401_UNAUTHORIZED: "Authentication required",
                status.HTTP_403_FORBIDDEN: "Forbidden",
                status.HTTP_404_NOT_FOUND: "Not found",
                status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type",
                status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests",
            }
            return problem_response(
                self.request,
                AudioAPIProblem(
                    response.status_code,
                    exc.default_code.replace("_", "-"),
                    titles.get(response.status_code, "Request failed"),
                    str(exc.detail),
                    errors=exc.detail if isinstance(exc.detail, (dict, list)) else None,
                ),
            )
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Open-Cinema-API-Version"] = str(API_VERSION)
        response["Open-Cinema-Schema-Version"] = "1"
        response["Vary"] = "Accept, Open-Cinema-API-Version"
        if getattr(response, "status_code", 500) < 400 and not response.get("Content-Type"):
            response["Content-Type"] = API_MEDIA_TYPE
        return response
