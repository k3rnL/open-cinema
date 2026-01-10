import importlib
import logging
import pkgutil

from django.apps import AppConfig

# Prevent duplicate URL registration if Django calls ready() more than once
_ALREADY_REGISTERED = False

logger = logging.getLogger(__name__)

class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        """
        Import all modules in the 'plugin' package so APIPlugin subclasses register
        via __init_subclass__. Then register URLs from APIPlugin.registry.
        """
        global _ALREADY_REGISTERED
        if _ALREADY_REGISTERED:
            return

        from core.plugin_system.oc_plugin import OCPlugin

        logger.info("Starting plugin auto-discovery...")

        try:
            import plugin # your user-installed plugin folder must be a Python package
        except Exception as e:
            logger.warning("No 'plugin' package found or failed to import: %s", e)
            _ALREADY_REGISTERED = True
            return

        # Import every module under plugin.* to trigger class registration
        for _, modname, ispkg in pkgutil.walk_packages(
            path=plugin.__path__,
            prefix=plugin.__name__ + ".",
        ):
            try:
                if 'migrations' not in modname:
                    importlib.import_module(modname)
                    print(f"Imported {"package" if ispkg else "module"}: {modname}")
            except Exception:
                # Don't crash if a plugin fails to load
                logger.exception("Failed to load plugin module %s", modname)
                print(f"Failed to load module {modname}")

        # Pull plugin classes from registry (no module scanning needed)
        plugin_classes = list(OCPlugin.registry.values())
        print(f"Plugin auto-discovery completed. Found {len(plugin_classes)} API plugin(s).")

        if plugin_classes:
            self._register_plugin_urls(plugin_classes)

        _ALREADY_REGISTERED = True

    def _register_plugin_urls(self, plugin_classes):
        """Register URLs from discovered API plugins."""
        from api.urls import register_plugin_urls
        register_plugin_urls(plugin_classes)
