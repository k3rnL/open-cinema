from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from api.models import SystemControlAction, SystemControlOperation

from .base import SystemV1APIView
from .components import component_documents, readiness_document
from .control import (
    appliance_action_documents,
    operation_document,
    request_action,
)
from .probes import collect_metrics, collect_overview
from .schemas import api_json_schemas, openapi_document, schema_metadata


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SchemaMetadataView(SystemV1APIView):
    def get(self, request):
        return Response(schema_metadata())


class JSONSchemasView(SystemV1APIView):
    def get(self, request):
        return Response({"apiVersion": 1, "schemas": api_json_schemas()})


class OpenAPIView(SystemV1APIView):
    def get(self, request):
        return Response(openapi_document())


class SystemOverviewView(SystemV1APIView):
    def get(self, request):
        return Response(collect_overview(readiness=readiness_document()))


class SystemMetricsView(SystemV1APIView):
    def get(self, request):
        return Response(collect_metrics())


class ComponentListView(SystemV1APIView):
    def get(self, request):
        return Response({"schemaVersion": 1, "items": component_documents()})


class ApplianceActionListView(SystemV1APIView):
    def get(self, request):
        return Response({"schemaVersion": 1, "items": appliance_action_documents()})


class ComponentRestartView(SystemV1APIView):
    _actions = {
        "open-cinema": SystemControlAction.RESTART_OPEN_CINEMA,
        "open-cinema-orchestrator": SystemControlAction.RESTART_ORCHESTRATOR,
    }

    def post(self, request, component_id: str):
        action = self._actions.get(component_id)
        if action is None:
            raise ValueError("This component does not advertise a restart action.")
        operation = request_action(
            action=action,
            action_token=request.data.get("actionToken"),
            user=request.user,
        )
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class ApplianceRebootView(SystemV1APIView):
    def post(self, request):
        operation = request_action(
            action=SystemControlAction.REBOOT_APPLIANCE,
            action_token=request.data.get("actionToken"),
            user=request.user,
        )
        return Response(operation_document(operation), status=status.HTTP_202_ACCEPTED)


class SystemControlOperationView(SystemV1APIView):
    def get(self, request, operation_id):
        operation = get_object_or_404(SystemControlOperation, pk=operation_id)
        return Response(operation_document(operation))
