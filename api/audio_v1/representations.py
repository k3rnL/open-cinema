from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy


def timestamp(value) -> str | None:
    return value.isoformat() if value is not None else None


def graph_document(graph) -> dict[str, object]:
    activation = getattr(graph, "activation", None)
    return {
        "id": str(graph.pk),
        "name": graph.name,
        "kind": graph.kind,
        "ownerId": str(graph.owner_id),
        "labels": graph.labels,
        "createdAt": timestamp(graph.created_at),
        "updatedAt": timestamp(graph.updated_at),
        "archivedAt": timestamp(graph.archived_at),
        "activeRevisionId": (
            str(activation.revision_id) if activation is not None and activation.enabled else None
        ),
        "desiredStateVersion": (activation.desired_state_version if activation is not None else 0),
    }


def revision_document(revision, *, include_content: bool = True) -> dict[str, object]:
    document = {
        "id": str(revision.pk),
        "definitionId": str(revision.definition_id),
        "revisionNumber": revision.revision_number,
        "schemaVersion": revision.schema_version,
        "state": revision.state,
        "authorId": str(revision.author_id),
        "contentDigest": revision.content_digest,
        "validation": revision.validation_summary,
        "updateVersion": revision.update_version,
        "createdAt": timestamp(revision.created_at),
        "publishedAt": timestamp(revision.published_at),
    }
    if include_content:
        document["content"] = revision.content
    return document


def camilladsp_profile_document(profile, *, include_content: bool = True) -> dict[str, object]:
    document = {
        "id": str(profile.pk),
        "profileId": str(profile.profile_id),
        "version": profile.version,
        "schemaVersion": profile.schema_version,
        "ownerId": str(profile.owner_id),
        "name": profile.name,
        "description": profile.description,
        "contentDigest": profile.content_digest,
        "validation": profile.validation_summary,
        "createdAt": timestamp(profile.created_at),
    }
    if include_content:
        document["content"] = profile.content
    return document


def activation_document(activation) -> dict[str, object]:
    return {
        "id": str(activation.pk),
        "definitionId": str(activation.definition_id),
        "revisionId": str(activation.revision_id) if activation.enabled else None,
        "parameterBindings": activation.parameter_bindings,
        "sceneBindings": activation.scene_bindings,
        "desiredStateVersion": activation.desired_state_version,
        "activatedAt": timestamp(activation.activated_at),
        "updatedAt": timestamp(activation.updated_at),
    }


def endpoint_document(endpoint) -> dict[str, object]:
    return {
        "id": str(endpoint.pk),
        "name": endpoint.name,
        "ownerId": str(endpoint.owner_id),
        "direction": endpoint.direction,
        "selector": endpoint.selector,
        "tags": endpoint.tags,
        "groups": endpoint.groups,
        "policyMetadata": endpoint.policy_metadata,
        "explicitBinding": endpoint.explicit_binding,
        "lastKnown": endpoint.last_known_summary,
        "updateVersion": endpoint.update_version,
        "createdAt": timestamp(endpoint.created_at),
        "updatedAt": timestamp(endpoint.updated_at),
    }


def audio_adapter_document(adapter) -> dict[str, object]:
    state = getattr(adapter, "runtime_state", None)
    observed = {
        "lifecycle": "stopped",
        "health": "unknown",
        "processId": None,
        "runtimeGeneration": 0,
        "configurationDigest": "",
        "expectedNodeName": "",
        "runtimeKey": None,
        "progress": {},
        "retryAt": None,
        "lastError": {},
        "startedAt": None,
        "observedAt": None,
        "updatedAt": None,
    }
    if state is not None:
        observed = {
            "lifecycle": state.lifecycle,
            "health": state.health,
            "processId": state.process_id,
            "runtimeGeneration": state.runtime_generation,
            "configurationDigest": state.configuration_digest,
            "expectedNodeName": state.expected_node_name,
            "runtimeKey": state.runtime_key,
            "progress": state.progress,
            "retryAt": timestamp(state.retry_at),
            "lastError": state.last_error,
            "startedAt": timestamp(state.started_at),
            "observedAt": timestamp(state.observed_at),
            "updatedAt": timestamp(state.updated_at),
        }
    return {
        "id": str(adapter.pk),
        "ownerId": str(adapter.owner_id),
        "schemaVersion": adapter.schema_version,
        "desired": {
            "name": adapter.name,
            "kind": adapter.kind,
            "configuration": adapter.configuration,
            "enabled": adapter.enabled,
            "restartGeneration": adapter.restart_generation,
            "updateVersion": adapter.update_version,
            "createdAt": timestamp(adapter.created_at),
            "updatedAt": timestamp(adapter.updated_at),
        },
        "observed": observed,
    }


