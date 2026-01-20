import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.tasks.audio_device_discovery import discover_and_update_audio_devices

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def trigger_discovery(request):
    """
    Manually trigger audio device discovery and update the KnownAudioDevice table.
    This will discover all connected devices and mark inactive ones.
    """
    try:
        logger.info("Manual device discovery triggered via API")
        discover_and_update_audio_devices()

        from api.models import KnownAudioDevice

        # Get counts for response
        total_devices = KnownAudioDevice.objects.count()
        active_devices = KnownAudioDevice.objects.filter(active=True).count()
        inactive_devices = total_devices - active_devices

        return JsonResponse({
            'message': 'Device discovery completed successfully',
            'total_devices': total_devices,
            'active_devices': active_devices,
            'inactive_devices': inactive_devices
        })
    except Exception as e:
        logger.error(f"Error during manual device discovery: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
