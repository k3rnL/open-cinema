import logging

from django.apps import AppConfig

from core.plugin_system import ApplicationLifecycleContext, PluginRegistry

# Prevent duplicate URL registration if Django calls ready() more than once.
_ALREADY_REGISTERED = False
PLUGIN_REGISTRY = PluginRegistry()

logger = logging.getLogger(__name__)


class ApiConfig(AppConfig):
    name = "api"

    def ready(self):
        from core.orchestration.sqlite_policy import install_sqlite_connection_policy

        install_sqlite_connection_policy()

        global _ALREADY_REGISTERED
        if _ALREADY_REGISTERED:
            return

        PLUGIN_REGISTRY.discover()

        # The built-in example is also registered directly so source-tree
        # development works before editable package metadata is refreshed.
        from plugin.counter.api.plugin import CounterApplicationPlugin

        if PLUGIN_REGISTRY.get("counter") is None:
            try:
                PLUGIN_REGISTRY.register_application(CounterApplicationPlugin())
            except Exception:
                logger.exception("Failed to register bundled counter application plugin")

        PLUGIN_REGISTRY.start_applications(ApplicationLifecycleContext())
        for diagnostic in PLUGIN_REGISTRY.diagnostics:
            logger.warning(
                "Plugin %s %s: %s",
                diagnostic.plugin_id,
                diagnostic.code,
                diagnostic.message,
            )

        plugins = PLUGIN_REGISTRY.application_plugins()
        if plugins:
            self._register_plugin_urls(plugins)
        _ALREADY_REGISTERED = True

    def _register_plugin_urls(self, plugins):
        from api.urls import register_plugin_urls

        register_plugin_urls(plugins)