def override_document(override) -> dict[str, object]:
    return {
        "id": str(override.pk),
        "mutationKind": "temporaryOverride",
        "persistentDesiredChange": False,
        "scopeType": override.scope_type,
        "scopeId": override.scope_id,
        "value": override.value,
        "priority": override.priority,
        "creatorId": str(override.creator_id),
        "reason": override.reason,
        "startsAt": timestamp(override.starts_at),
        "expiresAt": timestamp(override.expires_at),
        "cancelledAt": timestamp(override.cancelled_at),
        "cancelledById": (str(override.cancelled_by_id) if override.cancelled_by_id else None),
        "active": override.is_active(),
        "createdAt": timestamp(override.created_at),
    }


def applied_state_document(state) -> dict[str, object]:
    if state is None:
        return {
            "status": "idle",
            "currentPlanId": None,
            "previousPlanId": None,
            "transitionGeneration": 0,
            "correlationId": None,
            "lastError": None,
            "updatedAt": None,
        }
    return {
        "status": state.status,
        "currentPlanId": str(state.current_plan_id) if state.current_plan_id else None,
        "previousPlanId": (str(state.previous_plan_id) if state.previous_plan_id else None),
        "transitionGeneration": state.transition_generation,
        "correlationId": str(state.correlation_id),
        "lastError": state.last_error,
        "updatedAt": timestamp(state.updated_at),
    }


def plan_document(plan, *, applied_state=None) -> dict[str, object]:
    runtime = plan.document.get("world", {}) if isinstance(plan.document, Mapping) else {}
    explanation = deepcopy(plan.explanation)
    presentation = explanation.get("presentation") if isinstance(explanation, Mapping) else None
    if isinstance(presentation, dict):
        transition = presentation.get("transition")
        if not isinstance(transition, dict):
            transition = {}
            presentation["transition"] = transition
        applied = applied_state_document(applied_state)
        transition["status"] = applied["status"]
        transition["observedAt"] = applied["updatedAt"] or transition.get("observedAt")
        transition["message"] = (
            applied["lastError"].get("message")
            if isinstance(applied["lastError"], Mapping)
            else applied["lastError"]
        )
        if applied["status"] == "failed":
            message = transition["message"] or "The route could not be applied."
            headline = presentation.get("headline")
            if isinstance(headline, dict):
                headline.update(
                    {
                        "status": "failed",
                        "title": "The audio route failed to apply",
                        "summary": message,
                    }
                )
            errors = presentation.get("errors")
            if isinstance(errors, list):
                errors.append(
                    {
                        "stage": "reconciliation",
                        "path": "$runtime",
                        "code": "reconciliation_failed",
                        "message": message,
                        "severity": "error",
                        "nextStep": "Check the affected device or processor, then retry the graph.",
                    }
                )
    return {
        "id": str(plan.pk),
        "schemaVersion": plan.schema_version,
        "definitionId": str(plan.graph_definition_id),
        "revisionId": str(plan.graph_revision_id),
        "desiredStateVersion": plan.desired_state_version,
        "worldGeneration": plan.world_generation,
        "worldSequence": plan.world_sequence,
        "runtimeVersion": runtime.get("version"),
        "resolutionMode": plan.resolution_mode,
        "status": plan.status,
        "document": plan.document,
        "explanation": explanation,
        "planDigest": plan.plan_digest,
        "correlationId": str(plan.correlation_id),
        "applied": applied_state_document(applied_state),
        "createdAt": timestamp(plan.created_at),
    }


_SENSITIVE_FRAGMENTS = (
    "address",
    "serial",
    "object.path",
    "device.string",
    "socket",
    "token",
    "secret",
    "password",
)


def redact(value: object, *, admin: bool) -> object:
    if admin:
        return value
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[redacted]"
                if any(fragment in str(key).lower() for fragment in _SENSITIVE_FRAGMENTS)
                else redact(item, admin=False)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, admin=False) for item in value]
    return value


def projection_document(projection, *, admin: bool) -> dict[str, object]:
    return {
        "id": str(projection.pk),
        "type": projection.projection_type,
        "subject": projection.subject_key,
        "worldGeneration": projection.world_generation,
        "worldSequence": projection.world_sequence,
        "payload": redact(projection.payload, admin=admin),
        "current": projection.is_current,
        "observedAt": timestamp(projection.observed_at),
    }


def event_document(event, *, admin: bool) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "id": str(event.id),
        "correlationId": str(event.correlation_id),
        "definitionId": (str(event.graph_definition_id) if event.graph_definition_id else None),
        "type": event.event_type,
        "severity": event.severity,
        "payload": redact(event.payload, admin=admin),
        "occurredAt": timestamp(event.occurred_at),
    }
