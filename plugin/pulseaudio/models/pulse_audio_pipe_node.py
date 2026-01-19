from typing import TYPE_CHECKING

from django.db.models import Field

from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager

if TYPE_CHECKING:
    from plugin.pulseaudio.audio.pulse_audio_pipe_node_manager import PulseAudioPipeNodeManager


class PulseAudioPipeNode(AudioPipelineProcessingNode):
    """Represents a PulseAudio pipe node in the audio pipeline."""

    class Meta:
        app_label = 'api'

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from plugin.pulseaudio.audio.pulse_audio_pipe_node_manager import PulseAudioPipeNodeManager
        return PulseAudioPipeNodeManager(self)

    @classmethod
    def get_exposed_fields(cls) -> list[Field]:
        return []