from django.db import models


class AudioDevice(models.Model):
    kind: str = models.CharField(max_length=255)
    sampling_rate = models.IntegerField()
    format = models.CharField(max_length=9, choices=[
        ("S16LE", "16-bit Signed Little Endian"),
        ("S24LE", "24-bit Signed Little Endian"),
        ("S32LE", "32-bit Signed Little Endian"),
        ("S16BE", "16-bit Signed Big Endian"),
        ("S24BE", "24-bit Signed Big Endian"),
        ("S32BE", "32-bit Signed Big Endian"),
        ("FLOAT32LE", "32-bit Floating Point Little Endian"),
        ("FLOAT32BE", "64-bit Floating Point Little Endian")
    ])