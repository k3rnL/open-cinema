from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from jsonschema import Draft202012Validator

from core.orchestration.graph_schema import desired_graph_schema

from . import API_MEDIA_TYPE, API_VERSION, PROBLEM_MEDIA_TYPE

_BASE = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


def _object(required, properties, *, additional=False):
    return {
        **_BASE,
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": additional,
    }


@lru_cache(maxsize=1)
def api_json_schemas() -> dict[str, dict[str, object]]:
    identifier = {"type": "string", "format": "uuid"}
    version = {"type": "integer", "minimum": 0}
    explanation_presentation = _object(
        [
            "schemaVersion",
            "headline",
            "route",
            "selection",
            "alternatives",
            "signals",
            "processors",
            "overrides",
            "transition",
            "errors",
            "technicalReferences",
        ],
        {
            "schemaVersion": {"const": 1},
            "headline": _object(
                ["status", "title", "summary"],
                {
                    "status": {"enum": ["active", "inactive", "waiting", "degraded", "failed"]},
                    "title": {"type": "string", "minLength": 1},
                    "summary": {"type": "string", "minLength": 1},
                },
            ),
            "route": {
                "type": "array",
                "items": _object(
                    ["kind", "name", "role", "detail", "referenceId", "nodeId"],
                    {
                        "kind": {"enum": ["endpoint", "processor"]},
                        "name": {"type": "string", "minLength": 1},
                        "role": {"enum": ["source", "decode", "process", "output"]},
                        "detail": {"type": ["string", "null"]},
                        "referenceId": {"type": ["string", "null"]},
                        "nodeId": {"type": "string", "minLength": 1},
                    },
                ),
            },
            "selection": {"type": "object"},
            "alternatives": {"type": "array", "items": {"type": "object"}},
            "signals": {"type": "object"},
            "processors": {"type": "array", "items": {"type": "object"}},
            "overrides": {"type": "array", "items": {"type": "object"}},
            "transition": _object(
                ["status", "durationMs", "observedAt", "message"],
                {
                    "status": {"type": "string", "minLength": 1},
                    "durationMs": {"type": ["integer", "null"], "minimum": 0},
                    "observedAt": {"type": ["string", "null"], "format": "date-time"},
                    "message": {"type": ["string", "null"]},
                },
            ),
            "errors": {"type": "array", "items": {"type": "object"}},
            "technicalReferences": {"type": "object"},
        },
    )
    schemas = {
        "Problem": _object(
            ["type", "title", "status", "detail", "code", "instance", "apiVersion"],
            {
                "type": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "integer", "minimum": 400, "maximum": 599},
                "detail": {"type": "string"},
                "code": {"type": "string"},
                "instance": {"type": "string"},
                "apiVersion": {"const": API_VERSION},
                "errors": {},
                "currentVersion": version,
            },
        ),
        "GraphDefinition": _object(
            ["id", "name", "kind", "ownerId", "labels", "desiredStateVersion"],
            {
                "id": identifier,
                "name": {"type": "string", "minLength": 1},
                "kind": {"enum": ["graph", "subgraph"]},
                "ownerId": identifier,
                "labels": {"type": "object", "additionalProperties": {"type": "string"}},
                "createdAt": {"type": ["string", "null"], "format": "date-time"},
                "updatedAt": {"type": ["string", "null"], "format": "date-time"},
                "archivedAt": {"type": ["string", "null"], "format": "date-time"},
                "activeRevisionId": {"type": ["string", "null"], "format": "uuid"},
                "desiredStateVersion": version,
            },
        ),
        "GraphRevision": _object(
            [
                "id",
                "definitionId",
                "revisionNumber",
                "schemaVersion",
                "state",
                "contentDigest",
                "updateVersion",
            ],
            {
                "id": identifier,
                "definitionId": identifier,
                "revisionNumber": {"type": "integer", "minimum": 1},
                "schemaVersion": {"const": 1},
                "state": {"enum": ["draft", "published"]},
                "authorId": identifier,
                "contentDigest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "validation": {"type": "object"},
                "updateVersion": {"type": "integer", "minimum": 1},
                "createdAt": {"type": ["string", "null"], "format": "date-time"},
                "publishedAt": {"type": ["string", "null"], "format": "date-time"},
                "content": deepcopy(desired_graph_schema()),
            },
        ),
        "GraphActivation": _object(
            ["definitionId", "revisionId", "desiredStateVersion"],
            {
                "id": identifier,
                "definitionId": identifier,
                "revisionId": {"type": ["string", "null"], "format": "uuid"},
                "parameterBindings": {"type": "object"},
                "sceneBindings": {"type": "object"},
                "desiredStateVersion": version,
                "activatedAt": {"type": ["string", "null"], "format": "date-time"},
                "updatedAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "LogicalEndpoint": _object(
            ["id", "name", "direction", "selector", "tags", "groups", "updateVersion"],
            {
                "id": identifier,
                "name": {"type": "string", "minLength": 1},
                "ownerId": identifier,
                "direction": {"enum": ["input", "output"]},
                "selector": {"type": "object"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "groups": {"type": "array", "items": {"type": "string"}},
                "policyMetadata": {"type": "object"},
                "explicitBinding": {"type": ["object", "null"]},
                "lastKnown": {"type": "object"},
                "updateVersion": {"type": "integer", "minimum": 1},
                "createdAt": {"type": ["string", "null"], "format": "date-time"},
                "updatedAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "MasterAudioLevel": _object(
            [
                "schemaVersion",
                "scope",
                "desired",
                "effective",
                "observed",
                "writable",
                "applying",
                "degraded",
                "runtimeVersion",
                "updateVersion",
                "updatedAt",
            ],
            {
                "schemaVersion": {"const": 1},
                "scope": {"const": "master-output"},
                "desired": {"$ref": "#/$defs/AudioLevelValue"},
                "effective": {"type": "object"},
                "observed": {"type": "object"},
                "writable": {"type": "boolean"},
                "applying": {"type": "boolean"},
                "degraded": {"type": "array", "items": {"type": "object"}},
                "runtimeVersion": {"type": ["string", "null"]},
                "updateVersion": {"type": "integer", "minimum": 1},
                "updatedAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "EndpointAudioLevel": _object(
            [
                "schemaVersion",
                "scope",
                "endpointId",
                "direction",
                "availability",
                "desired",
                "master",
                "effective",
                "observed",
                "capabilities",
                "applying",
                "degraded",
                "runtimeVersion",
                "updateVersion",
                "updatedAt",
            ],
            {
                "schemaVersion": {"const": 1},
                "scope": {"enum": ["device-level", "input-level"]},
                "endpointId": identifier,
                "direction": {"enum": ["input", "output"]},
                "availability": {"enum": ["available", "unavailable", "ambiguous", "invalid"]},
                "desired": {"$ref": "#/$defs/AudioLevelValue"},
                "master": {"type": ["object", "null"]},
                "effective": {"$ref": "#/$defs/AudioLevelValue"},
                "observed": {"type": "object"},
                "capabilities": {"type": "object"},
                "applying": {"type": "boolean"},
                "degraded": {"type": "array", "items": {"type": "object"}},
                "runtimeVersion": {"type": ["string", "null"]},
                "updateVersion": {"type": "integer", "minimum": 1},
                "updatedAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "ManagedResourcePresentation": _object(
            [
                "schemaVersion",
                "id",
                "resourceType",
                "name",
                "kind",
                "version",
                "versionStatus",
                "desired",
                "observed",
                "freshness",
                "actions",
                "correlations",
            ],
            {
                "schemaVersion": {"const": 1},
                "id": {"type": "string"},
                "resourceType": {"enum": ["adapter", "processor"]},
                "name": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "minLength": 1},
                "version": {"type": ["string", "null"]},
                "versionStatus": {"enum": ["known", "unknown"]},
                "desired": {"type": "object"},
                "observed": {"type": "object"},
                "freshness": {"type": "object"},
                "actions": {"type": "array", "items": {"type": "object"}},
                "correlations": {"type": "array", "items": {"type": "object"}},
            },
        ),
        "RuntimeExplanationPresentation": deepcopy(explanation_presentation),
        "ManagedAudioAdapter": _object(
            ["id", "ownerId", "schemaVersion", "desired", "observed"],
            {
                "id": identifier,
                "ownerId": identifier,
                "schemaVersion": {"const": 1},
                "desired": _object(
                    [
                        "name",
                        "kind",
                        "configuration",
                        "enabled",
                        "restartGeneration",
                        "updateVersion",
                    ],
                    {
                        "name": {"type": "string", "minLength": 1},
                        "kind": {
                            "enum": [
                                "roc-receiver",
                                "roc-sender",
                                "debug-file-source",
                                "debug-file-recorder",
                            ]
                        },
                        "configuration": {"type": "object"},
                        "enabled": {"type": "boolean"},
                        "restartGeneration": version,
                        "updateVersion": {"type": "integer", "minimum": 1},
                        "createdAt": {"type": ["string", "null"], "format": "date-time"},
                        "updatedAt": {"type": ["string", "null"], "format": "date-time"},
                    },
                ),
                "observed": {"type": "object"},
            },
        ),
        "ResolvedPlan": _object(
            [
                "id",
                "schemaVersion",
                "definitionId",
                "revisionId",
                "desiredStateVersion",
                "worldGeneration",
                "worldSequence",
                "resolutionMode",
                "status",
                "document",
                "explanation",
                "planDigest",
            ],
            {
                "id": identifier,
                "schemaVersion": {"const": 1},
                "definitionId": identifier,
                "revisionId": identifier,
                "desiredStateVersion": version,
                "worldGeneration": version,
                "worldSequence": version,
                "runtimeVersion": {"type": ["string", "null"]},
                "resolutionMode": {"enum": ["live", "shadow"]},
                "status": {"enum": ["resolved", "waiting", "degraded", "conflicted", "invalid"]},
                "document": {"type": "object"},
                "explanation": _object(
                    ["presentation"],
                    {"presentation": deepcopy(explanation_presentation)},
                    additional=True,
                ),
                "planDigest": {"type": "string"},
                "correlationId": identifier,
                "applied": {"type": "object"},
                "createdAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "RuntimeProjection": _object(
            ["id", "type", "subject", "worldGeneration", "worldSequence", "payload"],
            {
                "id": identifier,
                "type": {"type": "string"},
                "subject": {"type": "string"},
                "worldGeneration": version,
                "worldSequence": version,
                "payload": {"type": "object"},
                "current": {"type": "boolean"},
                "observedAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
        "SpeakerTest": _object(
            [
                "active",
                "token",
                "runtimeKey",
                "outputName",
                "channel",
                "startedAt",
                "endsAt",
                "durationMs",
            ],
            {
                "active": {"type": "boolean"},
                "token": {"type": ["string", "null"], "format": "uuid"},
                "runtimeKey": {"type": ["string", "null"]},
                "outputName": {"type": ["string", "null"]},
                "channel": {"type": ["string", "null"]},
                "startedAt": {"type": ["string", "null"], "format": "date-time"},
                "endsAt": {"type": ["string", "null"], "format": "date-time"},
                "durationMs": {"type": ["integer", "null"], "minimum": 250, "maximum": 5000},
            },
        ),
        "SpeakerTestOutput": _object(
            [
                "runtimeKey",
                "runtimeGeneration",
                "name",
                "description",
                "targetName",
                "channels",
                "rate",
            ],
            {
                "runtimeKey": {"type": "string"},
                "runtimeGeneration": {"type": "integer", "minimum": 1},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "targetName": {"type": "string"},
                "channels": {
                    "type": "array",
                    "minItems": 1,
                    "items": _object(
                        ["position", "label"],
                        {
                            "position": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                        },
                    ),
                },
                "rate": {"type": "integer", "minimum": 8000, "maximum": 384000},
            },
        ),
        "ManualOverride": _object(
            [
                "id",
                "mutationKind",
                "persistentDesiredChange",
                "scopeType",
                "scopeId",
                "priority",
                "reason",
                "active",
            ],
            {
                "id": identifier,
                "mutationKind": {"const": "temporaryOverride"},
                "persistentDesiredChange": {"const": False},
                "scopeType": {
                    "enum": ["endpoint", "scene", "volume", "mute", "route", "graph_parameter"]
                },
                "scopeId": {"type": "string", "minLength": 1},
                "value": {},
                "priority": {"type": "integer"},
                "creatorId": identifier,
                "reason": {"type": "string", "minLength": 1},
                "startsAt": {"type": ["string", "null"], "format": "date-time"},
                "expiresAt": {"type": ["string", "null"], "format": "date-time"},
                "cancelledAt": {"type": ["string", "null"], "format": "date-time"},
                "active": {"type": "boolean"},
            },
        ),
        "NodeType": _object(
            ["id", "version", "displayName", "category", "ports", "configurationSchema"],
            {
                "id": {"type": "string"},
                "version": {"type": "integer", "minimum": 1},
                "displayName": {"type": "string"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "ports": {"type": "array", "items": {"type": "object"}},
                "configurationSchema": {"type": "object"},
                "available": {"type": "boolean"},
                "source": {"enum": ["core", "managed", "plugin"]},
                "pluginId": {"type": ["string", "null"]},
                "ui": {"type": "object"},
            },
            additional=True,
        ),
        "CamillaDSPProfile": _object(
            [
                "id",
                "profileId",
                "version",
                "schemaVersion",
                "ownerId",
                "name",
                "contentDigest",
                "validation",
            ],
            {
                "id": identifier,
                "profileId": identifier,
                "version": {"type": "integer", "minimum": 1},
                "schemaVersion": {"const": 1},
                "ownerId": identifier,
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "contentDigest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "validation": {"type": "object"},
                "createdAt": {"type": ["string", "null"], "format": "date-time"},
                "content": {"type": "object"},
            },
        ),
        "OrchestrationEvent": _object(
            ["sequence", "id", "correlationId", "type", "severity", "payload", "occurredAt"],
            {
                "sequence": {"type": "integer", "minimum": 1},
                "id": identifier,
                "correlationId": identifier,
                "definitionId": {"type": ["string", "null"], "format": "uuid"},
                "type": {"type": "string"},
                "severity": {"enum": ["debug", "info", "warning", "error"]},
                "payload": {"type": "object"},
                "occurredAt": {"type": ["string", "null"], "format": "date-time"},
            },
        ),
    }
    schemas["SpeakerTestOverview"] = _object(
        ["outputs", "active"],
        {
            "outputs": {
                "type": "array",
                "items": deepcopy(schemas["SpeakerTestOutput"]),
            },
            "active": deepcopy(schemas["SpeakerTest"]),
        },
    )
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    audio_level_value = _object(
        ["level", "muted"],
        {
            "level": {"type": "number", "minimum": 0, "maximum": 1},
            "muted": {"type": "boolean"},
        },
    )
    for schema in schemas.values():
        schema.setdefault("$defs", {})["AudioLevelValue"] = audio_level_value
    return schemas


_PATHS = (
    "/schema",
    "/schemas",
    "/openapi.json",
    "/graphs",
    "/subgraphs",
    "/graphs/import",
    "/graphs/{definitionId}",
    "/graphs/{definitionId}/revisions",
    "/graphs/{definitionId}/activation",
    "/revisions/{revisionId}",
    "/revisions/{revisionId}/validate",
    "/revisions/{revisionId}/compare",
    "/revisions/{revisionId}/publish",
    "/revisions/{revisionId}/activate",
    "/revisions/{revisionId}/export",
    "/revisions/{revisionId}/dry-run",
    "/node-types",
    "/adapter-types",
    "/adapters",
    "/adapters/{adapterId}",
    "/adapters/{adapterId}/restart",
    "/camilladsp/profiles",
    "/camilladsp/profiles/{revisionId}",
    "/endpoints",
    "/levels/master",
    "/endpoints/{endpointId}",
    "/endpoints/{endpointId}/candidates",
    "/endpoints/{endpointId}/binding",
    "/endpoints/{endpointId}/level",
    "/endpoints/selector-preview",
    "/endpoint-candidates",
    "/plans/current",
    "/plans/history",
    "/plans/{planId}",
    "/plans/dry-run",
    "/runtime/snapshot",
    "/runtime/resources",
    "/runtime/processors",
    "/runtime/readiness",
    "/runtime/diagnostics",
    "/speaker-test",
    "/overrides",
    "/overrides/{overrideId}/cancel",
    "/events",
)


@lru_cache(maxsize=1)
def openapi_document() -> dict[str, object]:
    mutating = {
        "/graphs": {"post"},
        "/subgraphs": {"post"},
        "/graphs/import": {"post"},
        "/graphs/{definitionId}/revisions": {"post"},
        "/graphs/{definitionId}/activation": {"delete"},
        "/camilladsp/profiles": {"post"},
        "/revisions/{revisionId}": {"patch", "delete"},
        "/revisions/{revisionId}/validate": {"post"},
        "/revisions/{revisionId}/publish": {"post"},
        "/revisions/{revisionId}/activate": {"post"},
        "/revisions/{revisionId}/dry-run": {"post"},
        "/endpoints": {"post"},
        "/endpoints/{endpointId}": {"patch"},
        "/levels/master": {"patch"},
        "/endpoints/{endpointId}/level": {"patch"},
        "/endpoints/{endpointId}/binding": {"post"},
        "/endpoints/selector-preview": {"post"},
        "/plans/dry-run": {"post"},
        "/overrides": {"post"},
        "/overrides/{overrideId}/cancel": {"post"},
        "/adapters": {"post"},
        "/adapters/{adapterId}": {"patch", "delete"},
        "/adapters/{adapterId}/restart": {"post"},
        "/speaker-test": {"post", "delete"},
    }
    read_only = {
        "/schema",
        "/schemas",
        "/openapi.json",
        "/graphs",
        "/subgraphs",
        "/graphs/{definitionId}",
        "/graphs/{definitionId}/revisions",
        "/graphs/{definitionId}/activation",
        "/revisions/{revisionId}",
        "/revisions/{revisionId}/compare",
        "/revisions/{revisionId}/export",
        "/node-types",
        "/adapter-types",
        "/adapters",
        "/adapters/{adapterId}",
        "/camilladsp/profiles",
        "/camilladsp/profiles/{revisionId}",
        "/endpoints",
        "/endpoints/{endpointId}",
        "/levels/master",
        "/endpoints/{endpointId}/candidates",
        "/endpoint-candidates",
        "/endpoints/{endpointId}/level",
        "/plans/current",
        "/plans/history",
        "/plans/{planId}",
        "/runtime/snapshot",
        "/runtime/resources",
        "/runtime/processors",
        "/runtime/readiness",
        "/runtime/diagnostics",
        "/speaker-test",
        "/overrides",
        "/events",
    }
    response_components = {
        "/graphs": "GraphDefinition",
        "/subgraphs": "GraphDefinition",
        "/graphs/{definitionId}": "GraphDefinition",
        "/graphs/{definitionId}/revisions": "GraphRevision",
        "/graphs/{definitionId}/activation": "GraphActivation",
        "/revisions/{revisionId}": "GraphRevision",
        "/revisions/{revisionId}/publish": "GraphRevision",
        "/revisions/{revisionId}/activate": "GraphActivation",
        "/node-types": "NodeType",
        "/adapters": "ManagedAudioAdapter",
        "/adapters/{adapterId}": "ManagedAudioAdapter",
        "/adapters/{adapterId}/restart": "ManagedAudioAdapter",
        "/camilladsp/profiles": "CamillaDSPProfile",
        "/camilladsp/profiles/{revisionId}": "CamillaDSPProfile",
        "/endpoints": "LogicalEndpoint",
        "/endpoints/{endpointId}": "LogicalEndpoint",
        "/levels/master": "MasterAudioLevel",
        "/endpoints/{endpointId}/level": "EndpointAudioLevel",
        "/runtime/resources": "ManagedResourcePresentation",
        "/plans/history": "ResolvedPlan",
        "/plans/{planId}": "ResolvedPlan",
        "/overrides": "ManualOverride",
        "/overrides/{overrideId}/cancel": "ManualOverride",
        "/speaker-test": "SpeakerTest",
    }
    collection_paths = {
        "/graphs",
        "/subgraphs",
        "/graphs/{definitionId}/revisions",
        "/node-types",
        "/adapter-types",
        "/adapters",
        "/camilladsp/profiles",
        "/endpoints",
        "/plans/history",
        "/overrides",
        "/runtime/resources",
    }
    created_operations = {
        ("/graphs", "post"),
        ("/subgraphs", "post"),
        ("/graphs/import", "post"),
        ("/graphs/{definitionId}/revisions", "post"),
        ("/camilladsp/profiles", "post"),
        ("/endpoints", "post"),
        ("/overrides", "post"),
        ("/adapters", "post"),
    }
    precondition_operations = {
        ("/revisions/{revisionId}", "patch"),
        ("/revisions/{revisionId}", "delete"),
        ("/revisions/{revisionId}/publish", "post"),
        ("/revisions/{revisionId}/activate", "post"),
        ("/graphs/{definitionId}/activation", "delete"),
        ("/endpoints/{endpointId}", "patch"),
        ("/levels/master", "patch"),
        ("/endpoints/{endpointId}/level", "patch"),
        ("/endpoints/{endpointId}/binding", "post"),
        ("/adapters/{adapterId}", "patch"),
        ("/adapters/{adapterId}", "delete"),
        ("/adapters/{adapterId}/restart", "post"),
    }
    paths = {}
    for path in _PATHS:
        methods = set(mutating.get(path, ()))
        if path in read_only or not methods:
            methods.add("get")
        operations = {}
        for method in sorted(methods):
            status_code = "201" if (path, method) in created_operations else "200"
            component = response_components.get(path)
            if path == "/speaker-test" and method == "get":
                component = "SpeakerTestOverview"
            response_schema: dict[str, object] = {"type": "object"}
            if component is not None:
                response_schema = {"$ref": f"#/components/schemas/{component}"}
                if path in collection_paths and method == "get":
                    response_schema = {
                        "type": "object",
                        "required": ["items"],
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": response_schema,
                            },
                            "pagination": {"type": "object"},
                        },
                    }
            operation = {
                "operationId": (
                    method
                    + path.replace("/", "_")
                    .replace("{", "")
                    .replace("}", "")
                    .replace(".", "_")
                    .strip("_")
                ),
                "responses": {
                    status_code: {
                        "description": "Successful orchestration response",
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
                "security": [{"session": []}],
            }
            if method in {"post", "patch"}:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"type": "object"}},
                        API_MEDIA_TYPE: {"schema": {"type": "object"}},
                    },
                }
            if (path, method) in precondition_operations:
                operation["parameters"] = [
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": '^(W/)?"?[0-9]+"?$',
                        },
                    }
                ]
            if path in collection_paths and method == "get":
                operation.setdefault("parameters", []).extend(
                    [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 100},
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 0},
                        },
                    ]
                )
            if path == "/events":
                operation["responses"]["200"] = {
                    "description": "Resumable server-sent event stream",
                    "content": {"text/event-stream": {"schema": {"type": "string"}}},
                }
                operation["parameters"] = [
                    {
                        "name": "Last-Event-ID",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "integer", "minimum": 0},
                    }
                ]
            operations[method] = operation
        paths[path] = operations
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Open Cinema audio orchestration API",
            "version": "1.0.0",
        },
        "servers": [{"url": "/api/audio/v1"}],
        "paths": paths,
        "components": {
            "securitySchemes": {"session": {"type": "apiKey", "in": "cookie", "name": "sessionid"}},
            "schemas": deepcopy(api_json_schemas()),
        },
    }


