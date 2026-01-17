import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models import AudioPipelineNode
from api.views.audio_pipelines import node_to_json, json_node_to_model, fill_model_from_json, find_model_by_name, \
    update_slots


@csrf_exempt
def nodes(request, pipeline_id):
    """Handle GET (list) and POST (create) for the pipeline's node collection."""
    if request.method == "GET":
        return list_nodes(request, pipeline_id)
    elif request.method == "POST":
        return create_node(request, pipeline_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def node(request, pipeline_id, node_id):
    """Handle GET (list) and POST (create) for the pipeline's node collection."""
    if request.method == "GET":
        return get_node(request, pipeline_id, node_id)
    elif request.method == "PATCH" or request.method == "PUT":
        return update_node(request, pipeline_id, node_id)
    elif request.method == "DELETE":
        return delete_node(request, pipeline_id, node_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def list_nodes(request, pipeline_id):
    nodes = AudioPipelineNode.objects.filter(pipeline_id=pipeline_id).all()
    data = [node_to_json(node) for node in nodes]

    return JsonResponse(data, safe=False)


@require_http_methods(["POST"])
def create_node(request, pipeline_id):
    node_json = json.loads(request.body)
    node_model = json_node_to_model(node_json)

    node_model.pipeline_id = pipeline_id
    node_model.save()
    update_slots(node_model)

    data = node_to_json(node_model)

    return JsonResponse(data, safe=False, status=201)


@require_http_methods(["GET"])
def get_node(request, pipeline_id, node_id):
    try:
        base_node = AudioPipelineNode.objects.get(id=node_id)
        cls = find_model_by_name(base_node.type_name)
        node = cls.objects.get(id=node_id)
        data = node_to_json(node)
    except AudioPipelineNode.DoesNotExist:
        return JsonResponse({'error': 'Node not found'}, status=404)

    return JsonResponse(data, safe=False)


@require_http_methods(["PATCH", "PUT"])
def update_node(request, pipeline_id, node_id):
    node_json = json.loads(request.body)
    cls = find_model_by_name(node_json['type_name'])
    node_model = cls.objects.get(id=node_id)

    fill_model_from_json(node_model, node_json)

    node_model.save()
    update_slots(node_model)

    data = node_to_json(node_model)

    return JsonResponse(data, safe=False, status=200)


@require_http_methods(["DELETE"])
def delete_node(request, pipeline_id, node_id):
    try:
        node = AudioPipelineNode.objects.get(id=node_id)
    except AudioPipelineNode.DoesNotExist:
        return JsonResponse({'error': 'Node not found'}, status=404)

    node.delete()
    return JsonResponse({}, status=204)
