import importlib
import pkgutil

from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        """Auto-discover all plugin modules to register AudioBackend implementations."""
        import plugin

        print("Starting plugin auto-discovery...")

        # Walk through all modules in the plugin package and import them
        for importer, modname, ispkg in pkgutil.walk_packages(
            path=plugin.__path__,
            prefix=plugin.__name__ + '.'
        ):
            try:
                module_type = "package" if ispkg else "module"
                print(f"Importing {module_type}: {modname}")
                importlib.import_module(modname)
                print(f"Successfully imported {module_type}: {modname}")
            except Exception as e:
                # Log but don't crash if a plugin fails to load
                print(f"Warning: Failed to load plugin module {modname}: {e}")

        print("Plugin auto-discovery completed.")
