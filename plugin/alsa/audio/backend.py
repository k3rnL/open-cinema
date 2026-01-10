import logging

import alsaaudio

from core.audio.audio_backend import AudioBackend
from core.audio.audio_device import AudioDevice, AudioDeviceType
from core.audio.sample_format_enum import SampleFormatEnum

logger = logging.getLogger(__name__)


# Mapping ALSA format constants to SampleFormatEnum
ALSA_FORMAT_MAP = {
    alsaaudio.PCM_FORMAT_U8: SampleFormatEnum.U8,
    alsaaudio.PCM_FORMAT_S16_LE: SampleFormatEnum.S16LE,
    alsaaudio.PCM_FORMAT_S16_BE: SampleFormatEnum.S16BE,
    alsaaudio.PCM_FORMAT_S24_LE: SampleFormatEnum.S24LE,
    alsaaudio.PCM_FORMAT_S24_BE: SampleFormatEnum.S24BE,
    alsaaudio.PCM_FORMAT_S32_LE: SampleFormatEnum.S32LE,
    alsaaudio.PCM_FORMAT_S32_BE: SampleFormatEnum.S32BE,
    alsaaudio.PCM_FORMAT_FLOAT_LE: SampleFormatEnum.FLOAT32LE,
    alsaaudio.PCM_FORMAT_FLOAT_BE: SampleFormatEnum.FLOAT32BE,
}


class AlsaAudioBackend(AudioBackend):

    @property
    def name(self):
        return "alsa"

    def devices(self):
        devices = []
        try:
            # Get PCM capture devices
            try:
                capture_devices = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
                for device_name in capture_devices:
                    try:
                        logger.debug(f"Found ALSA capture device: {device_name}")
                        # Try to open the device to get its capabilities
                        pcm = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, device=device_name)

                        # Get device info - use defaults if we can't query specific values
                        # Note: pyalsaaudio doesn't provide direct access to all device capabilities
                        # We'll use common defaults
                        devices.append(AudioDevice(
                            self,
                            device_name,
                            AudioDeviceType.CAPTURE,
                            SampleFormatEnum.S16LE,  # Default format
                            48000,  # Default sample rate
                            2  # Default channel count
                        ))
                        pcm.close()
                    except alsaaudio.ALSAAudioError as e:
                        logger.warning(f"Failed to process capture device {device_name}: {e}")
            except alsaaudio.ALSAAudioError as e:
                logger.error(f"Failed to list ALSA capture devices: {e}")

            # Get PCM playback devices
            try:
                playback_devices = alsaaudio.pcms(alsaaudio.PCM_PLAYBACK)
                for device_name in playback_devices:
                    try:
                        logger.debug(f"Found ALSA playback device: {device_name}")
                        pcm = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK, device=device_name)

                        devices.append(AudioDevice(
                            self,
                            device_name,
                            AudioDeviceType.PLAYBACK,
                            SampleFormatEnum.S16LE,  # Default format
                            48000,  # Default sample rate
                            2  # Default channel count
                        ))
                        pcm.close()
                    except alsaaudio.ALSAAudioError as e:
                        logger.warning(f"Failed to process playback device {device_name}: {e}")
            except alsaaudio.ALSAAudioError as e:
                logger.error(f"Failed to list ALSA playback devices: {e}")

        except Exception as e:
            logger.error(f"Unexpected error while listing ALSA devices: {e}")

        logger.info(f"ALSA backend discovered {len(devices)} devices")
        return devices