import logging
import traceback

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models.deletion import ProtectedError

from api.models import KnownAudioDevice
from core.audio.audio_backend_exception import AudioBackendException
from core.audio.audio_backends import AudioBackends

logger = logging.getLogger(__name__)

@require_http_methods(["GET"])
def get_devices(request):
    """
    Get all known audio devices from the database.
    Query parameters:
    - active: Filter by active status (true/false)
    - device_type: Filter by device type (CAPTURE/PLAYBACK)
    """
    # Get query parameters
    active_filter = request.GET.get('active')
    device_type_filter = request.GET.get('device_type')

    # Start with all devices
    devices = KnownAudioDevice.objects.all()

    # Apply filters
    if active_filter is not None:
        active_bool = active_filter.lower() == 'true'
        devices = devices.filter(active=active_bool)

    if device_type_filter:
        devices = devices.filter(device_type=device_type_filter.upper())

    volumes = {}
    for device in devices:
        try:
            volumes[device.id] = AudioBackends.get_backend(device.backend).get_volume(device)
        except AudioBackendException as e:
            logger.error(f"Failed to get volume for device {device.id}: {e}")
            volumes[device.id] = 0
            continue

    # Convert to JSON
    devices_data = [
        {
            'id': device.id,
            'backend': device.backend,
            'name': device.name,
            'nice_name': device.nice_name,
            'device_type': device.device_type,
            'format': device.format,
            'sample_rate': device.sample_rate,
            'channels': device.channels,
            'active': device.active,
            'last_seen': device.last_seen.isoformat(),
            'volume': volumes[device.id],
        }
        for device in devices
    ]

    return JsonResponse(devices_data, safe=False)


@require_http_methods(["DELETE"])
def forget_device(request, device_id):
    """
    Remove the device from known devices, this does not physically delete a device
    """
    try:
        KnownAudioDevice.objects.filter(id=device_id).delete()
        return JsonResponse({}, safe=False)
    except ProtectedError as e:
        protected_objects = e.protected_objects
        references = [str(obj) for obj in protected_objects]
        device_name = KnownAudioDevice.objects.filter(id=device_id).first().name
        return JsonResponse(
            {
                'error': f'Cannot delete device "{device_name}" because it is referenced by other objects',
                'references': references
            },
            status=409
        )


@require_http_methods(["GET"])
def discover_devices(request):
    """
    Discover currently connected audio devices from all backends.
    This queries the actual hardware/system, not the database.
    """
    devices = AudioBackends.get_all_devices()

    # Convert AudioDevice objects to dictionaries for JSON serialization
    devices_data = [
        {
            'backend': device.backend.name,
            'name': device.name,
            'device_type': device.device_type.name,
            'device_format': device.device_format.name,
            'sample_rate': device.sample_rate,
            'channels': device.channels
        }
        for device in devices
    ]

    return JsonResponse(devices_data, safe=False)

def set_volume_of_device(request, device_id: int, volume: int):
    if volume < 0 or volume > 100:
        return JsonResponse({'error': 'Volume must be between 0 and 100'}, status=400)
    try:
        device = KnownAudioDevice.objects.get(id=device_id)
        if not device.active:
            return JsonResponse({'error': 'Device is not active'}, status=400)
        AudioBackends.get_backend(device.backend).set_volume(device, volume)
        return JsonResponse({}, status=204)
    except KnownAudioDevice.DoesNotExist:
        return JsonResponse({'error': f'Device with ID {device_id} does not exist'}, status=404)
    except AudioBackendException as e:
        logger.error(f'Failed to set volume for device {device_id}: {str(e)}')
        return JsonResponse({'error': 'Failed to set volume, is the device connected?'}, status=400)

def get_volume_of_device(request, device_id: int):
    try:
        device = KnownAudioDevice.objects.get(id=device_id)
        if not device.active:
            return JsonResponse({'error': 'Device is not active'}, status=400)
        return JsonResponse({'volume': AudioBackends.get_backend(device.backend).get_volume(device)})
    except KnownAudioDevice.DoesNotExist:
        return JsonResponse({'error': f'Device with ID {device_id} does not exist'}, status=404)
    except AudioBackendException as e:
        traceback.print_exception(e)
        logger.error(f'Failed to get volume for device {device_id}: {str(e)}')
        return JsonResponse({'error': 'Failed to get volume, is the device connected?'}, status=400)