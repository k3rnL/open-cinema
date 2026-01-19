from django.http import JsonResponse

from api.models.audio.audio_pipeline import AudioPipeline
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraph


def validate_audio_pipeline(request, pipeline_id):
    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    pipeline_graph = AudioPipelineGraph(pipeline)

    validation = pipeline_graph.validate()

    data = {
        'valid': validation.valid(),
        'errors': validation.graph_errors,
        'edges': [
            {
                'id': edge.edge,
                'valid': edge.valid(),
                'errors': edge.errors,
            } for edge in validation.edges],
        'nodes': [
            {
                'id': node.node,
                'errors': node.errors,
                'fields': node.fields,
                'slots': node.slots,
                'valid': node.valid()
            } for node in validation.nodes
        ]
    }

    return JsonResponse(data, status=200)
