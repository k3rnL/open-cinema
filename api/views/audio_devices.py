from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models.deletion import ProtectedError

from api.models import KnownAudioDevice
from core.audio.audio_backends import AudioBackends


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

    # Convert to JSON
    devices_data = [
        {
            'id': device.id,
            'backend': device.backend,
            'name': device.name,
            'device_type': device.device_type,
            'format': device.format,
            'sample_rate': device.sample_rate,
            'channels': device.channels,
            'active': device.active,
            'last_seen': device.last_seen.isoformat()
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