from django.db import models

from api.models import CamillaDSPPipeline, camilladsp_pipeline
from api.models.audio.pipeline.audio_pipeline_node import Slot, SlotType, SlotDirection
from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode


class CamillaDSPAudioPipelineNode(AudioPipelineProcessingNode):

    camilladsp_pipeline = models.ForeignKey(
        CamillaDSPPipeline,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audio_pipeline_nodes',
        verbose_name='Camilla DSP Pipeline',
        help_text='The Camilla DSP pipeline associated with this node.'
    )

    def get_dynamic_slots_schematics(self) -> list[Slot]:
        if self.camilladsp_pipeline is None:
            return []

        input_device = self.camilladsp_pipeline.input_device
        output_device = self.camilladsp_pipeline.output_device
        return [
            Slot(input_device.name, SlotType.AUDIO, SlotDirection.INPUT),
            Slot(output_device.name, SlotType.AUDIO, SlotDirection.OUTPUT)
        ]

    class Meta:
        app_label = 'api'

