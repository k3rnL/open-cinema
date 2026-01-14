from django.db.models.fields import Field
from django.http import JsonResponse

from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode


def field_to_json(field: Field):
    return {
        'name': field.name,
        'type': field.__class__.__name__,
        'help_text': field.help_text if hasattr(field, 'help_text') else None,
        'choices': field.choices if hasattr(field, 'choices') else None,
        'nullable': field.null
    }


def get_pipeline_schematics(request):
    io = []
    for subclass in AudioPipelineIONode.__subclasses__():
        model_name = subclass.__name__
        io.append({
            'name': model_name,
            'fields': [field_to_json(f)
                       for f in subclass._meta.get_fields(include_parents=False)
                       if '_ptr' not in f.name]
        })

    data = {
        'io': io
    }

    print('Pipeline schematics generated successfully', data)
    return JsonResponse(data, safe=False)
