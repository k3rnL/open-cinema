from typing import TYPE_CHECKING

from django.db import models
from django.db.models import Field

from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager

if TYPE_CHECKING:
    from plugin.pulseaudio.audio.pulse_audio_pipe_node_manager import PulseAudioPipeNodeManager


class PulseAudioPipeNode(AudioPipelineProcessingNode):
    """Represents a PulseAudio pipe node in the audio pipeline."""

    latency = models.IntegerField(default=200, help_text='Latency in milliseconds')

    class Meta:
        app_label = 'api'

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from plugin.pulseaudio.audio.pulse_audio_pipe_node_manager import PulseAudioPipeNodeManager
        return PulseAudioPipeNodeManager(self)

    @classmethod
    def get_exposed_fields(cls) -> list[Field]:
        return [
            cls._meta.get_field('latency')
        ]