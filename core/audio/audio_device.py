from enum import Enum

from core.audio.audio_backend import AudioBackend
from core.audio.sample_format_enum import SampleFormatEnum


class AudioDeviceType(Enum):
    CAPTURE = 1
    PLAYBACK = 2

class AudioDevice:

    def __init__(self,
                 backend: AudioBackend,
                 name: str,
                 nice_name: str,
                 device_type: AudioDeviceType,
                 device_format: SampleFormatEnum,
                 sample_rate: int,
                 channels: int):
        self.backend = backend
        self.name = name
        self.nice_name = nice_name
        self.device_type = device_type
        self.device_format = device_format
        self.sample_rate = sample_rate
        self.channels = channels

    def __str__(self):
        return f"<{type(self).__name__}: {self.name}, {self.nice_name}, {self.device_type}, {self.device_format.name}, {self.sample_rate} Hz, {self.channels} channels>"

