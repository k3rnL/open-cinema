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
    # Appliance observation and guarded host controls are intentionally
    # separate from desired audio orchestration state.
    path("system/v1/", include("api.system_v1.urls")),
    # Core-owned version-2 plugin documents, instances, and write-only secrets.
    path("plugin-platform/v2/", include("api.plugin_v2.urls")),
    # Version
    path("version", api.views.version.get_version, name="version"),
]

# Plugin API routes (dynamically populated by apps.py during startup)
_plugin_urlpatterns = []


def register_plugin_urls(plugin_urlpatterns):
    """Append core-guarded version-2 plugin URL patterns during startup."""
    global _plugin_urlpatterns
    _plugin_urlpatterns.extend(plugin_urlpatterns)
    urlpatterns.extend(_plugin_urlpatterns)
