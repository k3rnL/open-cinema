from django.db import models
from django_enum import EnumField

from api.models.audio.audio_pipeline import AudioPipeline

class JobStatus(models.TextChoices):
    STARTED = 'STARTED'
    RUNNING = 'RUNNING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'

class AudioPipelineApplyJob(models.Model):

    pipeline = models.ForeignKey(AudioPipeline, on_delete=models.CASCADE)

    status = EnumField(JobStatus, default=JobStatus.STARTED)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
