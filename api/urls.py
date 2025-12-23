from django.urls import path, include

import api.views.audio_devices
import api.views.device_discovery
import api.views.camilladsp_pipelines
import api.views.camilladsp_status
import api.views.version

# Core API routes
urlpatterns = [
    # Version
    path("version", api.views.version.get_version, name="version"),

    # Audio devices
    path("devices", api.views.audio_devices.get_devices, name="get_devices"),
    path("devices/discover", api.views.audio_devices.discover_devices, name="discover_devices"),
    path("devices/update", api.views.device_discovery.trigger_discovery, name="trigger_discovery"),

    # CamillaDSP pipelines
    path("camilladsp/pipelines", api.views.camilladsp_pipelines.list_pipelines, name="list_pipelines"),
    path("camilladsp/pipelines/create", api.views.camilladsp_pipelines.create_pipeline, name="create_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>", api.views.camilladsp_pipelines.get_pipeline, name="get_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/update", api.views.camilladsp_pipelines.update_pipeline, name="update_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/delete", api.views.camilladsp_pipelines.delete_pipeline, name="delete_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/activate", api.views.camilladsp_pipelines.activate_pipeline, name="activate_pipeline"),
    path("camilladsp/pipelines/<int:pipeline_id>/deactivate", api.views.camilladsp_pipelines.deactivate_pipeline, name="deactivate_pipeline"),

    # CamillaDSP status
    path("camilladsp/status", api.views.camilladsp_status.get_status, name="camilladsp_status"),
    path("camilladsp/config", api.views.camilladsp_status.get_config, name="camilladsp_config"),
    path("camilladsp/reload", api.views.camilladsp_status.reload_config, name="camilladsp_reload"),
]

# Plugin API routes (dynamically populated by apps.py during startup)
_plugin_urlpatterns = []


def register_plugin_urls(plugin_classes):
    """
    Called by ApiConfig.ready() to register plugin URLs.

    Plugins get their routes under /api/plugins/{plugin_name}/
    """
    global _plugin_urlpatterns

    for plugin_class in plugin_classes:
        try:
            plugin_instance = plugin_class()
            plugin_urls = plugin_instance.get_urls()

            # Add plugin routes under /api/plugins/{plugin_name}/
            _plugin_urlpatterns.append(
                path(f"plugins/{plugin_instance.plugin_name}/",
                     include((plugin_urls, plugin_instance.plugin_name)))
            )
            print(f"  → Registered API routes for plugin: {plugin_instance.plugin_name}")

        except Exception as e:
            print(f"  ✗ Failed to register plugin {plugin_class.__name__}: {e}")

    # Append plugin URLs to main urlpatterns
    urlpatterns.extend(_plugin_urlpatterns)