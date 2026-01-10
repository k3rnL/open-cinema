from django.db import models


class PreferencesAudioBackend(models.Model):

    name = models.CharField(
        max_length=255,
        help_text="The name of the backend"
    )

    enabled = models.BooleanField(
        help_text="Whether this backend is enabled or not and should be used in device discovery"
    )