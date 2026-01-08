"""Base class for API plugins that can register routes."""

from abc import ABC, abstractmethod
from typing import List


class APIPlugin(ABC):
    """
    Base class for plugins that want to register API routes.

    Plugins implementing this class will have their URLs automatically
    registered under /api/plugins/{plugin_name}/.

    Example:
        class MyPlugin(APIPlugin):
            @property
            def plugin_name(self):
                return "myplugin"

            def get_urls(self):
                return [
                    path('status', self.get_status, name='status'),
                    path('action/<int:id>', self.do_action, name='action'),
                ]

            def get_status(self, request):
                return JsonResponse({'status': 'ok'})
    """

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """
        Unique plugin identifier (used in URL namespace).

        This will be used as the URL prefix: /api/plugins/{plugin_name}/
        Must be URL-safe (lowercase, no spaces).

        Returns:
            str: Plugin name
        """
        pass

    @abstractmethod
    def get_urls(self) -> List:
        """
        Return list of URL patterns for this plugin.

        These URLs will be automatically prefixed with /api/plugins/{plugin_name}/

        Example:
            return [
                path('info', self.get_info, name='info'),
                path('control/<int:id>', self.control, name='control'),
            ]

        Returns:
            List[URLPattern]: Django URL patterns
        """
        pass

    registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Don't register the abstract base itself
        if cls is APIPlugin:
            return

        # Derive the plugin key
        key = getattr(cls, "__name__")
        if key in APIPlugin.registry:
            raise ValueError(f"Duplicate plugin name: {key}")

        APIPlugin.registry[key] = cls
