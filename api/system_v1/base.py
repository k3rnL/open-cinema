from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from . import API_MEDIA_TYPE, API_VERSION, PROBLEM_MEDIA_TYPE, SCHEMA_VERSION


class SystemJSONRenderer(JSONRenderer):
    media_type = API_MEDIA_TYPE


class SystemAPIProblem(Exception):
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


def problem_response(request, problem: SystemAPIProblem) -> Response:
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
    return Response(document, status=problem.status_code, content_type=PROBLEM_MEDIA_TYPE)


class SystemV1APIView(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (SystemJSONRenderer, JSONRenderer)

    def initial(self, request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        requested = request.headers.get("Open-Cinema-API-Version")
        if requested is not None and requested != str(API_VERSION):
            raise SystemAPIProblem(
                status.HTTP_406_NOT_ACCEPTABLE,
                "unsupported-api-version",
                "Unsupported API version",
                f"This endpoint supports API version {API_VERSION}.",
            )

    def handle_exception(self, exc):
        if isinstance(exc, SystemAPIProblem):
            return problem_response(self.request, exc)
        if isinstance(exc, DjangoPermissionDenied):
            return problem_response(
                self.request,
                SystemAPIProblem(
                    status.HTTP_403_FORBIDDEN,
                    "forbidden",
                    "Forbidden",
                    str(exc) or "You cannot access this appliance resource.",
                ),
            )
        if isinstance(exc, (TypeError, ValueError)):
            return problem_response(
                self.request,
                SystemAPIProblem(
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
                SystemAPIProblem(
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
        response["Open-Cinema-Schema-Version"] = str(SCHEMA_VERSION)
        response["Vary"] = "Accept, Open-Cinema-API-Version"
        if getattr(response, "status_code", 500) < 400 and not response.get("Content-Type"):
            response["Content-Type"] = API_MEDIA_TYPE
        return response
