import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models.audio_pipeline import AudioPipeline
from api.models.audio_pipeline_edge import AudioPipelineEdge
from api.models.audio_pipeline_node import AudioPipelineNode


@csrf_exempt
def pipelines(request):
    """Handle GET (list) and POST (create) for pipelines collection."""
    if request.method == "GET":
        return list_pipelines(request)
    elif request.method == "POST":
        return create_pipeline(request)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(['GET'])
def list_pipelines(request):
    pipelines = AudioPipeline.objects.all()

    data = [
        {
            'id': pipeline.id,
            'name': pipeline.name,
            'created_at': pipeline.created_at,
            'updated_at': pipeline.updated_at,
            'active': pipeline.active,
        } for pipeline in pipelines
    ]

    return JsonResponse(data, safe=False)


@require_http_methods(['POST'])
def create_pipeline(request):
    data = json.loads(request.body)

    pipeline = AudioPipeline()
    pipeline.name = data['name']
    pipeline.save()

    nodes = []
    for data_node in data['nodes']:
        node = AudioPipelineNode()
        node.pipeline = pipeline
        node.kind = data_node['kind']
        node.plugin = data_node['plugin']
        node.parameters = data_node['parameters']
        node.save()
        nodes.append(node)

    edges = []
    for data_edge in data['edges']:
        edge = AudioPipelineEdge()
        edge.node_a = nodes[data_edge['node_a']]
        edge.node_b = nodes[data_edge['node_b']]
        edge.save()
        edges.append(edge)

    return_data = {
        'name': pipeline.name,
        'nodes': [
            {
                'id': node.id,
                'kind': node.kind,
                'plugin': node.plugin,
                'parameters': node.parameters,
            }
            for node in nodes
        ],
        'edges': [
            {
                'id': edge.id,
                'node_a': edge.node_a.id,
                'node_b': edge.node_b.id,
            }
            for edge in edges
        ]
    }

    return JsonResponse(return_data, safe=False)


def pipeline(request, pipeline_id):
    """Handle GET (list) and POST (create) for pipeline item."""
    if request.method == "GET":
        return get_pipeline(request, pipeline_id)
    elif request.method == "PATCH":
        return update_pipeline(request, pipeline_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(['GET'])
def get_pipeline(request, pipeline_id):
    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    nodes = pipeline.audiopipelinenode_set.all()
    node_ids = [n.id for n in nodes]
    edges = AudioPipelineEdge.objects.filter(node_a__in=node_ids, node_b__in=node_ids).distinct().all()

    data = {
        'id': pipeline.id,
        'name': pipeline.name,
        'created_at': pipeline.created_at,
        'updated_at': pipeline.updated_at,
        'active': pipeline.active,
        'nodes': [
            {
                'id': node.id,
                'kind': node.kind,
                'plugin': node.plugin,
                'parameters': node.parameters,
            }
            for node in nodes
        ],
        'edges': [
            {
                'id': edge.id,
                'node_a': edge.node_a.id,
                'node_b': edge.node_b.id,
            }
            for edge in edges
        ]
    }

    return JsonResponse(data, safe=False)


@require_http_methods(['PATCH'])
def update_pipeline(request, pipeline_id):
    data = json.loads(request.body)

    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    if 'name' in data:
        pipeline.name = data['name']

    AudioPipelineNode.objects.filter(pipeline=pipeline).delete()
    nodes = []
    for data_node in data['nodes']:
        node = AudioPipelineNode()
        node.pipeline = pipeline
        node.kind = data_node['kind']
        node.plugin = data_node['plugin']
        node.parameters = data_node['parameters']
        node.save()
        nodes.append(node)

    edges = []
    for data_edge in data['edges']:
        edge = AudioPipelineEdge()
        edge.node_a = nodes[data_edge['node_a']]
        edge.node_b = nodes[data_edge['node_b']]
        edge.save()
        edges.append(edge)

    return_data = {
        'name': pipeline.name,
        'nodes': [
            {
                'id': node.id,
                'kind': node.kind,
                'plugin': node.plugin,
                'parameters': node.parameters,
            }
            for node in nodes
        ],
        'edges': [
            {
                'id': edge.id,
                'node_a': edge.node_a.id,
                'node_b': edge.node_b.id,
            }
            for edge in edges
        ]
    }

    return JsonResponse(return_data, safe=False)
