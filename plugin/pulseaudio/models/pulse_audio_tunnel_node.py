from django.db import models

from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection


class PulseAudioTunnelNode(AudioPipelineIONode):
    """Represents a PulseAudio tunnel node in the audio pipeline."""

    server = models.CharField(
        max_length=255,
        help_text='The server to connect to'
    )

    mode = models.CharField(
        max_length=255,
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

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        if self.mode == 'SOURCE' or self.mode == 'source':
            name = self.source if self.source is not None else 'Source Name'
            return [AudioPipelineNodeSlot(name=name, type=SlotType.AUDIO, direction=SlotDirection.OUTPUT, node=self)]
        elif self.mode == 'SINK' or self.mode == 'sink':
            name = self.sink if self.sink is not None else 'Sink Name'
            return [AudioPipelineNodeSlot(name=name, type=SlotType.AUDIO, direction=SlotDirection.INPUT, node=self)]
        return []

    class Meta:
        app_label = 'api'
