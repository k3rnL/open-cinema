from django.db import models

from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode


class AudioPipelineEdge(models.Model):

    node_a = models.ForeignKey(AudioPipelineNode, on_delete=models.CASCADE, related_name='outgoing_edges')
    node_b = models.ForeignKey(AudioPipelineNode, on_delete=models.CASCADE, related_name='incoming_edges')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

