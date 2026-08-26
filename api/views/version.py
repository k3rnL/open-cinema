from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from opencinema.version import MAJOR, MINOR, PATCH, __version__


@require_http_methods(["GET"])
def get_version(request):
    """Get API version information."""
    return JsonResponse({
        'version': __version__,
        'major': MAJOR,
        'minor': MINOR,
        'patch': PATCH,
        'api': 'v1'
    })
