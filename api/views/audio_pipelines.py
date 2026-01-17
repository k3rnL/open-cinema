import json
from typing import Any

from django.apps import apps
from django.db import models
from django.db.models import Model
from django.db.models.fields import Field
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_edge import AudioPipelineEdge
from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode


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


def node_to_json(node: AudioPipelineNode) -> dict[str, Any]:
    return {
        'id': node.id,
        'type_name': node.__class__.__name__,
        'dynamic_slots_schematics': [slot.to_dict() for slot in node.get_dynamic_slots_schematics()],
        'fields': get_fields_value(node, node._meta.local_fields)
    }


def pipeline_to_json(pipeline: AudioPipeline) -> dict[str, Any]:
    nodes = pipeline.audiopipelinenode_set.all()
    node_ids = [n.id for n in nodes]
    edges = AudioPipelineEdge.objects.filter(node_a__in=node_ids, node_b__in=node_ids).distinct().all()

    # Get concrete subclass instances
    concrete_nodes = [get_concrete_node(node) for node in nodes]

    return {
        'id': pipeline.id,
        'name': pipeline.name,
        'created_at': pipeline.created_at,
        'updated_at': pipeline.updated_at,
        'active': pipeline.active,
        'nodes': [node_to_json(node) for node in concrete_nodes],
        'edges': [
            {
                'id': edge.id,
                'node_a': edge.node_a.id,
                'node_b': edge.node_b.id,
            }
            for edge in edges
        ]
    }


def recursive_subclasses[T](cls: type[T]) -> set[type[T]]:
    """
    Recursively finds all subclasses of a given class.
    """
    return set.union({cls}, *map(recursive_subclasses, cls.__subclasses__()))


def find_model_by_name(name: str) -> type[AudioPipelineNode] | None:
    for model in apps.get_models():
        if model.__name__ == name:
            return model
    return None

def fill_model_from_json(node: AudioPipelineNode, data: dict[str, Any]) -> None:
    fields = node._meta.local_fields
    for field in fields:
        if '_ptr' in field.name:
            continue
        if field.name in data['fields']:
            if field.is_relation:
                try:
                    relation_instance = field.remote_field.model.objects.get(id=data['fields'][field.name])
                    setattr(node, field.name, relation_instance)
                except field.remote_field.model.DoesNotExist:
                    raise ReferenceError(
                        f'Relation {field.name} with ID {data["fields"][field.name]} does not exist')
            else:
                setattr(node, field.name, data['fields'][field.name])

def json_node_to_model(data_node) -> AudioPipelineNode:
    class_name = data_node['type_name']

    # Search through all registered models to find the matching class
    cls = find_model_by_name(class_name)

    if cls is None:
        raise ReferenceError(f'Class {class_name} not found in registered Django models')

    node = cls()
    node.type_name = class_name
    fill_model_from_json(node, data_node)

    return node


@require_http_methods(['POST'])
def create_pipeline(request):
    data = json.loads(request.body)

    pipeline = AudioPipeline()
    pipeline.name = data['name']
    pipeline.save()

    nodes = []
    for data_node in data['nodes']:
        try:
            node = json_node_to_model(data_node)
            node.pipeline = pipeline
            node.save()
            nodes.append(node)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    edges = []
    for data_edge in data['edges']:
        edge = AudioPipelineEdge()
        edge.node_a = nodes[data_edge['node_a']]
        edge.node_b = nodes[data_edge['node_b']]
        edge.save()
        edges.append(edge)

    return_data = pipeline_to_json(pipeline)

    return JsonResponse(return_data, safe=False)


def pipeline(request, pipeline_id):
    """Handle GET (list) and POST (create) for pipeline item."""
    if request.method == "GET":
        return get_pipeline(request, pipeline_id)
    elif request.method == "PATCH":
        return update_pipeline(request, pipeline_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


def get_fields_value(node: AudioPipelineNode, fields: list[Field]) -> dict[str, Any]:
    result = {}

    for field in fields:
        if '_ptr' in field.name:
            continue
        if field.is_relation:
            value = getattr(node, field.name)
            if value is not None:
                result[field.name] = getattr(value, field.remote_field.field_name)
        else:
            result[field.name] = getattr(node, field.name)

    return result


def get_concrete_node(node: AudioPipelineNode) -> AudioPipelineNode:
    """Get the concrete subclass instance from a base AudioPipelineNode."""
    # Find all subclass names by checking for related objects
    for subclass in recursive_subclasses(AudioPipelineNode):
        if subclass == AudioPipelineNode:
            continue
        # Get the related name (lowercase class name + '_ptr')
        related_name = subclass.__name__.lower()
        if hasattr(node, related_name):
            return getattr(node, related_name)
    return node


@require_http_methods(['GET'])
def get_pipeline(request, pipeline_id):
    pipeline = AudioPipeline.objects.get(id=pipeline_id)

    return JsonResponse(pipeline_to_json(pipeline), safe=False)


@require_http_methods(['PATCH'])
def update_pipeline(request, pipeline_id):
    data = json.loads(request.body)

    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    if 'name' in data:
        pipeline.name = data['name']

    nodes: list[AudioPipelineNode] = []
    for data_node in data['nodes']:
        try:
            if 'id' in data_node and data_node['id'] >= 0:
                # update existing node
                node_id = data_node['id']
                cls = find_model_by_name(data_node['type_name'])
                node = cls.objects.get(id=node_id)

                fill_model_from_json(node, data_node)
                node.save()
                nodes.append(node)
            else:
                # create node
                node = json_node_to_model(data_node)
                node.pipeline = pipeline
                node.save()
                nodes.append(node)
        except ReferenceError as e:
            print(e)
            return JsonResponse({'error': str(e)}, status=400)
        except models.ObjectDoesNotExist as e:
            return JsonResponse({'error': f"Could not update node of type {data_node['type_name']}, id {data_node['id']} not found"}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'{e.__class__.__name__}: {e}'}, status=500)

    # reset all edges and apply those from data
    node_ids = [node.id for node in nodes]
    AudioPipelineEdge.objects.filter(node_a_id__in=node_ids, node_b_id__in=node_ids).delete()
    edges = []
    for data_edge in data['edges']:
        edge = AudioPipelineEdge()
        edge.node_a_id = data_edge['node_a']
        edge.node_b_id = data_edge['node_b']
        edge.save()
        edges.append(edge)

    return JsonResponse(pipeline_to_json(pipeline), safe=False)
