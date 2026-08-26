from __future__ import annotations

import json
from json import JSONDecodeError

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST


def _identity(request: HttpRequest) -> dict[str, object]:
    user = request.user
    if not user.is_authenticated:
        return {"authenticated": False, "user": None}
    display_name = user.get_full_name().strip() or user.get_username()
    return {
        "authenticated": True,
        "user": {
            "id": str(user.pk),
            "username": user.get_username(),
            "name": display_name,
            "email": user.email,
            "isStaff": user.is_staff,
            "isSuperuser": user.is_superuser,
        },
    }


def _problem(*, status: int, code: str, detail: str) -> JsonResponse:
    return JsonResponse(
        {
            "status": status,
            "code": code,
            "detail": detail,
        },
        status=status,
    )


def _json_body(request: HttpRequest) -> dict[str, object] | None:
    try:
        value = json.loads(request.body or b"{}")
    except (JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


@require_GET
@never_cache
@ensure_csrf_cookie
def session(request: HttpRequest) -> JsonResponse:
    """Return the browser session and bootstrap its CSRF cookie."""

    get_token(request)
    return JsonResponse(_identity(request))


@require_POST
@never_cache
@ensure_csrf_cookie
@csrf_protect
@sensitive_post_parameters("password")
def login_session(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    if payload is None:
        return _problem(
            status=400,
            code="invalid-request",
            detail="The login request must be a JSON object.",
        )

    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not username.strip():
        return _problem(
            status=400,
            code="invalid-username",
            detail="Username is required.",
        )
    if not isinstance(password, str) or not password:
        return _problem(
            status=400,
            code="invalid-password",
            detail="Password is required.",
        )

    user = authenticate(request, username=username.strip(), password=password)
    if user is None:
        return _problem(
            status=401,
            code="invalid-credentials",
            detail="The username or password is incorrect.",
        )

    login(request, user)
    if not bool(payload.get("remember", False)):
        request.session.set_expiry(0)
    get_token(request)
    return JsonResponse(_identity(request))


@require_POST
@never_cache
@ensure_csrf_cookie
@csrf_protect
def logout_session(request: HttpRequest) -> JsonResponse:
    logout(request)
    get_token(request)
    return JsonResponse({"authenticated": False, "user": None})
