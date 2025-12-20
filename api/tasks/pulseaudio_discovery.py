from celery import shared_task

import api.models.audio_device


@shared_task
def sync_pulseaudio_devices():
    # api.models.audio_device.AudioDevice.
    pulsectl.