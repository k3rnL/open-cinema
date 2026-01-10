import logging
from enum import IntEnum

import pulsectl

from core.audio.audio_backend import AudioBackend
from core.audio.audio_device import AudioDevice, AudioDeviceType
from core.audio.sample_format_enum import SampleFormatEnum

logger = logging.getLogger(__name__)


class PaSampleFormat(IntEnum):
    INVALID      = -1
    U8           = 0
    ALAW         = 1
    ULAW         = 2
    S16LE        = 3
    S16BE        = 4
    FLOAT32LE    = 5
    FLOAT32BE    = 6
    S32LE        = 7
    S32BE        = 8
    S24LE        = 9
    S24BE        = 10
    S24_32LE     = 11
    S24_32BE     = 12


class PulseAudioBackend(AudioBackend):

    @property
    def name(self):
        return "pulseaudio"

    def devices(self):
        devices = []
        try:
            with pulsectl.Pulse("list-devices") as p:
                # Process sources (capture devices)
                for source in p.source_list():
                    try:
                        logger.debug(f"Found PulseAudio source: {source.name}")
                        source = p.get_source_by_name(source.name) # There is a bug in pulsectl,
                                                                          # This is the way to get the real informations
                        devices.append(AudioDevice(
                            self,
                            source.name,
                            AudioDeviceType.CAPTURE,
                            SampleFormatEnum(PaSampleFormat(source.sample_spec.format).name),
                            source.sample_spec.rate,
                            source.channel_count
                        ))
                        print(f"{source.name}: format:{source.sample_spec.format} ch: {source.channel_count}")
                    except Exception as e:
                        print(e)
                        logger.error(f"Failed to process source {source.name}: {e}")

                # Process sinks (playback devices)
                for sink in p.sink_list():
                    try:
                        logger.debug(f"Found PulseAudio sink: {sink.name}")
                        sink = p.get_sink_by_name(sink.name)
                        devices.append(AudioDevice(
                            self,
                            sink.name,
                            AudioDeviceType.PLAYBACK,
                            SampleFormatEnum(PaSampleFormat(sink.sample_spec.format).name),
                            sink.sample_spec.rate,
                            sink.sample_spec.channels
                        ))
                    except Exception as e:
                        logger.error(f"Failed to process sink {sink.name}: {e}")

        except pulsectl.PulseError as e:
            logger.error(f"PulseAudio error while listing devices: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while listing PulseAudio devices: {e}")

        logger.info(f"PulseAudio backend discovered {len(devices)} devices")
        return devices