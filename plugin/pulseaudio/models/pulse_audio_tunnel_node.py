from typing import TYPE_CHECKING

from django.db import models
from django.db.models import Field

from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager

if TYPE_CHECKING:
    from plugin.pulseaudio.audio.pulse_audio_tunnel_node_manager import PulseAudioTunnelNodeManager


class PulseAudioTunnelNode(AudioPipelineIONode):
    """Represents a PulseAudio tunnel node in the audio pipeline."""

    server = models.CharField(
        max_length=255,
        null=True,
        help_text='The server to connect to'
    )

    mode = models.CharField(
        max_length=255,
        null=True,
        choices=[('SOURCE', 'source'), ('SINK', 'sink')],
        help_text='The mode of the tunnel. Either source or sink'
    )

    source = models.CharField(
        max_length=255,
        null=True,
        help_text='The source on the remote server. Only available in source mode')

    sink = models.CharField(
        max_length=255,
        null=True,
        help_text='The sink on the remote server. Only available in sink mode'
    )

    cookie = models.CharField(
        max_length=255,
        null=True,
        help_text='The authentication cookie file to use'
    )

    class Meta:
        app_label = 'api'

    @classmethod
    def get_exposed_fields(cls) -> list[Field]:
        return [
            cls._meta.get_field('server'),
            cls._meta.get_field('mode'),
            cls._meta.get_field('source'),
            cls._meta.get_field('sink'),
            cls._meta.get_field('cookie')
        ]

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from plugin.pulseaudio.audio.pulse_audio_tunnel_node_manager import PulseAudioTunnelNodeManager
        return PulseAudioTunnelNodeManager(self)