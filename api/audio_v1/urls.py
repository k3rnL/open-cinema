from django.urls import path

from .adapter_views import (
    AdapterDetailView,
    AdapterListView,
    AdapterRestartView,
    AdapterTypeCatalogueView,
)

from .event_views import OrchestrationEventStreamView
from .graph_views import (
    DefinitionActivationView,
    DefinitionDetailView,
    DefinitionListView,
    GraphImportView,
    RevisionActivateView,
    RevisionCompareView,
    RevisionDetailView,
    RevisionExportView,
    RevisionListView,
    RevisionPublishView,
    RevisionValidateView,
    SubgraphListView,
)
from .inventory_views import (
    EndpointBindingView,
    EndpointCandidateExplanationView,
    EndpointCandidateListView,
    EndpointDetailView,
    EndpointListView,
    SelectorPreviewView,
)
from .level_views import EndpointAudioLevelView, MasterAudioLevelView
from .override_views import OverrideCancelView, OverrideListView
from .plan_views import CurrentPlanView, PlanDetailView, PlanDryRunView, PlanHistoryView
from .profile_views import CamillaDSPProfileDetailView, CamillaDSPProfileListView
from .runtime_views import (
    DiagnosticBundleView,
    ManagedResourceView,
    OrchestrationReadinessView,
    ProcessorHealthView,
    RuntimeSnapshotView,
)
from .schema_views import (
    JSONSchemasView,
    NodeTypeCatalogueView,
    OpenAPIView,
    SchemaMetadataView,
)
from .speaker_test_views import SpeakerTestView

app_name = "audio-v1"

urlpatterns = [
    path("", SchemaMetadataView.as_view(), name="root"),
    path("schema", SchemaMetadataView.as_view(), name="schema"),
    path("schemas", JSONSchemasView.as_view(), name="schemas"),
    path("openapi.json", OpenAPIView.as_view(), name="openapi"),
    path("graphs", DefinitionListView.as_view(), name="graphs"),
    path("subgraphs", SubgraphListView.as_view(), name="subgraphs"),
    path("graphs/import", GraphImportView.as_view(), name="graph-import"),
    path(
        "graphs/<uuid:definition_id>",
        DefinitionDetailView.as_view(),
        name="graph-detail",
    ),
    path(
        "graphs/<uuid:definition_id>/revisions",
        RevisionListView.as_view(),
        name="graph-revisions",
    ),
    path(
        "graphs/<uuid:definition_id>/activation",
        DefinitionActivationView.as_view(),
        name="graph-activation",
    ),
    path(
        "revisions/<uuid:revision_id>",
        RevisionDetailView.as_view(),
        name="revision-detail",
    ),
    path(
        "revisions/<uuid:revision_id>/validate",
        RevisionValidateView.as_view(),
        name="revision-validate",
    ),
    path(
        "revisions/<uuid:revision_id>/compare",
        RevisionCompareView.as_view(),
        name="revision-compare",
    ),
    path(
        "revisions/<uuid:revision_id>/publish",
        RevisionPublishView.as_view(),
        name="revision-publish",
    ),
    path(
        "revisions/<uuid:revision_id>/activate",
        RevisionActivateView.as_view(),
        name="revision-activate",
    ),
    path(
        "revisions/<uuid:revision_id>/export",
        RevisionExportView.as_view(),
        name="revision-export",
    ),
    path(
        "revisions/<uuid:revision_id>/dry-run",
        PlanDryRunView.as_view(),
        name="revision-dry-run",
    ),
    path("node-types", NodeTypeCatalogueView.as_view(), name="node-types"),
    path("adapter-types", AdapterTypeCatalogueView.as_view(), name="adapter-types"),
    path("adapters", AdapterListView.as_view(), name="adapters"),
    path("adapters/<uuid:adapter_id>", AdapterDetailView.as_view(), name="adapter-detail"),
    path(
        "adapters/<uuid:adapter_id>/restart", AdapterRestartView.as_view(), name="adapter-restart"
    ),
    path(
        "camilladsp/profiles",
        CamillaDSPProfileListView.as_view(),
        name="camilladsp-profiles",
    ),
    path(
        "camilladsp/profiles/<uuid:revision_id>",
        CamillaDSPProfileDetailView.as_view(),
        name="camilladsp-profile-detail",
    ),
    path("endpoints", EndpointListView.as_view(), name="endpoints"),
    path("levels/master", MasterAudioLevelView.as_view(), name="master-audio-level"),
    path(
        "endpoints/selector-preview",
        SelectorPreviewView.as_view(),
        name="endpoint-selector-preview",
    ),
    path(
        "endpoint-candidates",
        EndpointCandidateListView.as_view(),
        name="endpoint-candidates",
    ),
    path(
        "endpoints/<uuid:endpoint_id>",
        EndpointDetailView.as_view(),
        name="endpoint-detail",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/candidates",
        EndpointCandidateExplanationView.as_view(),
        name="endpoint-candidate-explanation",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/binding",
        EndpointBindingView.as_view(),
        name="endpoint-binding",
    ),
    path(
        "endpoints/<uuid:endpoint_id>/level",
        EndpointAudioLevelView.as_view(),
        name="endpoint-audio-level",
    ),
    path("plans/current", CurrentPlanView.as_view(), name="plans-current"),
    path("plans/history", PlanHistoryView.as_view(), name="plans-history"),
    path("plans/dry-run", PlanDryRunView.as_view(), name="plans-dry-run"),
    path("plans/<uuid:plan_id>", PlanDetailView.as_view(), name="plan-detail"),
    path("runtime/snapshot", RuntimeSnapshotView.as_view(), name="runtime-snapshot"),
    path("runtime/resources", ManagedResourceView.as_view(), name="runtime-resources"),
    path("runtime/processors", ProcessorHealthView.as_view(), name="runtime-processors"),
    path("runtime/readiness", OrchestrationReadinessView.as_view(), name="readiness"),
    path("runtime/diagnostics", DiagnosticBundleView.as_view(), name="diagnostics"),
    path("speaker-test", SpeakerTestView.as_view(), name="speaker-test"),
    path("overrides", OverrideListView.as_view(), name="overrides"),
    path(
        "overrides/<uuid:override_id>/cancel",
        OverrideCancelView.as_view(),
        name="override-cancel",
    ),
    path("events", OrchestrationEventStreamView.as_view(), name="events"),
]
