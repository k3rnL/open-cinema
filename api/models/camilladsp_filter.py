from django.db import models

from .camilladsp_pipeline import Pipeline


class Filter(models.Model):
    """Represents a filter in a CamillaDSP pipeline (for future extensibility)."""

    FILTER_TYPE_CHOICES = [
        ('GAIN', 'Gain'),
        ('VOLUME', 'Volume'),
        ('LOUDNESS', 'Loudness'),
        ('DELAY', 'Delay'),
        ('FIR', 'FIR Filter'),
        ('IIR', 'IIR Filter'),
        ('BIQUAD', 'Biquad'),
        ('COMPRESSOR', 'Compressor'),
        ('LIMITER', 'Limiter'),
        ('EQ', 'Equalizer'),
    ]

    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name='filters',
        help_text="Pipeline this filter belongs to"
    )

    filter_type = models.CharField(
        max_length=20,
        choices=FILTER_TYPE_CHOICES,
        help_text="Type of filter"
    )

    order = models.IntegerField(
        default=0,
        help_text="Position in the filter chain (lower = earlier)"
    )

    config = models.JSONField(
        default=dict,
        help_text="Filter configuration parameters (JSON)"
    )

    enabled = models.BooleanField(default=True, help_text="Whether this filter is enabled")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['pipeline', 'order']
        indexes = [
            models.Index(fields=['pipeline', 'order']),
        ]

    def __str__(self):
        return f"{self.pipeline.name} - {self.filter_type} (order: {self.order})"
