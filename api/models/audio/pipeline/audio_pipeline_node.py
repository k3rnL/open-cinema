from enum import Enum

from django.db import models

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot


class AudioPipelineNode(models.Model):

    type_name = models.CharField(
        max_length=255,
        default=None,
        null=False,
        help_text="The type of the node, e.g. 'AudioProcessor'"
    )

    pipeline = models.ForeignKey(AudioPipeline, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    static_slots: list[AudioPipelineNodeSlot] = []

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        return []

