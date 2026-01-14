from django.db import models

from api.models.audio.audio_pipeline import AudioPipeline


class AudioPipelineNode(models.Model):

    kind = models.CharField(
        help_text="Name of the python object in the plugin domain representing this item",
    )

    plugin = models.CharField(
        help_text="Plugin that manages this item",
    )

    pipeline = models.ForeignKey(AudioPipeline, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    parameters = models.JSONField(
        help_text="JSON object containing parameters to create the python object",
    )
