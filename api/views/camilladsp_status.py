import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.camilladsp import CamillaDSPManager

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def get_status(request):
    """Get CamillaDSP status and active pipeline information."""
    try:
        manager = CamillaDSPManager()
        status = manager.get_status()
        return JsonResponse(status)
    except Exception as e:
        logger.error(f"Error getting CamillaDSP status: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def get_config(request):
    """Get the current active CamillaDSP configuration."""
    try:
        manager = CamillaDSPManager()
        config = manager.get_current_config()

        if config is None:
            return JsonResponse(
                {'error': 'Could not retrieve current configuration'},
                status=500
            )

        return JsonResponse(config)
    except Exception as e:
        logger.error(f"Error getting CamillaDSP config: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def reload_config(request):
    """Reload the current CamillaDSP configuration."""
    try:
        manager = CamillaDSPManager()
        success, message = manager.reload_config()

        if success:
            return JsonResponse({'message': message})
        else:
            return JsonResponse({'error': message}, status=500)
    except Exception as e:
        logger.error(f"Error reloading CamillaDSP config: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
