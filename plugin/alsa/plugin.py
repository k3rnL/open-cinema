"""Counter API Plugin - provides REST endpoints for counter operations."""

from core.audio.audio_backend import AudioBackend
from core.plugin_system.oc_plugin import OCPlugin
from plugin.alsa.audio.backend import AlsaAudioBackend
from plugin.counter.models import CounterLog
from plugin.pulseaudio.audio.backend import PulseAudioBackend


class AlsaOCPlugin(OCPlugin):
    """
    PulseAudio plugin, provides pulse audio backend capabilities
    """

    @property
    def plugin_name(self):
        return "alsa"

    def get_urls(self):
        return [ ]

    def get_audio_backend(self) -> None | AudioBackend:
        return AlsaAudioBackend()