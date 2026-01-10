"""Counter API Plugin - provides REST endpoints for counter operations."""

from core.audio.audio_backend import AudioBackend
from core.plugin_system.oc_plugin import OCPlugin
from plugin.counter.models import CounterLog
from plugin.pulseaudio.audio.backend import PulseAudioBackend


class PulseAudioOCPlugin(OCPlugin):
    """
    PulseAudio plugin, provides pulse audio backend capabilities
    """

    @property
    def plugin_name(self):
        return "pulseaudio"

    def get_urls(self):
        return [ ]

    def get_audio_backend(self) -> None | AudioBackend:
        return PulseAudioBackend()