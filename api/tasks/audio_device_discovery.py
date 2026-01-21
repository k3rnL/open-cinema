import logging
from datetime import timedelta
from django.utils import timezone

from api.models import KnownAudioDevice
from core.audio.audio_backends import AudioBackends

logger = logging.getLogger(__name__)


def discover_and_update_audio_devices():
    """
    Periodic task to discover audio devices and update the KnownAudioDevice table.
    This should be run regularly (e.g., every 30 seconds) to keep device status current.
    """
    logger.info("Starting audio device discovery task")

    try:
        # Discover all devices from backend
        discovered_devices = AudioBackends.get_all_devices()

        # Track which devices we've seen
        seen_device_keys = set()

        for device in discovered_devices:
            # Create a unique key for this device
            device_key = (device.backend.name, device.name)
            seen_device_keys.add(device_key)

            # Update or create a device in the database
            known_device, created = KnownAudioDevice.objects.update_or_create(
                backend=device.backend.name,
                name=device.name,
                defaults={
                    'nice_name': device.nice_name,
                    'device_type': device.device_type.name,
                    'format': device.device_format.name,
                    'sample_rate': device.sample_rate,
                    'channels': device.channels,
                    'active': True,
                }
            )

            if created:
                logger.info(f"New device discovered: {device.name} ({device.backend.name})")
            else:
                logger.debug(f"Updated device: {device.name} ({device.backend.name})")

        # Mark devices as inactive if they weren't discovered
        # (but only if they were seen recently - within last 5 minutes)
        inactive_devices = KnownAudioDevice.objects.filter(
            active=True,
        ).exclude(
            backend__in=[key[0] for key in seen_device_keys],
            name__in=[key[1] for key in seen_device_keys]
        )

        for device in inactive_devices:
            device_key = (device.backend, device.name)
            if device_key not in seen_device_keys:
                device.active = False
                device.save()
                logger.info(f"Device marked as inactive: {device.name} ({device.backend})")

        logger.info(f"Audio device discovery completed. Found {len(discovered_devices)} active devices")

    except Exception as e:
        logger.error(f"Error during audio device discovery: {e}", exc_info=True)


# For manual invocation
if __name__ == "__main__":
    discover_and_update_audio_devices()
