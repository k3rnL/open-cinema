from django.db import models

from api.models import KnownAudioDevice
from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode


class AudioPipelineDeviceNode(AudioPipelineIONode):

    device = models.ForeignKey(KnownAudioDevice, on_delete=models.RESTRICT)

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from core.audio.audio_pipeline_device_node_manager import AudioPipelineDeviceNodeManager
        return AudioPipelineDeviceNodeManager(self)

