from django.db import models


class KnownAudioDevice(models.Model):
    """Represents an audio device discovered by the system."""

    DEVICE_TYPE_CHOICES = [
        ('CAPTURE', 'Capture'),
        ('PLAYBACK', 'Playback'),
    ]

    FORMAT_CHOICES = [
        ('S16LE', '16-bit Signed Little Endian'),
        ('S24LE', '24-bit Signed Little Endian'),
        ('S32LE', '32-bit Signed Little Endian'),
        ('S16BE', '16-bit Signed Big Endian'),
        ('S24BE', '24-bit Signed Big Endian'),
        ('S32BE', '32-bit Signed Big Endian'),
        ('FLOAT32LE', '32-bit Floating Point Little Endian'),
        ('FLOAT32BE', '32-bit Floating Point Big Endian'),
        ('U8', '8-bit Unsigned'),
        ('ALAW', 'A-law'),
        ('ULAW', 'μ-law'),
        ('S24_32LE', '24-bit in 32-bit Little Endian'),
        ('S24_32BE', '24-bit in 32-bit Big Endian'),
    ]

    backend = models.CharField(max_length=50, help_text="Audio backend name (e.g., 'pulseaudio')")
    name = models.CharField(max_length=255, help_text="Device identifier")
    nice_name = models.CharField(max_length=255, help_text="Device nice name", null=True)
    device_type = models.CharField(max_length=10, choices=DEVICE_TYPE_CHOICES)
    format = models.CharField(max_length=15, choices=FORMAT_CHOICES)
    sample_rate = models.IntegerField(help_text="Sample rate in Hz")
    channels = models.IntegerField(help_text="Number of audio channels")
    active = models.BooleanField(default=False, help_text="Whether device is currently connected")

    last_seen = models.DateTimeField(auto_now=True, help_text="Last time device was detected")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['backend', 'name']]
        indexes = [
            models.Index(fields=['active']),
            models.Index(fields=['device_type']),
        ]

    def __str__(self):
        status = "active" if self.active else "inactive"
        return f"{self.name} ({self.backend}, {self.device_type}, {status})"
