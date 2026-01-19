from typing import TYPE_CHECKING

from django.db import models

from api.models import CamillaDSPPipeline
from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager

if TYPE_CHECKING:
    from core.camilladsp.camilladsp_audio_pipeline_node_manager import CamillaDSPAudioPipelineNodeManager

class CamillaDSPAudioPipelineNode(AudioPipelineProcessingNode):

    camilladsp_pipeline = models.ForeignKey(
        CamillaDSPPipeline,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audio_pipeline_nodes',
        verbose_name='Camilla DSP Pipeline',
        help_text='The Camilla DSP pipeline associated with this node.'
    )

    class Meta:
        app_label = 'api'

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from core.camilladsp.camilladsp_audio_pipeline_node_manager import CamillaDSPAudioPipelineNodeManager
        return CamillaDSPAudioPipelineNodeManager(self)