import logging
import uuid
from enum import IntEnum

import pulsectl
from pulsectl import PulseError, PulseIndexError

from api.models import KnownAudioDevice
from core.audio.audio_backend import AudioBackend
from core.audio.audio_backend_exception import AudioBackendException
from core.audio.audio_device import AudioDevice, AudioDeviceType
from core.audio.sample_format_enum import SampleFormatEnum
from plugin.pulseaudio.models.pulse_audio_created_device import PulseAudioCreatedModule

logger = logging.getLogger(__name__)


class PaSampleFormat(IntEnum):
    INVALID = -1
    U8 = 0
    ALAW = 1
    ULAW = 2
    S16LE = 3
    S16BE = 4
    FLOAT32LE = 5
    FLOAT32BE = 6
    S32LE = 7
    S32BE = 8
    S24LE = 9
    S24BE = 10
    S24_32LE = 11
    S24_32BE = 12


class PulseAudioBackend(AudioBackend):

    @property
    def name(self):
        return "pulseaudio"

    def get_source(self, device_name: str) -> AudioDevice:
        with pulsectl.Pulse("list-devices") as p:
            source = p.get_source_by_name(device_name)
            if source is None:
                raise ValueError(f"Device '{device_name}' not found")
            return AudioDevice(
                self,
                source.name,
                source.proplist.get('device.description'),
                AudioDeviceType.CAPTURE,
                SampleFormatEnum(PaSampleFormat(source.sample_spec.format).name),
                source.sample_spec.rate,
                source.channel_count
            )

    def get_sink(self, device_name: str) -> AudioDevice:
        with pulsectl.Pulse("list-devices") as p:
            sink = p.get_sink_by_name(device_name)
            if sink is None:
                raise ValueError(f"Device '{device_name}' not found")
            return AudioDevice(
                self,
                sink.name,
                sink.proplist.get('device.description'),
                AudioDeviceType.PLAYBACK,
                SampleFormatEnum(PaSampleFormat(sink.sample_spec.format).name),
                sink.sample_spec.rate,
                sink.channel_count
            )

    def devices(self):
        devices = []
        try:
            with pulsectl.Pulse("list-devices") as p:
                # Process sources (capture devices)
                for source in p.source_list():
                    try:
                        logger.debug(f"Found PulseAudio source: {source.name}")
                        source = p.get_source_by_name(source.name)  # There is a bug in pulsectl, this is the way to get the real informations

                        devices.append(AudioDevice(
                            self,
                            source.name,
                            source.proplist.get('device.description'),
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
                            sink.proplist.get('device.string'),
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

    def add_module(self, name: str, args: list[str] = list) -> PulseAudioCreatedModule:
        internal_id = str(hash(' '.join(args)))
        try:
            with pulsectl.Pulse("create-module") as p:
                module_index = p.module_load(name, args)
                return PulseAudioCreatedModule.objects.create(module_id=module_index, internal_id=internal_id)
        except PulseError as e:
            logger.error(f"Failed to load PulseAudio module: {e}")
            raise e

    def del_module(self, module: PulseAudioCreatedModule):
        try:
            with pulsectl.Pulse("unload-module") as p:
                for m in p.module_list():
                    internal_id = str(hash(m.argument))
                    if internal_id == module.internal_id:
                        p.module_unload(module.module_id)
                        module.delete()
                        return
        except PulseError as e:
            logger.error(f"Failed to unload PulseAudio module: {e}")
            raise e

    def del_device(self, device: KnownAudioDevice):
        if device.backend != self.name:
            raise ValueError(f"Cannot delete device {device.name} from backend {device.backend}, expected {self.name}")

        try:
            with pulsectl.Pulse("delete-device") as p:
                print(f"Deleting device {device.name} of type {device.device_type}")
                if device.device_type == AudioDeviceType.PLAYBACK:
                    d = p.get_sink_by_name(device.name)
                else:
                    d = p.get_source_by_name(device.name)
                p.module_unload(d.owner_module)
                device.delete()
        except PulseError as e:
            logger.error(f"Failed to delete PulseAudio device: {e}")
            raise e

    def get_volume(self, device: KnownAudioDevice) -> int:
        try:
            with pulsectl.Pulse("list-devices") as p:
                if device.device_type == AudioDeviceType.CAPTURE:
                    pulse_device = p.get_source_by_name(device.name)
                else:
                    pulse_device = p.get_sink_by_name(device.name)
                return int(pulse_device.volume.value_flat * 100)
        except PulseIndexError:
            return 0
        except PulseError as e:
            raise AudioBackendException(f"Failed to get volume for device {device.name}: {e}") from e

    def set_volume(self, device: KnownAudioDevice, volume: int) -> None:
        try:
            with pulsectl.Pulse("set-volume") as p:
                if device.device_type == AudioDeviceType.CAPTURE:
                    pulse_device = p.get_source_by_name(device.name)
                else:
                    pulse_device = p.get_sink_by_name(device.name)
                device_volume = pulse_device.volume
                device_volume.value_flat = float(volume) / 100.0
                p.volume_set(pulse_device, device_volume)
        except PulseIndexError:
            # Device does not exist (yet?), mark it as inactive
            device.active = False
            device.save()
        except PulseError as e:
            logger.error(f"Failed to set volume for device {device.name}: {e}")
            raise AudioBackendException(f"Failed to set volume for device {device.name}: {e}") from e

