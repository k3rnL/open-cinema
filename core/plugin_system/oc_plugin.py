"""Base class for API plugins that can register routes."""

from abc import ABC, abstractmethod
from typing import List

from core.audio.audio_backend import AudioBackend


class OCPlugin(ABC):
    """
    Base class for Open Cinema plugins.

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
        Return list of URL patterns to register for this plugin.

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

    def get_audio_backend(self) -> None | AudioBackend:
        """
        A plugin can provide an audio backend to be registered and used
        """
        return None

    # Register all plugins
    registry = {}

    @staticmethod
    def get_registered_plugins() -> List["OCPlugin"]:
        return list(OCPlugin.registry.values())

    @staticmethod
    def get_registered_audio_backends() -> List[AudioBackend]:
        return [plugin.get_audio_backend() for plugin in OCPlugin.get_registered_plugins() if plugin.get_audio_backend() is not None]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Don't register the abstract base itself
        if cls is OCPlugin:
            return

        # Derive the plugin key
        key = getattr(cls, "__name__")
        if key in OCPlugin.registry:
            raise ValueError(f"Duplicate plugin name: {key}")

        OCPlugin.registry[key] = cls()
