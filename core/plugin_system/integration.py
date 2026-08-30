from __future__ import annotations

import uuid
from functools import wraps
from time import monotonic

from django.conf import settings
from django.http import JsonResponse
from django.urls import URLPattern, URLResolver, include, path
from django.views.decorators.csrf import csrf_protect

from .contracts import PluginHealth, PluginLifecycleState
from .v2_contracts import ApiCapability, AutomationCapability, PluginDesiredState
from .v2_registry import (
    PluginCapabilityRecord,
    PluginDistributionRecord,
    PluginDistributionRegistry,
)


def _problem(
    *,
    status: int,
    code: str,
    detail: str,
    correlation_id: str | None = None,
) -> JsonResponse:
    document = {
        "type": f"https://open-cinema.invalid/problems/{code}",
        "title": code.replace("-", " ").title(),
        "status": status,
        "code": code,
        "detail": detail,
    }
    if correlation_id is not None:
        document["correlationId"] = correlation_id
    return JsonResponse(document, status=status, content_type="application/problem+json")


def _guard_view(
    record: PluginDistributionRecord,
    capability: PluginCapabilityRecord,
    view,
):
    timeout_seconds = float(getattr(settings, "OPEN_CINEMA_PLUGIN_ROUTE_TIMEOUT_SECONDS", 5.0))

    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return _problem(
                status=401,
                code="authentication-required",
                detail="Plugin APIs require an authenticated Open Cinema session.",
            )
        if record.desired_state is not PluginDesiredState.ENABLED:
            return _problem(
                status=503,
                code="plugin-disabled",
                detail=f"Plugin {record.manifest.plugin_id!r} is disabled.",
            )
        if record.state not in {
            PluginLifecycleState.AVAILABLE,
            PluginLifecycleState.STARTED,
        }:
            return _problem(
                status=503,
                code="plugin-unavailable",
                detail=f"Plugin {record.manifest.plugin_id!r} is not available.",
            )
        if capability.health not in {PluginHealth.HEALTHY, PluginHealth.DEGRADED}:
            return _problem(
                status=503,
                code="plugin-capability-unavailable",
                detail=f"Capability {capability.declaration.capability_id!r} is unavailable.",
            )
        correlation_id = str(uuid.uuid4())
        started = monotonic()
        try:
            response = view(request, *args, **kwargs)
        except Exception as error:
            from open_cinema_plugin_sdk.errors import PluginConcurrencyError

            from .storage import PluginStorageNotFoundError, StalePluginStateError

            if isinstance(error, PluginStorageNotFoundError):
                return _problem(
                    status=404,
                    code="plugin-resource-not-found",
                    detail=str(error),
                    correlation_id=correlation_id,
                )
            if isinstance(error, (PluginConcurrencyError, StalePluginStateError)):
                return _problem(
                    status=409,
                    code="stale-plugin-resource",
                    detail=str(error),
                    correlation_id=correlation_id,
                )
            if isinstance(error, PermissionError):
                return _problem(
                    status=403,
                    code="plugin-resource-forbidden",
                    detail=str(error),
                    correlation_id=correlation_id,
                )
            if isinstance(error, (TypeError, ValueError)):
                return _problem(
                    status=422,
                    code="plugin-request-invalid",
                    detail=str(error),
                    correlation_id=correlation_id,
                )
            capability.health = PluginHealth.DEGRADED
            capability.diagnostic(
                record.manifest.plugin_id,
                "plugin-route-failed",
                str(error),
                exception=type(error).__name__,
                correlationId=correlation_id,
            )
            return _problem(
                status=500,
                code="plugin-route-failed",
                detail="The plugin route failed. Use the correlation ID in Plugins diagnostics.",
                correlation_id=correlation_id,
            )
        elapsed = monotonic() - started
        if elapsed > timeout_seconds:
            capability.health = PluginHealth.DEGRADED
            capability.diagnostic(
                record.manifest.plugin_id,
                "plugin-route-timeout",
                f"Plugin route exceeded {timeout_seconds} seconds.",
                elapsedSeconds=elapsed,
                correlationId=correlation_id,
            )
            return _problem(
                status=504,
                code="plugin-route-timeout",
                detail="The plugin route exceeded its deadline.",
                correlation_id=correlation_id,
            )
        response["Open-Cinema-Plugin"] = record.manifest.plugin_id
        return response

    return csrf_protect(guarded)


def _guard_patterns(
    record: PluginDistributionRecord,
    capability: PluginCapabilityRecord,
    patterns,
) -> list[URLPattern | URLResolver]:
    guarded_patterns: list[URLPattern | URLResolver] = []
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            guarded_patterns.append(
                URLPattern(
                    pattern.pattern,
                    _guard_view(record, capability, pattern.callback),
                    pattern.default_args,
                    pattern.name,
                )
            )
        elif isinstance(pattern, URLResolver):
            guarded_patterns.append(
                URLResolver(
                    pattern.pattern,
                    _guard_patterns(record, capability, pattern.url_patterns),
                    pattern.default_kwargs,
                    pattern.app_name,
                    pattern.namespace,
                )
            )
        else:
            raise TypeError("plugin routes must contain Django URLPattern values")
    return guarded_patterns


def plugin_api_urlpatterns(registry: PluginDistributionRegistry):
    patterns = []
    for record, capability_record in registry.capability_records(ApiCapability):
        contribution = capability_record.contribution
        if not isinstance(contribution, ApiCapability):
            continue
        plugin_patterns = _guard_patterns(record, capability_record, contribution.routes())
        patterns.append(
            path(
                f"plugins/{record.manifest.plugin_id}/",
                include((plugin_patterns, record.manifest.plugin_id)),
            )
        )
    return patterns


class PluginAutomationRegistry:
    def __init__(self, plugins: PluginDistributionRegistry) -> None:
        self.plugins = plugins
        self._hooks: dict[
            str,
            tuple[PluginDistributionRecord, PluginCapabilityRecord, object],
        ] = {}

    def refresh(self) -> None:
        hooks = {}
        for record, capability_record in self.plugins.capability_records(AutomationCapability):
            contribution = capability_record.contribution
            if not isinstance(contribution, AutomationCapability):
                continue
            for automation_id, hook in contribution.hooks.items():
                if automation_id in hooks:
                    capability_record.health = PluginHealth.FAILED
                    capability_record.diagnostic(
                        record.manifest.plugin_id,
                        "duplicate-automation-id",
                        "Another enabled plugin already owns this automation ID.",
                    )
                    continue
                hooks[automation_id] = (record, capability_record, hook)
        self._hooks = hooks

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._hooks))

    def invoke(self, automation_id: str, *args, **kwargs):
        try:
            record, capability, hook = self._hooks[automation_id]
        except KeyError as error:
            raise KeyError(f"automation {automation_id!r} is unavailable") from error
        if record.desired_state is not PluginDesiredState.ENABLED:
            raise PermissionError(f"plugin {record.manifest.plugin_id!r} is disabled")
        if capability.health not in {PluginHealth.HEALTHY, PluginHealth.DEGRADED}:
            raise RuntimeError(
                f"automation capability {capability.declaration.capability_id!r} failed"
            )
        try:
            return hook(*args, **kwargs)
        except Exception as error:
            capability.health = PluginHealth.DEGRADED
            capability.diagnostic(
                record.manifest.plugin_id,
                "plugin-automation-failed",
                str(error),
                exception=type(error).__name__,
                automationId=automation_id,
            )
            raise
