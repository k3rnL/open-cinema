import json
from typing import Any

from django.db import models
from django.http import JsonResponse
from rest_framework import serializers
from rest_framework.views import APIView

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_edge import AudioPipelineEdge
from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot
from api.views.audio_pipeline_nodes import NodeSerializer, node_to_json, get_concrete_node, update_slots, \
    json_node_to_model, find_model_by_name, fill_model_from_json


# Serializers
class SlotSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=255)
    node = serializers.IntegerField(required=True)


class EdgeSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, read_only=True)
    slot_a = SlotSerializer(required=True)
    slot_b = SlotSerializer(required=True)


class PipelineSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, read_only=True)
    name = serializers.CharField(required=True, max_length=255)
    nodes = NodeSerializer(many=True, required=False, default=list)
    edges = EdgeSerializer(many=True, required=False, default=list)
    active = serializers.BooleanField(required=False)


class AudioPipelineList(APIView):
    """Handle GET (list) and POST (create) for pipelines collection."""

    def get(self, request):
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

    def post(self, request):
        data = json.loads(request.body)

        serializer = PipelineSerializer(data=data)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        validated = serializer.validated_data

        pipeline = AudioPipeline()
        pipeline.name = validated['name']
        pipeline.save()

        nodes = []
        for data_node in validated.get('nodes', []):
            try:
                node = json_node_to_model(data_node)
                node.pipeline = pipeline
                node.save()
                nodes.append(node)
                update_slots(node)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=400)

        update_edges(nodes, validated.get('edges', []))

        return_data = pipeline_to_json(pipeline)

        return JsonResponse(return_data, safe=False)


def pipeline_to_json(pipeline: AudioPipeline) -> dict[str, Any]:
    nodes = pipeline.audiopipelinenode_set.all()
    node_ids = [n.id for n in nodes]
    edges = AudioPipelineEdge.objects.filter(slot_a__node_id__in=node_ids,
                                             slot_b__node_id__in=node_ids).distinct().all()

    # Get concrete subclass instances
    concrete_nodes = [get_concrete_node(node) for node in nodes]

    return {
        'id': pipeline.id,
        'name': pipeline.name,
        'created_at': pipeline.created_at,
        'updated_at': pipeline.updated_at,
        'active': pipeline.active,
        'stale': pipeline.stale,
        'nodes': [node_to_json(node) for node in concrete_nodes],
        'edges': [
            {
                'id': edge.id,
                'slot_a': edge.slot_a.to_dict(),
                'slot_b': edge.slot_b.to_dict(),
            }
            for edge in edges
        ]
    }


def update_edges(nodes: list[AudioPipelineNode], edges) -> None:
    node_ids = [node.id for node in nodes]
    for data_edge in edges:
        slot_a_data = data_edge['slot_a']
        slot_b_data = data_edge['slot_b']
        slot_a = AudioPipelineNodeSlot.objects.filter(name=slot_a_data['name'], node_id=slot_a_data['node']).first()
        slot_b = AudioPipelineNodeSlot.objects.filter(name=slot_b_data['name'], node_id=slot_b_data['node']).first()
        if slot_a is None or slot_b is None:
            raise Exception(f'Slots not found for edge: {data_edge}')
        existing_edge = AudioPipelineEdge.objects.filter(slot_a=slot_a, slot_b=slot_b).first()
        if existing_edge is not None:
            continue
        edge = AudioPipelineEdge()

        edge.slot_a = slot_a
        edge.slot_b = slot_b
        edge.save()

    for edge in AudioPipelineEdge.objects.filter(slot_a__node__in=node_ids, slot_b__node__in=node_ids).distinct():
        # look for edges that are not in the data anymore and delete them
        found = False
        for data_edge in edges:
            slot_a_data = data_edge['slot_a']
            slot_b_data = data_edge['slot_b']
            if (slot_a_data['name'] == edge.slot_a.name and slot_b_data['name'] == edge.slot_b.name
                    or slot_b_data['name'] == edge.slot_a.name and slot_a_data['name'] == edge.slot_b.name):
                found = True
                break
        if not found:
            edge.delete()


class AudioPipelineDetail(APIView):
    """Handle GET, PATCH for pipeline item."""

    def delete(self, request, pipeline_id):
        pipeline = AudioPipeline.objects.get(id=pipeline_id)
        pipeline.delete()
        return JsonResponse({}, status=204)

    def get(self, request, pipeline_id):
        pipeline = AudioPipeline.objects.get(id=pipeline_id)
        return JsonResponse(pipeline_to_json(pipeline), safe=False)

    def patch(self, request, pipeline_id):
        data = json.loads(request.body)
        serializer = PipelineSerializer(data=data, partial=True)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        validated = serializer.validated_data

        pipeline = AudioPipeline.objects.get(id=pipeline_id)
        if 'name' in validated:
            pipeline.name = validated['name']

        nodes: list[AudioPipelineNode] = []
        for data_node in validated.get('nodes', []):
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

                update_slots(node)
            except ReferenceError as e:
                print(e)
                return JsonResponse({'error': str(e)}, status=400)
            except models.ObjectDoesNotExist as e:
                return JsonResponse(
                    {'error': f"Could not update node of type {data_node['type_name']}, id {data_node['id']} not found"},
                    status=400)
            except Exception as e:
                return JsonResponse({'error': f'{e.__class__.__name__}: {e}'}, status=500)

        # remove unused edges and apply those from data
        update_edges(nodes, validated.get('edges', []))

        return JsonResponse(pipeline_to_json(pipeline), safe=False)

