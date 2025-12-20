from django.db import models
from django.core.exceptions import ValidationError

from .known_audio_device import KnownAudioDevice


class Pipeline(models.Model):
    """Represents a CamillaDSP audio processing pipeline configuration."""

    name = models.CharField(max_length=255, unique=True, help_text="User-friendly pipeline name")
    description = models.TextField(blank=True, help_text="Optional description of this pipeline")

    input_device = models.ForeignKey(
        KnownAudioDevice,
        on_delete=models.PROTECT,
        related_name='input_pipelines',
        limit_choices_to={'device_type': 'CAPTURE'},
        help_text="Audio input (capture) device"
    )

    output_device = models.ForeignKey(
        KnownAudioDevice,
        on_delete=models.PROTECT,
        related_name='output_pipelines',
        limit_choices_to={'device_type': 'PLAYBACK'},
        help_text="Audio output (playback) device"
    )

    enabled = models.BooleanField(default=False, help_text="Whether this pipeline is enabled")
    active = models.BooleanField(default=False, help_text="Whether this pipeline is currently active/running")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        """Validate that input is CAPTURE and output is PLAYBACK."""
        if self.input_device and self.input_device.device_type != 'CAPTURE':
            raise ValidationError({'input_device': 'Input device must be a CAPTURE device.'})

        if self.output_device and self.output_device.device_type != 'PLAYBACK':
            raise ValidationError({'output_device': 'Output device must be a PLAYBACK device.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.input_device.name} → {self.output_device.name})"
