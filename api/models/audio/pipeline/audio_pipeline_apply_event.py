from django.db import models
from django_enum import EnumField

from api.models import AudioPipelineNode
from api.models.audio.pipeline.audio_pipeline_apply_job import AudioPipelineApplyJob


class EventType(models.TextChoices):
    START = 'START'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
    STARTED_NODE = 'STARTED_NODE'
    COMPLETED_NODE = 'COMPLETED_NODE'


class AudioPipelineApplyEvent(models.Model):
    job = models.ForeignKey(AudioPipelineApplyJob, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)

    event_type = EnumField(EventType, null=False)

    node = models.ForeignKey(
        AudioPipelineNode,
        on_delete=models.CASCADE,
        null=True
    )

    # See PipelineJobEventData
    data = models.JSONField(null=True)

    class Meta:
        ordering = ['-created_at']
