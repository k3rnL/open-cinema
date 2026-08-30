from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from rest_framework import exceptions, status
from rest_framework.permissions import IsAdminUser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from core.plugin_system.storage import (
    PluginStorageNotFoundError,
    PluginStorageOwnershipError,
    StalePluginStateError,
)
from core.plugin_system.operations import PluginOperationError

from . import API_VERSION


class PluginAPIProblem(Exception):
    def __init__(self, status_code: int, code: str, title: str, detail: str) -> None:
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        super().__init__(detail)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return str(value) if isinstance(value, exceptions.ErrorDetail) else value


def _problem_response(request, problem: PluginAPIProblem) -> Response:
    return Response(
        {
            "type": f"https://open-cinema.invalid/problems/{problem.code}",
            "title": problem.title,
            "status": problem.status_code,
            "detail": problem.detail,
            "code": problem.code,
            "instance": request.path,
            "apiVersion": API_VERSION,
        },
        status=problem.status_code,
        content_type="application/problem+json",
    )


class PluginV2APIView(APIView):
    permission_classes = (IsAdminUser,)
    renderer_classes = (JSONRenderer,)

    def initial(self, request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        from api.apps import refresh_plugin_runtime

        refresh_plugin_runtime()
        requested = request.headers.get("Open-Cinema-API-Version")
        if requested is not None and requested != str(API_VERSION):
            raise PluginAPIProblem(
                status.HTTP_406_NOT_ACCEPTABLE,
                "unsupported-api-version",
                "Unsupported API version",
                f"This endpoint supports API version {API_VERSION}.",
            )

    def handle_exception(self, exc):
        if isinstance(exc, PluginStorageNotFoundError):
            exc = PluginAPIProblem(
                status.HTTP_404_NOT_FOUND,
                "plugin-storage-not-found",
                "Plugin data not found",
                str(exc),
            )
        elif isinstance(exc, PluginStorageOwnershipError):
            exc = PluginAPIProblem(
                status.HTTP_403_FORBIDDEN,
                "plugin-storage-forbidden",
                "Plugin storage forbidden",
                str(exc),
            )
        elif isinstance(exc, StalePluginStateError):
            exc = PluginAPIProblem(
                status.HTTP_409_CONFLICT,
                "stale-plugin-data",
                "Plugin data changed",
                str(exc),
            )
        elif isinstance(exc, PluginOperationError):
            exc = PluginAPIProblem(
                status.HTTP_409_CONFLICT,
                "plugin-operation-conflict",
                "Plugin operation conflict",
                str(exc),
            )
        elif isinstance(exc, DjangoPermissionDenied):
            exc = PluginAPIProblem(
                status.HTTP_403_FORBIDDEN,
                "forbidden",
                "Forbidden",
                str(exc) or "You cannot access plugin administration.",
            )
        elif isinstance(exc, (TypeError, ValueError)):
            exc = PluginAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "invalid-request",
                "Invalid request",
                str(exc),
            )
        if isinstance(exc, PluginAPIProblem):
            return _problem_response(self.request, exc)
        if isinstance(exc, exceptions.APIException):
            response = super().handle_exception(exc)
            return Response(
                {
                    "type": "https://open-cinema.invalid/problems/request-failed",
                    "title": "Request failed",
                    "status": response.status_code,
                    "detail": str(exc.detail),
                    "code": exc.default_code.replace("_", "-"),
                    "instance": self.request.path,
                    "apiVersion": API_VERSION,
                    "errors": _plain(exc.detail),
                },
                status=response.status_code,
                content_type="application/problem+json",
            )
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Open-Cinema-API-Version"] = str(API_VERSION)
        response["Vary"] = "Accept, Open-Cinema-API-Version"
        return response


def parse_version_precondition(request) -> int:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise PluginAPIProblem(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "precondition-required",
            "Precondition required",
            "This operation requires If-Match with the last observed numeric version.",
        )
    candidate = raw.strip().removeprefix("W/").strip().strip('"')
    try:
        version = int(candidate)
    except (TypeError, ValueError) as error:
        raise PluginAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-precondition",
            "Invalid precondition",
            "If-Match must contain one positive numeric version.",
        ) from error
    if version < 1:
        raise PluginAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-precondition",
            "Invalid precondition",
            "If-Match must contain one positive numeric version.",
        )
    return version


def require_object(value: object, field_name: str = "body") -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value