def schema_metadata() -> dict[str, object]:
    return {
        "service": "open-cinema-audio-orchestration",
        "apiVersion": API_VERSION,
        "schemaVersion": 1,
        "supportedApiVersions": [API_VERSION],
        "mediaType": API_MEDIA_TYPE,
        "problemMediaType": PROBLEM_MEDIA_TYPE,
        "desiredGraphSchemaVersion": 1,
        "resolverReplaySchemaVersion": 1,
        "eventSchemaVersion": 1,
        "conventions": {
            "pagination": {"parameters": ["limit", "offset"], "maximumLimit": 100},
            "optimisticConcurrency": {
                "requestHeader": "If-Match",
                "responseHeader": "ETag",
                "conflictStatus": 412,
                "missingStatus": 428,
            },
            "eventResumption": {
                "requestHeader": "Last-Event-ID",
                "gapEvent": "snapshot",
            },
        },
        "links": {
            "schemas": "/api/audio/v1/schemas",
            "openapi": "/api/audio/v1/openapi.json",
            "events": "/api/audio/v1/events",
            "readiness": "/api/audio/v1/runtime/readiness",
            "camilladspProfiles": "/api/audio/v1/camilladsp/profiles",
            "adapterTypes": "/api/audio/v1/adapter-types",
            "adapters": "/api/audio/v1/adapters",
            "masterAudioLevel": "/api/audio/v1/levels/master",
        },
    }
