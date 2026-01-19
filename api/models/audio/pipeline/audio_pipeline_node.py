from enum import Enum

from django.db import models
from django.db.models.fields import Field

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager


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

    def get_manager(self) -> 'AudioPipelineNodeManager':
        raise NotImplementedError('Erroneous Call to get_manager() on AudioPipelineNode class, it must be called on '
                                  'specialized call and be implemented by subclasses.')

    @classmethod
    def get_exposed_fields(cls) -> list[Field]:
        """
        Returns a list of Django model fields that are exposed for this node.
        Can be overridden by subclasses to expose only a subset of the fields.
        """
        return cls._meta.local_fields