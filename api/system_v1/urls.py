from django.urls import path

from .views import (
    ApplianceActionListView,
    ApplianceRebootView,
    ComponentRestartView,
    ComponentListView,
    JSONSchemasView,
    OpenAPIView,
    SchemaMetadataView,
    SystemMetricsView,
    SystemOverviewView,
    SystemControlOperationView,
)

app_name = "system-v1"

urlpatterns = [
    path("", SchemaMetadataView.as_view(), name="root"),
    path("schema", SchemaMetadataView.as_view(), name="schema"),
    path("schemas", JSONSchemasView.as_view(), name="schemas"),
    path("openapi.json", OpenAPIView.as_view(), name="openapi"),
    path("overview", SystemOverviewView.as_view(), name="overview"),
    path("metrics", SystemMetricsView.as_view(), name="metrics"),
    path("components", ComponentListView.as_view(), name="components"),
    path("actions", ApplianceActionListView.as_view(), name="actions"),
    path("actions/reboot", ApplianceRebootView.as_view(), name="reboot"),
    path(
        "components/<slug:component_id>/actions/restart",
        ComponentRestartView.as_view(),
        name="component-restart",
    ),
    path(
        "operations/<uuid:operation_id>",
        SystemControlOperationView.as_view(),
        name="operation",
    ),
]
