import logging

from django.apps import AppConfig

from core.plugin_system import PluginDistributionRegistry
from core.plugin_system.integration import PluginAutomationRegistry, plugin_api_urlpatterns
from core.plugin_system.v2_registry import runtime_plugin_entry_points

# Prevent duplicate URL registration if Django calls ready() more than once.
_ALREADY_REGISTERED = False
_RUNTIME_INITIALIZED = False
PLUGIN_REGISTRY = PluginDistributionRegistry()
PLUGIN_AUTOMATIONS = PluginAutomationRegistry(PLUGIN_REGISTRY)

logger = logging.getLogger(__name__)


def initialize_plugin_runtime() -> bool:
    """Join durable desired state and start plugins after Django app loading is complete."""

    from core.plugin_system.persistence_sync import synchronize_plugin_inventory

    global _RUNTIME_INITIALIZED
    if _RUNTIME_INITIALIZED:
        return True
    persisted = synchronize_plugin_inventory(PLUGIN_REGISTRY)
    if not persisted:
        logger.info("Plugin inventory persistence is unavailable until migrations complete")
    PLUGIN_REGISTRY.start_enabled()
    PLUGIN_AUTOMATIONS.refresh()
    _RUNTIME_INITIALIZED = True
    return persisted


def refresh_plugin_runtime() -> bool:
    """Reconcile durable hot lifecycle state in the current service process."""

    from core.plugin_system.persistence_sync import refresh_plugin_desired_state

    if not refresh_plugin_desired_state(PLUGIN_REGISTRY):
        return False
    PLUGIN_REGISTRY.stop_disabled()
    PLUGIN_REGISTRY.start_enabled()
    PLUGIN_AUTOMATIONS.refresh()
    return True


class ApiConfig(AppConfig):
    name = "api"

    def ready(self):
        from core.orchestration.sqlite_policy import install_sqlite_connection_policy

        install_sqlite_connection_policy()

        global _ALREADY_REGISTERED
        if _ALREADY_REGISTERED:
            return

        PLUGIN_REGISTRY.discover(entry_points_provider=runtime_plugin_entry_points)
        for diagnostic in PLUGIN_REGISTRY.diagnostics:
            logger.warning(
                "Plugin %s %s: %s",
                diagnostic.plugin_id,
                diagnostic.code,
                diagnostic.message,
            )

        from api.urls import register_plugin_urls

        register_plugin_urls(plugin_api_urlpatterns(PLUGIN_REGISTRY))
        _ALREADY_REGISTERED = True
