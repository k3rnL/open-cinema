from django.db import models


class AudioPipeline(models.Model):

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Pipeline name"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this pipeline"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    active = models.BooleanField(default=False)

    stale = models.BooleanField(default=False)