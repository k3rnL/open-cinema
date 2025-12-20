from abc import ABC, abstractmethod
from typing import List

class AudioBackend(ABC):

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def devices(self):
        pass

class AudioBackends:

    @staticmethod
    def get_all() -> List[AudioBackend]:
        """Returns instances of all discovered AudioBackend implementations."""
        return [backend_class() for backend_class in AudioBackend.__subclasses__()]

    @staticmethod
    def get_all_devices():
        """Returns all audio devices from all backends."""
        devices = []
        for backend in AudioBackends.get_all():
            devices.extend(backend.devices())
        return devices
