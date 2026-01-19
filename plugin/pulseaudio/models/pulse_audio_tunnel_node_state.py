from django.db import models

from api.models import KnownAudioDevice
from plugin.pulseaudio.models.pulse_audio_created_device import PulseAudioCreatedModule


class PulseAudioTunnelNodeState(models.Model):

    node = models.OneToOneField('PulseAudioTunnelNode', on_delete=models.CASCADE)

    module = models.ForeignKey(PulseAudioCreatedModule, on_delete=models.CASCADE, null=False)

    device = models.ForeignKey(KnownAudioDevice, on_delete=models.RESTRICT, null=True)

    class Meta:
        app_label = 'api'