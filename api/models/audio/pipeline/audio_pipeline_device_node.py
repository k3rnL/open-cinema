from django.db import models

from api.models import KnownAudioDevice
from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode


class AudioPipelineDeviceNode(AudioPipelineIONode):

    device = models.ForeignKey(KnownAudioDevice, on_delete=models.RESTRICT)