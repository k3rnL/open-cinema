from django.db import models


class AudioPipelineNodePosition(models.Model):

    node = models.OneToOneField(
        'AudioPipelineNode',
        on_delete=models.CASCADE,
        related_name='position'
    )

    x = models.IntegerField()
    y = models.IntegerField()