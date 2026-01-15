from django.db import models

from api.models.audio.audio_pipeline import AudioPipeline


class AudioPipelineNode(models.Model):

    pipeline = models.ForeignKey(AudioPipeline, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
