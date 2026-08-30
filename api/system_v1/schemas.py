from __future__ import annotations

from copy import deepcopy

from . import API_MEDIA_TYPE, API_VERSION, PROBLEM_MEDIA_TYPE, SCHEMA_VERSION


def _nullable(kind: str) -> dict[str, object]:
    return {"type": [kind, "null"]}


def api_json_schemas() -> dict[str, dict[str, object]]:
    return {
        "Problem": {
            "type": "object",
            "required": ["type", "title", "status", "detail", "code", "instance", "apiVersion"],
            "properties": {
                "type": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "integer"},
                "detail": {"type": "string"},
                "code": {"type": "string"},
                "instance": {"type": "string"},
                "apiVersion": {"const": 1},
            },
        },
        "SystemOverview": {
            "type": "object",
            "required": [
                "schemaVersion",
                "observedAt",
                "hostname",
                "model",
                "operatingSystem",
                "kernel",
                "bootId",
                "uptimeSeconds",
                "storage",
                "temperatureCelsius",
                "throttling",
                "application",
                "unavailableFields",
            ],
            "properties": {
                "schemaVersion": {"const": 1},
                "observedAt": {"type": "string", "format": "date-time"},
                "hostname": _nullable("string"),
                "model": _nullable("string"),
                "operatingSystem": _nullable("string"),
                "kernel": _nullable("string"),
                "bootId": _nullable("string"),
                "uptimeSeconds": _nullable("number"),
                "storage": {"type": ["object", "null"]},
                "temperatureCelsius": _nullable("number"),
                "throttling": {"type": "object"},
                "application": {"type": "object"},
                "unavailableFields": {"type": "array", "items": {"type": "string"}},
            },
        },
        "SystemMetrics": {
            "type": "object",
            "required": [
                "schemaVersion",
                "observedAt",
                "cpuPercent",
                "memory",
                "unavailableFields",
            ],
            "properties": {
                "schemaVersion": {"const": 1},
                "observedAt": {"type": "string", "format": "date-time"},
                "cpuPercent": _nullable("number"),
                "memory": {"type": ["object", "null"]},
                "unavailableFields": {"type": "array", "items": {"type": "string"}},
            },
        },
        "Component": {
            "type": "object",
            "required": [
                "id",
                "name",
                "version",
                "versionStatus",
                "health",
                "observedAt",
                "actions",
            ],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "version": _nullable("string"),
                "versionStatus": {"enum": ["known", "unknown"]},
                "versionSource": {"type": "string"},
                "health": {"enum": ["ready", "degraded", "unknown"]},
                "observedAt": {"type": "string", "format": "date-time"},
                "actions": {"type": "array", "items": {"type": "object"}},
            },
        },
        "SystemAction": {
            "type": "object",
            "required": [
                "id",
                "label",
                "available",
                "reason",
                "actionToken",
                "method",
                "href",
            ],
            "properties": {
                "id": {"enum": ["restart", "reboot"]},
                "label": {"type": "string"},
                "available": {"type": "boolean"},
                "reason": _nullable("string"),
                "actionToken": _nullable("string"),
                "method": {"const": "POST"},
                "href": {"type": "string"},
            },
        },
        "SystemControlOperation": {
            "type": "object",
            "required": [
                "id",
                "correlationId",
                "action",
                "targetId",
                "status",
                "error",
                "requestedAt",
                "updatedAt",
                "completedAt",
                "links",
            ],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "correlationId": {"type": "string", "format": "uuid"},
                "action": {
                    "enum": [
                        "restart-open-cinema",
                        "restart-orchestrator",
                        "reboot-appliance",
                    ]
                },
                "targetId": {"type": "string"},
                "status": {
                    "enum": [
                        "requested",
                        "executing",
                        "reconnecting",
                        "succeeded",
                        "failed",
                    ]
                },
                "error": {"type": ["object", "null"]},
                "requestedAt": {"type": "string", "format": "date-time"},
                "updatedAt": {"type": "string", "format": "date-time"},
                "completedAt": _nullable("string"),
                "links": {"type": "object"},
            },
        },
    }


def schema_metadata() -> dict[str, object]:
    return {
        "service": "open-cinema-system",
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "supportedApiVersions": [API_VERSION],
        "mediaType": API_MEDIA_TYPE,
        "problemMediaType": PROBLEM_MEDIA_TYPE,
        "links": {
            "overview": "/api/system/v1/overview",
            "metrics": "/api/system/v1/metrics",
            "components": "/api/system/v1/components",
            "actions": "/api/system/v1/actions",
            "schemas": "/api/system/v1/schemas",
            "openapi": "/api/system/v1/openapi.json",
        },
    }


def openapi_document() -> dict[str, object]:
    paths = {}
    for path, component in (
        ("/overview", "SystemOverview"),
        ("/metrics", "SystemMetrics"),
        ("/components", None),
        ("/actions", None),
        ("/schema", None),
        ("/schemas", None),
    ):
        response_schema: dict[str, object] = {"type": "object"}
        if component:
            response_schema = {"$ref": f"#/components/schemas/{component}"}
        elif path in ("/components", "/actions"):
            response_schema = {
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "$ref": (
                                "#/components/schemas/Component"
                                if path == "/components"
                                else "#/components/schemas/SystemAction"
                            )
                        },
                    }
                },
            }
        paths[path] = {
            "get": {
                "operationId": "get" + path.replace("/", "_").strip("_"),
                "security": [{"session": []}],
                "responses": {
                    "200": {
                        "description": "Successful appliance response",
                        "content": {
                            API_MEDIA_TYPE: {"schema": response_schema},
                            "application/json": {"schema": response_schema},
                        },
                    },
                    "4XX": {
                        "description": "Problem response",
                        "content": {
                            PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}
                        },
                    },
                },
            }
        }
    action_request = {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["actionToken"],
                    "properties": {"actionToken": {"type": "string"}},
                }
            }
        },
    }
    action_response = {
        "202": {
            "description": "The fixed appliance operation was accepted",
            "content": {
                API_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/SystemControlOperation"}}
            },
        },
        "4XX": {
            "description": "Problem response",
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        },
    }
    paths["/components/{componentId}/actions/restart"] = {
        "post": {
            "operationId": "restartComponent",
            "security": [{"session": []}],
            "parameters": [
                {
                    "name": "componentId",
                    "in": "path",
                    "required": True,
                    "schema": {"enum": ["open-cinema", "open-cinema-orchestrator"]},
                }
            ],
            "requestBody": action_request,
            "responses": action_response,
        }
    }
    paths["/actions/reboot"] = {
        "post": {
            "operationId": "rebootAppliance",
            "security": [{"session": []}],
            "requestBody": action_request,
            "responses": action_response,
        }
    }
    paths["/operations/{operationId}"] = {
        "get": {
            "operationId": "getSystemControlOperation",
            "security": [{"session": []}],
            "parameters": [
                {
                    "name": "operationId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Current operation state",
                    "content": {
                        API_MEDIA_TYPE: {
                            "schema": {"$ref": "#/components/schemas/SystemControlOperation"}
                        }
                    },
                }
            },
        }
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Open Cinema system API", "version": "1.0.0"},
        "servers": [{"url": "/api/system/v1"}],
        "paths": paths,
        "components": {
            "securitySchemes": {"session": {"type": "apiKey", "in": "cookie", "name": "sessionid"}},
            "schemas": deepcopy(api_json_schemas()),
        },
    }
