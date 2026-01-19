from django.db.models.fields import Field
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.views.audio_pipelines import find_model_by_name


@csrf_exempt
def node_relations(request, type_name, field_name):
    """Handle GET (list) and POST (create) for the pipeline's node collection."""
    if request.method == "GET":
        return list_relations(request, type_name, field_name)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def list_relations(request, type_name: str, field_name: str):
    cls = find_model_by_name(type_name)

    field: Field = None
    for f in cls._meta.local_fields:
        if f.name == field_name:
            field = f
            break

    values = [model_to_dict(m) for m in field.remote_field.model.objects.all()]
    return JsonResponse(data=values, safe=False)