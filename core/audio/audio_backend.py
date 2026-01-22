from abc import ABC, abstractmethod
from typing import List

from api.models import AudioDevice, KnownAudioDevice


class AudioBackend(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def devices(self) -> List[AudioDevice]:
        pass

    @abstractmethod
    def get_volume(self, device: KnownAudioDevice) -> int:
        """
        Returns the volume of the given device in percentage (0-100).
        """
        pass

    @abstractmethod
    def set_volume(self, device: KnownAudioDevice, volume: int) -> None:
        """
        Sets the volume of the given device to the specified percentage (0-100).
        """
        pass
