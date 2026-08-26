from django.urls import include, path

import api.auth_views
import api.views.version

# Core API routes
urlpatterns = [
    # Browser session authentication for the Refine management console.
    path("auth/session", api.auth_views.session, name="auth-session"),
    path("auth/login", api.auth_views.login_session, name="auth-login"),
    path("auth/logout", api.auth_views.logout_session, name="auth-logout"),
    # Desired graph orchestration API. Availability is controlled independently
    # by OPEN_CINEMA_AUDIO_ORCHESTRATION_API.
    path("audio/v1/", include("api.audio_v1.urls")),
    # Version
    path("version", api.views.version.get_version, name="version"),
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
                path(
                    f"plugins/{plugin_instance.plugin_name}/",
                    include((plugin_urls, plugin_instance.plugin_name)),
                )
            )
            print(f"  → Registered API routes for plugin: {plugin_instance.plugin_name}")

        except Exception as e:
            print(f"  ✗ Failed to register plugin {plugin_instance.__class__.__name__}: {e}")

    # Append plugin URLs to main urlpatterns
    urlpatterns.extend(_plugin_urlpatterns)
