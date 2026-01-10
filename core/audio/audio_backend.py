from abc import ABC, abstractmethod
from typing import List

from api.models import AudioDevice

class AudioBackend(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def devices(self) -> List[AudioDevice]:
        pass
