from django.urls import path

from .views import (
    InstalledPluginListView,
    PluginCatalogueView,
    PluginDocumentDetailView,
    PluginDocumentListView,
    PluginInstallView,
    PluginInstanceDetailView,
    PluginInstanceListView,
    PluginLifecycleActionView,
    PluginCleanupView,
    PluginOperationCancelView,
    PluginOperationDetailView,
    PluginOperationListView,
    PluginOperationRetryView,
    PluginSecretView,
    PluginSourceInspectionView,
    PluginUIBootstrapView,
)

app_name = "plugin-v2"

urlpatterns = [
    path("catalogue", PluginCatalogueView.as_view(), name="catalogue"),
    path("ui", PluginUIBootstrapView.as_view(), name="ui-bootstrap"),
    path("installed", InstalledPluginListView.as_view(), name="installed"),
    path("install", PluginInstallView.as_view(), name="install"),
    path(
        "inspect-source",
        PluginSourceInspectionView.as_view(),
        name="inspect-source",
    ),
    path("actions/cleanup", PluginCleanupView.as_view(), name="cleanup"),
    path("operations", PluginOperationListView.as_view(), name="operation-list"),
    path(
        "operations/<uuid:operation_id>",
        PluginOperationDetailView.as_view(),
        name="operation-detail",
    ),
    path(
        "operations/<uuid:operation_id>/cancel",
        PluginOperationCancelView.as_view(),
        name="operation-cancel",
    ),
    path(
        "operations/<uuid:operation_id>/retry",
        PluginOperationRetryView.as_view(),
        name="operation-retry",
    ),
    path(
        "plugins/<str:plugin_id>/actions/<str:action>",
        PluginLifecycleActionView.as_view(),
        name="lifecycle-action",
    ),
    path(
        "plugins/<str:plugin_id>/documents/<str:collection>",
        PluginDocumentListView.as_view(),
        name="document-list",
    ),
    path(
        "plugins/<str:plugin_id>/documents/<str:collection>/<str:document_id>",
        PluginDocumentDetailView.as_view(),
        name="document-detail",
    ),
    path(
        "plugins/<str:plugin_id>/capabilities/<str:capability_id>/instances",
        PluginInstanceListView.as_view(),
        name="instance-list",
    ),
    path(
        "plugins/<str:plugin_id>/capabilities/<str:capability_id>/instances/<str:instance_id>",
        PluginInstanceDetailView.as_view(),
        name="instance-detail",
    ),
    path(
        "plugins/<str:plugin_id>/secrets/<str:secret_id>",
        PluginSecretView.as_view(),
        name="secret",
    ),
]
