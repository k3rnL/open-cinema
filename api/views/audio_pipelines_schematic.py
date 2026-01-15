from django.db.models.fields import Field
from django.http import JsonResponse

from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode
from api.models.audio.pipeline.audio_pipeline_processing_node import AudioPipelineProcessingNode


def field_to_json(field: Field):
    if hasattr(field, 'choices') and field.choices is not None:
        choices = [{'label': choice[0], 'value': choice[1]} for choice in field.choices]
    else:
        choices = []

    return {
        'name': field.name,
        'type': field.__class__.__name__,
        'help_text': field.help_text if hasattr(field, 'help_text') else None,
        'choices': choices,
        'nullable': field.null
    }


def get_pipeline_schematics(request):
    io = []
    subclasses = [
        *AudioPipelineIONode.__subclasses__(),
        *AudioPipelineProcessingNode.__subclasses__()
    ]
    for subclass in subclasses:
        model_name = subclass.__name__
        io.append({
            'name': model_name,
            'fields': [field_to_json(f)
                       for f in subclass._meta.get_fields(include_parents=False)
                       if '_ptr' not in f.name],
            'slots': [slot.to_dict() for slot in subclass.static_slots]
        })

    data = {
        'io': io
    }

    print('Pipeline schematics generated successfully', data)
    return JsonResponse(data, safe=False)
