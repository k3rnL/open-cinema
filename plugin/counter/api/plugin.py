"""Version-2 counter example using core storage and declarative administration UI."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.urls import path
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods

from core.plugin_system import (
    AdminUICapability,
    ApiCapability,
    AutomationCapability,
    OpenCinemaPlugin,
    RuntimePluginIdentity,
)
from core.plugin_system.storage import (
    PLUGIN_STORAGE_SCHEMAS,
    PluginDocumentRepository,
    PluginStorageNotFoundError,
    StalePluginStateError,
)
from opencinema.version import __version__

COUNTER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["value", "totalActions", "history"],
    "properties": {
        "value": {"type": "integer"},
        "totalActions": {"type": "integer", "minimum": 0},
        "history": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "value", "comment", "timestamp"],
                "properties": {
                    "action": {"enum": ["INCREMENT", "DECREMENT", "RESET"]},
                    "value": {"type": "integer"},
                    "comment": {"type": "string", "maxLength": 512},
                    "timestamp": {"type": "string", "maxLength": 64},
                },
            },
        },
    },
}

COUNTER_UI = {
    "schemaVersion": 1,
    "navigation": [
        {
            "id": "counter.navigation",
            "label": "Counter example",
            "pageId": "counter.overview",
            "icon": "experiment",
            "order": 900,
        }
    ],
    "pages": [
        {
            "id": "counter.overview",
            "title": "Counter example",
            "description": (
                "A minimal version-2 plugin demonstrating API, automation, "
                "storage, and UI contributions."
            ),
            "template": "overview",
            "binding": {"read": "/api/plugins/counter/", "freshnessMs": 5000},
            "sections": [
                {
                    "id": "counter.status",
                    "title": "Current state",
                    "presentation": "status",
                    "fields": [
                        {
                            "id": "counter.value",
                            "path": "/value",
                            "label": "Value",
                            "widget": "number",
                            "readOnly": True,
                        },
                        {
                            "id": "counter.total-actions",
                            "path": "/totalActions",
                            "label": "Actions",
                            "widget": "number",
                            "readOnly": True,
                        },
                    ],
                }
            ],
            "actions": [
                {
                    "id": "counter.increment",
                    "label": "Increment",
                    "method": "POST",
                    "endpoint": "/api/plugins/counter/increment",
                    "confirmation": "none",
                    "lifecycleImpact": "hot",
                    "available": True,
                },
                {
                    "id": "counter.reset",
                    "label": "Reset",
                    "method": "POST",
                    "endpoint": "/api/plugins/counter/reset",
                    "confirmation": "confirm",
                    "lifecycleImpact": "hot",
                    "available": True,
                },
            ],
        }
    ],
}


class CounterPlugin(OpenCinemaPlugin):
    COLLECTION = "counter.state"
    DOCUMENT_ID = "current"
    SCHEMA_ID = "counter.state"

    def __init__(self) -> None:
        PLUGIN_STORAGE_SCHEMAS.register(
            plugin_id="counter",
            schema_id=self.SCHEMA_ID,
            schema_version=1,
            schema=COUNTER_SCHEMA,
        )

    @property
    def identity(self) -> RuntimePluginIdentity:
        return RuntimePluginIdentity("counter", "open-cinema", __version__)

    def capabilities(self):
        return (
            ApiCapability("counter.api", routes=self.get_urls),
            AutomationCapability(
                "counter.automation",
                hooks={"counter.current-value": self._get_current_value},
            ),
            AdminUICapability("counter.admin", descriptor=COUNTER_UI),
        )

    def get_urls(self):
        return (
            path("", self.get_counter, name="get-counter"),
            path("increment", self.increment, name="increment"),
            path("decrement", self.decrement, name="decrement"),
            path("reset", self.reset, name="reset"),
            path("history", self.get_history, name="history"),
            path("history/clear", self.clear_history, name="clear-history"),
        )

    @staticmethod
    def _empty_state() -> dict[str, object]:
        return {"value": 0, "totalActions": 0, "history": []}

    def _state(self):
        try:
            return PluginDocumentRepository.get("counter", self.COLLECTION, self.DOCUMENT_ID)
        except PluginStorageNotFoundError:
            return None

    def _get_current_value(self) -> int:
        state = self._state()
        return int(state.document["value"]) if state is not None else 0

    def _record(self, action: str, value: int, comment: str):
        if len(comment) > 512:
            raise ValueError("comment cannot exceed 512 characters")
        for _ in range(3):
            current = self._state()
            document = dict(current.document) if current is not None else self._empty_state()
            history = list(document["history"])
            history.insert(
                0,
                {
                    "action": action,
                    "value": value,
                    "comment": comment,
                    "timestamp": timezone.now().isoformat(),
                },
            )
            document.update(
                {
                    "value": value,
                    "totalActions": int(document["totalActions"]) + 1,
                    "history": history[:100],
                }
            )
            try:
                return PluginDocumentRepository.put(
                    plugin_id="counter",
                    collection=self.COLLECTION,
                    document_id=self.DOCUMENT_ID,
                    schema_id=self.SCHEMA_ID,
                    schema_version=1,
                    document=document,
                    schema=COUNTER_SCHEMA,
                    expected_version=current.update_version if current is not None else None,
                )
            except StalePluginStateError:
                continue
        raise StalePluginStateError("counter state changed repeatedly; retry the action")

    @staticmethod
    def _body(request) -> dict[str, object]:
        if not request.body:
            return {}
        value = json.loads(request.body)
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    @method_decorator(require_http_methods(["GET"]))
    def get_counter(self, request):
        state = self._state()
        document = dict(state.document) if state is not None else self._empty_state()
        return JsonResponse(
            {
                "value": document["value"],
                "totalActions": document["totalActions"],
                "updateVersion": state.update_version if state is not None else 0,
            }
        )

    @method_decorator(require_http_methods(["POST"]))
    def increment(self, request):
        body = self._body(request)
        previous = self._get_current_value()
        current = self._record("INCREMENT", previous + 1, str(body.get("comment", "")))
        return JsonResponse(
            {
                "action": "INCREMENT",
                "previousValue": previous,
                "newValue": current.document["value"],
                "updateVersion": current.update_version,
            }
        )

    @method_decorator(require_http_methods(["POST"]))
    def decrement(self, request):
        body = self._body(request)
        previous = self._get_current_value()
        current = self._record("DECREMENT", previous - 1, str(body.get("comment", "")))
        return JsonResponse(
            {
                "action": "DECREMENT",
                "previousValue": previous,
                "newValue": current.document["value"],
                "updateVersion": current.update_version,
            }
        )

    @method_decorator(require_http_methods(["POST"]))
    def reset(self, request):
        body = self._body(request)
        previous = self._get_current_value()
        current = self._record("RESET", 0, str(body.get("comment", "Counter reset")))
        return JsonResponse(
            {
                "action": "RESET",
                "previousValue": previous,
                "newValue": 0,
                "updateVersion": current.update_version,
            }
        )

    @method_decorator(require_http_methods(["GET"]))
    def get_history(self, request):
        state = self._state()
        history = list(state.document["history"]) if state is not None else []
        try:
            limit = int(request.GET.get("limit", 50))
        except (TypeError, ValueError) as error:
            raise ValueError("limit must be an integer") from error
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return JsonResponse({"count": min(len(history), limit), "history": history[:limit]})

    @method_decorator(require_http_methods(["DELETE"]))
    def clear_history(self, request):
        current = self._state()
        if current is None:
            return JsonResponse({"deletedCount": 0})
        deleted_count = len(current.document["history"])
        document = dict(current.document)
        document["history"] = []
        PluginDocumentRepository.put(
            plugin_id="counter",
            collection=self.COLLECTION,
            document_id=self.DOCUMENT_ID,
            schema_id=self.SCHEMA_ID,
            schema_version=1,
            document=document,
            schema=COUNTER_SCHEMA,
            expected_version=current.update_version,
        )
        return JsonResponse({"deletedCount": deleted_count})
