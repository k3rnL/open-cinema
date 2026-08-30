from __future__ import annotations

import hashlib
import json

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import PluginInstallation, PluginOperation, PluginOperationKind
from core.plugin_system.catalogue import FirstPartyPluginCatalogue
from core.plugin_system.acquisition import GitPluginAcquirer
from core.plugin_system.operations import (
    installation_action_documents,
    operation_document,
    request_operation_cancellation,
    request_plugin_operation,
)
from core.plugin_system import (
    AdminUICapability,
    PluginDesiredState as RuntimePluginDesiredState,
    PluginHealth,
    PluginLifecycleState,
)
from core.plugin_system.storage import (
    PLUGIN_STORAGE_SCHEMAS,
    PluginDocumentRepository,
    PluginInstanceRepository,
    PluginSecretRepository,
)

from .base import PluginV2APIView, parse_version_precondition, require_object


class PluginCatalogueView(PluginV2APIView):
    def get(self, request):
        from api.apps import PLUGIN_REGISTRY

        return Response(
            FirstPartyPluginCatalogue.load().joined_document(PLUGIN_REGISTRY)
        )


class PluginUIBootstrapView(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)

    def get(self, request):
        from api.apps import PLUGIN_REGISTRY

        plugins = []
        for record, capability in PLUGIN_REGISTRY.capability_records(AdminUICapability):
            contribution = capability.contribution
            if (
                not isinstance(contribution, AdminUICapability)
                or record.desired_state is not RuntimePluginDesiredState.ENABLED
                or record.state
                not in {PluginLifecycleState.AVAILABLE, PluginLifecycleState.STARTED}
                or capability.health
                not in {PluginHealth.HEALTHY, PluginHealth.DEGRADED}
            ):
                continue
            plugins.append(
                {
                    "id": record.manifest.plugin_id,
                    "displayName": record.manifest.display_name,
                    "version": record.manifest.version,
                    "health": record.health.value,
                    "descriptor": contribution.descriptor.to_dict(),
                }
            )
        document = {"schemaVersion": 1, "plugins": plugins}
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            return Response(
                {
                    "code": "plugin-ui-bootstrap-too-large",
                    "detail": "Enabled plugin UI descriptors exceed the response limit.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        etag = '"sha256:' + hashlib.sha256(encoded).hexdigest() + '"'
        if request.headers.get("If-None-Match") == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = Response(document)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=30, must-revalidate"
        return response


class InstalledPluginListView(PluginV2APIView):
    def get(self, request):
        from api.apps import PLUGIN_REGISTRY

        runtime = {item.manifest.plugin_id: item for item in PLUGIN_REGISTRY.records}
        items = []
        for installation in PluginInstallation.objects.all():
            record = runtime.get(installation.plugin_id)
            items.append(
                {
                    "id": installation.plugin_id,
                    "distribution": installation.distribution_id,
                    "installedVersion": installation.installed_version,
                    "desiredState": installation.desired_state,
                    "observedState": installation.observed_state,
                    "health": installation.aggregate_health,
                    "activeGeneration": installation.active_generation or None,
                    "lastKnownGoodGeneration": (
                        installation.last_known_good_generation or None
                    ),
                    "manifest": installation.manifest_snapshot,
                    "provenance": installation.provenance_snapshot,
                    "lifecycleImpact": installation.lifecycle_impact,
                    "updateVersion": installation.update_version,
                    "runtime": record.to_document() if record is not None else None,
                    "actions": installation_action_documents(installation),
                    "updatedAt": installation.updated_at.isoformat(),
                }
            )
        return Response({"schemaVersion": 1, "items": items})


def _idempotency_key(request) -> str:
    value = request.headers.get("Idempotency-Key")
    if not value:
        raise ValueError("Idempotency-Key is required")
    return value


def _enqueue(operation, *, created: bool) -> None:
    if not created:
        return
    from api.tasks.plugin_operations import run_plugin_operation

    run_plugin_operation.delay(str(operation.pk))


class PluginInstallView(PluginV2APIView):
    def post(self, request):
        body = require_object(request.data)
        if body.get("trustedCodeAcknowledged") is not True:
            raise ValueError("trustedCodeAcknowledged must be explicitly accepted")
        plugin_id = str(body.get("pluginId", ""))
        source_type = str(body.get("sourceType", "git"))
        if source_type not in {"catalogue", "git"}:
            raise ValueError("sourceType must be catalogue or git")
        repository = body.get("repository")
        revision = body.get("revision")
        version = body.get("version")
        artifact = None
        if source_type == "catalogue":
            entry = FirstPartyPluginCatalogue.load().get(plugin_id)
            if entry is None:
                raise ValueError("plugin is absent from the first-party catalogue")
            selected = next(
                (item for item in entry.versions if item.version == version),
                None,
            )
            if selected is None or not selected.published or not selected.compatible:
                raise ValueError("catalogue version is not currently installable")
            artifact = selected.artifact_for()
            if artifact is None:
                platform_document = selected.to_document()["currentPlatform"]
                raise ValueError(
                    "catalogue has no artifact for "
                    f"{platform_document['operatingSystem']}/"
                    f"{platform_document['architecture']}"
                )
            repository = entry.repository
            revision = selected.revision
        operation, created = request_plugin_operation(
            plugin_id=plugin_id,
            kind=PluginOperationKind.INSTALL,
            idempotency_key=_idempotency_key(request),
            requested_by=request.user,
            expected_version=None,
            stage_data={
                "sourceType": source_type,
                "repository": repository,
                "revision": revision,
                "version": version,
                "artifact": artifact.to_document()
                if source_type == "catalogue"
                else None,
                "trustedCodeAcknowledged": body.get("trustedCodeAcknowledged") is True,
            },
        )
        _enqueue(operation, created=created)
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class PluginSourceInspectionView(PluginV2APIView):
    def post(self, request):
        body = require_object(request.data)
        if body.get("trustedCodeAcknowledged") is not True:
            raise ValueError("trustedCodeAcknowledged must be explicitly accepted")
        with GitPluginAcquirer().acquire(
            repository_url=body.get("repository"),
            revision=body.get("revision"),
            trusted_code_acknowledged=True,
        ) as candidate:
            return Response(
                {
                    "schemaVersion": 1,
                    "manifest": candidate.manifest.to_document(),
                    "provenance": candidate.provenance_document(),
                    "warnings": (
                        [
                            "This revision is mutable. The resolved commit is recorded, "
                            "but repeating the same request may fetch different code."
                        ]
                        if candidate.mutable_revision
                        else []
                    ),
                }
            )


class PluginLifecycleActionView(PluginV2APIView):
    def post(self, request, plugin_id: str, action: str):
        try:
            kind = PluginOperationKind(action)
        except ValueError as error:
            raise ValueError("unsupported plugin lifecycle action") from error
        if kind not in {
            PluginOperationKind.ENABLE,
            PluginOperationKind.DISABLE,
            PluginOperationKind.UPDATE,
            PluginOperationKind.UNINSTALL,
            PluginOperationKind.ROLLBACK,
        }:
            raise ValueError("unsupported plugin lifecycle action")
        body = require_object(request.data)
        expected_version = body.get("expectedVersion")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise ValueError("expectedVersion must be an integer")
        operation, created = request_plugin_operation(
            plugin_id=plugin_id,
            kind=kind,
            idempotency_key=_idempotency_key(request),
            requested_by=request.user,
            expected_version=expected_version,
            stage_data={
                "deleteData": body.get("deleteData") is True,
                "sourceType": body.get("sourceType", "git"),
                "repository": body.get("repository"),
                "revision": body.get("revision"),
                "version": body.get("version"),
                "trustedCodeAcknowledged": body.get("trustedCodeAcknowledged") is True,
            },
        )
        _enqueue(operation, created=created)
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class PluginOperationListView(PluginV2APIView):
    def get(self, request):
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
        except (TypeError, ValueError) as error:
            raise ValueError("limit must be an integer") from error
        return Response(
            {
                "schemaVersion": 1,
                "items": [
                    operation_document(item)
                    for item in PluginOperation.objects.all()[:limit]
                ],
            }
        )


class PluginOperationDetailView(PluginV2APIView):
    def get(self, request, operation_id):
        operation = get_object_or_404(PluginOperation, pk=operation_id)
        return Response(operation_document(operation))


class PluginOperationCancelView(PluginV2APIView):
    def post(self, request, operation_id):
        body = require_object(request.data)
        operation = request_operation_cancellation(
            operation_id,
            concurrency_token=str(body.get("concurrencyToken", "")),
        )
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class PluginOperationRetryView(PluginV2APIView):
    def post(self, request, operation_id):
        previous = get_object_or_404(PluginOperation, pk=operation_id)
        operation, created = request_plugin_operation(
            plugin_id=previous.plugin_id,
            kind=PluginOperationKind.RETRY,
            idempotency_key=_idempotency_key(request),
            requested_by=request.user,
            expected_version=None,
            stage_data={"retryOperationId": str(previous.pk)},
        )
        _enqueue(operation, created=created)
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class PluginCleanupView(PluginV2APIView):
    def post(self, request):
        operation, created = request_plugin_operation(
            plugin_id="plugin-platform",
            kind=PluginOperationKind.CLEANUP,
            idempotency_key=_idempotency_key(request),
            requested_by=request.user,
            expected_version=None,
        )
        _enqueue(operation, created=created)
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


def _document(item) -> dict[str, object]:
    return {
        "id": item.document_id,
        "pluginId": item.plugin_id,
        "collection": item.collection,
        "schemaId": item.schema_id,
        "schemaVersion": item.schema_version,
        "document": item.document,
        "updateVersion": item.update_version,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def _instance(item) -> dict[str, object]:
    return {
        "id": item.instance_id,
        "pluginId": item.plugin_id,
        "capabilityId": item.capability_id,
        "displayName": item.display_name,
        "configurationVersion": item.configuration_version,
        "configuration": item.configuration,
        "desiredState": item.desired_state,
        "observedState": item.observed_state,
        "runtimeFacts": item.runtime_facts,
        "updateVersion": item.update_version,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def _pagination(request) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("limit and offset must be integers") from error
    return limit, offset


class PluginDocumentListView(PluginV2APIView):
    def get(self, request, plugin_id: str, collection: str):
        limit, offset = _pagination(request)
        items = PluginDocumentRepository.list(
            plugin_id, collection, limit=limit, offset=offset
        )
        return Response(
            {
                "schemaVersion": 1,
                "items": [_document(item) for item in items],
                "pagination": {"limit": limit, "offset": offset},
            }
        )

    def post(self, request, plugin_id: str, collection: str):
        body = require_object(request.data)
        schema_id = str(body.get("schemaId", ""))
        schema_version = body.get("schemaVersion")
        schema = PLUGIN_STORAGE_SCHEMAS.require(plugin_id, schema_id, schema_version)
        item = PluginDocumentRepository.put(
            plugin_id=plugin_id,
            collection=collection,
            document_id=body.get("id"),
            schema_id=schema_id,
            schema_version=schema_version,
            document=require_object(body.get("document"), "document"),
            schema=schema,
        )
        response = Response(_document(item), status=status.HTTP_201_CREATED)
        response["ETag"] = f'"{item.update_version}"'
        return response


class PluginDocumentDetailView(PluginV2APIView):
    def get(self, request, plugin_id: str, collection: str, document_id: str):
        item = PluginDocumentRepository.get(plugin_id, collection, document_id)
        response = Response(_document(item))
        response["ETag"] = f'"{item.update_version}"'
        return response

    def put(self, request, plugin_id: str, collection: str, document_id: str):
        expected_version = parse_version_precondition(request)
        body = require_object(request.data)
        schema_id = str(body.get("schemaId", ""))
        schema_version = body.get("schemaVersion")
        schema = PLUGIN_STORAGE_SCHEMAS.require(plugin_id, schema_id, schema_version)
        item = PluginDocumentRepository.put(
            plugin_id=plugin_id,
            collection=collection,
            document_id=document_id,
            schema_id=schema_id,
            schema_version=schema_version,
            document=require_object(body.get("document"), "document"),
            schema=schema,
            expected_version=expected_version,
        )
        response = Response(_document(item))
        response["ETag"] = f'"{item.update_version}"'
        return response

    def delete(self, request, plugin_id: str, collection: str, document_id: str):
        PluginDocumentRepository.delete(
            plugin_id,
            collection,
            document_id,
            expected_version=parse_version_precondition(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginInstanceListView(PluginV2APIView):
    def get(self, request, plugin_id: str, capability_id: str):
        limit, offset = _pagination(request)
        items = PluginInstanceRepository.list(
            plugin_id, capability_id, limit=limit, offset=offset
        )
        return Response(
            {
                "schemaVersion": 1,
                "items": [_instance(item) for item in items],
                "pagination": {"limit": limit, "offset": offset},
            }
        )

    def post(self, request, plugin_id: str, capability_id: str):
        body = require_object(request.data)
        schema_id = str(body.get("schemaId", ""))
        schema_version = body.get("configurationVersion")
        schema = PLUGIN_STORAGE_SCHEMAS.require(plugin_id, schema_id, schema_version)
        item = PluginInstanceRepository.create(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=body.get("id"),
            display_name=body.get("displayName"),
            configuration_version=schema_version,
            configuration=require_object(body.get("configuration"), "configuration"),
            schema=schema,
        )
        response = Response(_instance(item), status=status.HTTP_201_CREATED)
        response["ETag"] = f'"{item.update_version}"'
        return response


class PluginInstanceDetailView(PluginV2APIView):
    def get(self, request, plugin_id: str, capability_id: str, instance_id: str):
        item = PluginInstanceRepository.get(plugin_id, capability_id, instance_id)
        response = Response(_instance(item))
        response["ETag"] = f'"{item.update_version}"'
        return response

    def put(self, request, plugin_id: str, capability_id: str, instance_id: str):
        body = require_object(request.data)
        schema_id = str(body.get("schemaId", ""))
        schema_version = body.get("configurationVersion")
        schema = PLUGIN_STORAGE_SCHEMAS.require(plugin_id, schema_id, schema_version)
        item = PluginInstanceRepository.update_configuration(
            plugin_id=plugin_id,
            capability_id=capability_id,
            instance_id=instance_id,
            configuration_version=schema_version,
            configuration=require_object(body.get("configuration"), "configuration"),
            schema=schema,
            expected_version=parse_version_precondition(request),
        )
        response = Response(_instance(item))
        response["ETag"] = f'"{item.update_version}"'
        return response

    def delete(self, request, plugin_id: str, capability_id: str, instance_id: str):
        PluginInstanceRepository.delete(
            plugin_id,
            capability_id,
            instance_id,
            expected_version=parse_version_precondition(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginSecretView(PluginV2APIView):
    def get(self, request, plugin_id: str, secret_id: str):
        return Response(
            PluginSecretRepository.presence(plugin_id, secret_id).to_document()
        )

    def put(self, request, plugin_id: str, secret_id: str):
        body = require_object(request.data)
        value = body.get("value")
        current = PluginSecretRepository.presence(plugin_id, secret_id)
        expected_version = (
            parse_version_precondition(request) if current.configured else None
        )
        presence = PluginSecretRepository.set(
            plugin_id=plugin_id,
            secret_id=secret_id,
            value=value,
            expected_version=expected_version,
        )
        response = Response(presence.to_document())
        response["ETag"] = f'"{presence.update_version}"'
        return response

    def delete(self, request, plugin_id: str, secret_id: str):
        PluginSecretRepository.delete(
            plugin_id=plugin_id,
            secret_id=secret_id,
            expected_version=parse_version_precondition(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
