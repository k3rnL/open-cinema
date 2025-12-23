import importlib
import pkgutil

from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        """Auto-discover all plugin modules to register AudioBackend and APIPlugin implementations."""
        import plugin
        from core.plugin_system.api_plugin import APIPlugin

        print("Starting plugin auto-discovery...")

        discovered_api_plugins = []

        # Walk through all modules in the plugin package and import them
        for importer, modname, ispkg in pkgutil.walk_packages(
            path=plugin.__path__,
            prefix=plugin.__name__ + '.'
        ):
            try:
                module_type = "package" if ispkg else "module"
                print(f"Importing {module_type}: {modname}")
                module = importlib.import_module(modname)
                print(f"Successfully imported {module_type}: {modname}")

                # Check for API plugin classes in the module
                for item_name in dir(module):
                    item = getattr(module, item_name)
                    if (isinstance(item, type) and
                        issubclass(item, APIPlugin) and
                        item is not APIPlugin):
                        discovered_api_plugins.append(item)
                        print(f"  → Found API plugin class: {item.__name__}")

            except Exception as e:
                # Log but don't crash if a plugin fails to load
                print(f"Warning: Failed to load plugin module {modname}: {e}")

        print(f"Plugin auto-discovery completed. Found {len(discovered_api_plugins)} API plugin(s).")

        # Register discovered API plugins
        if discovered_api_plugins:
            self._register_plugin_urls(discovered_api_plugins)

    def _register_plugin_urls(self, plugin_classes):
        """Register URLs from discovered API plugins."""
        from api.urls import register_plugin_urls
        register_plugin_urls(plugin_classes)
