from django.db import models

from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot


class AudioPipelineEdge(models.Model):

    slot_a = models.ForeignKey(AudioPipelineNodeSlot, on_delete=models.CASCADE, related_name='outgoing_edges')
    slot_b = models.ForeignKey(AudioPipelineNodeSlot, on_delete=models.CASCADE, related_name='incoming_edges')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

