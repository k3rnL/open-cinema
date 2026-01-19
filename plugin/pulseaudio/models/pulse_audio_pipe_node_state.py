from typing import TYPE_CHECKING

from django.db import models

from plugin.pulseaudio.models.pulse_audio_created_device import PulseAudioCreatedModule


class PulseAudioPipeNodeState(models.Model):

    node = models.OneToOneField('PulseAudioPipeNode', on_delete=models.CASCADE)

    module = models.ForeignKey(PulseAudioCreatedModule, on_delete=models.CASCADE, null=False)

    class Meta:
        app_label = 'api'
