from abc import ABC, abstractmethod
from typing import List

from api.models.preferences_audio_backend import PreferencesAudioBackend
from core.audio.audio_backend import AudioBackend
from core.plugin_system import OCPlugin

class AudioBackends:

    @staticmethod
    def get_all() -> List[AudioBackend]:
        """Returns instances of all discovered AudioBackend implementations."""
        return OCPlugin.get_registered_audio_backends()

    @staticmethod
    def get_all_devices():
        """Returns all audio devices from enabled backends."""
        enabled_backends_name = [b.name for b in PreferencesAudioBackend.objects.all() if b.enabled]
        devices = []
        for backend in AudioBackends.get_all():
            if backend.name in enabled_backends_name:
                devices.extend(backend.devices())
        return devices
