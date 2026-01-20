from typing import Any

from django.db.models.fields import Field
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from api.models import AudioPipelineNode
from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode
from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode
from api.views.audio.pipeline.audio_pipelines import find_model_by_name


def field_to_json(field: Field):
    if hasattr(field, 'choices') and field.choices is not None:
        choices = [{'label': choice[0], 'value': choice[1]} for choice in field.choices]
    else:
        choices = []

    return {
        'name': field.name,
        'type': field.__class__.__name__,
        'is_relation': field.is_relation,
        'help_text': field.help_text if hasattr(field, 'help_text') else None,
        'choices': choices,
        'nullable': field.null
    }

def node_type_to_json(cls: type[AudioPipelineNode]) -> dict[str, Any]:
    return {
        'type_name': cls.__name__,
        'fields': [field_to_json(f)
                   for f in cls.get_exposed_fields()
                   if '_ptr' not in f.name],
    }

@require_http_methods(['GET'])
def get_node_schematic(request, pipeline_id, node_id):
    base_node = AudioPipelineNode.objects.get(id=node_id)
    cls = find_model_by_name(base_node.type_name)
    node = cls.objects.get(id=node_id)

    return JsonResponse(node_type_to_json(node.__class__), safe=False)


@require_http_methods(['GET'])
def get_pipeline_schematics(request):
    io = []
    subclasses = [
        *AudioPipelineIONode.__subclasses__(),
        *AudioPipelineProcessingNode.__subclasses__()
    ]
    for subclass in subclasses:
        io.append(node_type_to_json(subclass))

    data = {
        'io': io
    }

    return JsonResponse(data, safe=False)
