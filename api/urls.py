from django.urls import path, include

import api.views.audio.audio_devices
import api.views.audio.pipeline.audio_pipelines
import api.views.audio.pipeline.audio_pipeline_apply
import api.views.audio.pipeline.audio_pipeline_events
import api.views.audio.pipeline.audio_pipeline_validation
import api.views.audio.pipeline.audio_pipeline_edges
import api.views.audio.pipeline.node.audio_pipeline_nodes
import api.views.audio.pipeline.node.audio_pipeline_node_positions
import api.views.audio.pipeline.node.audio_pipeline_node_relations
import api.views.audio.pipeline.audio_pipelines_schematic
import api.views.preferences_audio_backend
import api.views.audio.device_discovery
import api.views.camilladsp_pipelines
import api.views.camilladsp_mixers
import api.views.camilladsp_status
import api.views.version

# Core API routes
urlpatterns = [
    # Version
    path("version", api.views.version.get_version, name="version"),

    # Audio devices
    path("devices", api.views.audio.audio_devices.get_devices, name="get_devices"),
    path("devices/<int:device_id>", api.views.audio.audio_devices.forget_device, name="forget_device"),
    path("devices/discover", api.views.audio.audio_devices.discover_devices, name="discover_devices"),
    path("devices/update", api.views.audio.device_discovery.trigger_discovery, name="trigger_discovery"),

    path("pipelines", api.views.audio.pipeline.audio_pipelines.AudioPipelineList.as_view(), name="pipelines"),
    path("pipelines/<int:pipeline_id>", api.views.audio.pipeline.audio_pipelines.AudioPipelineDetail.as_view(), name="pipeline"),
    path("pipelines/<int:pipeline_id>/validate", api.views.audio.pipeline.audio_pipeline_validation.validate_audio_pipeline, name="pipeline"),
    path("pipelines/<int:pipeline_id>/apply", api.views.audio.pipeline.audio_pipeline_apply.AudioPipelineApplyView.as_view(), name="pipeline_apply"),
    path("pipelines/<int:pipeline_id>/unapply", api.views.audio.pipeline.audio_pipeline_apply.AudioPipelineApplyView.as_view(), name="pipeline_unapply"),
    path("pipelines/<int:pipeline_id>/job/<int:job_id>", api.views.audio.pipeline.audio_pipeline_events.AudioPipelineApplyEventList.as_view(), name="pipeline_events"),
    path("pipelines/<int:pipeline_id>/nodes", api.views.audio.pipeline.node.audio_pipeline_nodes.AudioPipelineNodeList.as_view(), name="pipeline_nodes"),
    path("pipelines/<int:pipeline_id>/nodes/positions", api.views.audio.pipeline.node.audio_pipeline_node_positions.AudioPipelineNodePositionList.as_view(), name="pipeline_node_positions"),
    path("pipelines/<int:pipeline_id>/nodes/<int:node_id>", api.views.audio.pipeline.node.audio_pipeline_nodes.AudioPipelineNodeDetail.as_view(), name="pipeline_node"),
    path("pipelines/<int:pipeline_id>/edges", api.views.audio.pipeline.audio_pipeline_edges.AudioPipelineEdgeList.as_view(), name="pipeline_edges"),
    path("pipelines/<int:pipeline_id>/edges/<int:edge_id>", api.views.audio.pipeline.audio_pipeline_edges.AudioPipelineEdgeDetail.as_view(), name="pipeline_edge"),

    path("pipelines/schematics", api.views.audio.pipeline.audio_pipelines_schematic.get_pipeline_schematics, name="pipeline_schematics"),
    path("pipelines/schematics/<str:type_name>/<str:field_name>", api.views.audio.pipeline.node.audio_pipeline_node_relations.node_relations, name="pipeline_node_relations"),
    path("pipelines/<int:pipeline_id>/nodes/<int:node_id>/schematics", api.views.audio.pipeline.audio_pipelines_schematic.get_node_schematic, name="pipeline_node_schematics"),

    # Preferences
    path("preferences/audio-backends", api.views.preferences_audio_backend.get_audio_backends_preferences, name="get_audio_backend_preferences"),
    path("preferences/audio-backends/<str:backend_name>", api.views.preferences_audio_backend.update_audio_backend_preference, name="get_audio_backend_preferences"),

    # CamillaDSP pipelines
    path("camilladsp/pipelines/<int:pipeline_id>/yaml", api.views.camilladsp_pipelines.get_yaml_pipeline, name="get_yaml_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/activate", api.views.camilladsp_pipelines.activate_pipeline, name="activate_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/deactivate", api.views.camilladsp_pipelines.deactivate_pipeline, name="deactivate_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>", api.views.camilladsp_pipelines.pipeline_detail, name="pipeline_detail"),
    path("camilladsp/pipelines", api.views.camilladsp_pipelines.pipelines, name="pipelines"),

    # CamillaDSP mixers
    path("camilladsp/mixers/<int:mixer_id>", api.views.camilladsp_mixers.mixer_detail, name="mixer_detail"),
    path("camilladsp/mixers", api.views.camilladsp_mixers.mixers, name="mixers"),

    # CamillaDSP status
    path("camilladsp/status", api.views.camilladsp_status.get_status, name="camilladsp_status"),
    path("camilladsp/config", api.views.camilladsp_status.get_config, name="camilladsp_config"),
    path("camilladsp/config/yaml", api.views.camilladsp_status.get_config_yaml, name="camilladsp_config"),
    path("camilladsp/reload", api.views.camilladsp_status.reload_config, name="camilladsp_reload"),
]

# Plugin API routes (dynamically populated by apps.py during startup)
_plugin_urlpatterns = []


def register_plugin_urls(plugin_instances):
    """
    Called by ApiConfig.ready() to register plugin URLs.

    Plugins get their routes under /api/plugins/{plugin_name}/
    """
    global _plugin_urlpatterns

    for plugin_instance in plugin_instances:
        try:
            plugin_urls = plugin_instance.get_urls()

            # Add plugin routes under /api/plugins/{plugin_name}/
            _plugin_urlpatterns.append(
                path(f"plugins/{plugin_instance.plugin_name}/",
                     include((plugin_urls, plugin_instance.plugin_name)))
            )
            print(f"  → Registered API routes for plugin: {plugin_instance.plugin_name}")

        except Exception as e:
            print(f"  ✗ Failed to register plugin {plugin_instance.__class__.__name__}: {e}")

    # Append plugin URLs to main urlpatterns
    urlpatterns.extend(_plugin_urlpatterns)