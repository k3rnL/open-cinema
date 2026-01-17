from django.db import models

from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.validation_result import ValidationResultNode


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

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        field_errors = {}

        if self.server is None or self.server == '':
            field_errors['server'] = 'Server must be specified'
        if self.mode is None or self.mode == '':
            field_errors['mode'] = 'Mode must be specified'
        if self.mode == 'SOURCE' or self.mode == 'source' and self.source is None:
            field_errors['source'] = 'Source must be specified when mode is source'
        if self.mode == 'SINK' or self.mode == 'sink' and self.sink is None:
            field_errors['sink'] = 'Sink must be specified when mode is sink'

        return ValidationResultNode(self.id, [], field_errors, {}) if len(field_errors) > 0 else None