import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from api.models.preferences_audio_backend import PreferencesAudioBackend
from core.audio.audio_backends import AudioBackends


@require_http_methods(["GET"])
def get_audio_backends_preferences(request):
    all_backends = AudioBackends.get_all()
    preferences = {b.name: b for b in PreferencesAudioBackend.objects.all()}

    data = [
        {
            'name': b.name,
            'enabled': preferences[b.name].enabled if b.name in preferences else False,
        } for b in all_backends
    ]

    return JsonResponse(data, safe=False)

@require_http_methods(["PUT", "PATCH"])
def update_audio_backend_preference(request, backend_name):
    preferences, _ = PreferencesAudioBackend.objects.get_or_create(name=backend_name, defaults={'enabled': False})
    data = json.loads(request.body)

    preferences.enabled = data['enabled']
    preferences.save()

    return JsonResponse(data)