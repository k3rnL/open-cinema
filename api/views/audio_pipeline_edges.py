import json

from django.http import JsonResponse
from rest_framework import serializers
from rest_framework.views import APIView

from api.models.audio.pipeline.audio_pipeline_edge import AudioPipelineEdge


class EdgeDeleteRequest(serializers.Serializer):
    slot_a = serializers.IntegerField()
    slot_b = serializers.IntegerField()

class EdgeCreateRequest(EdgeDeleteRequest):
    pass

class AudioPipelineEdgeList(APIView):

    def delete(self, request, pipeline_id):
        data = json.loads(request.body)
        serializer = EdgeDeleteRequest(data=data)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        slot_a = serializer.validated_data['slot_a']
        slot_b = serializer.validated_data['slot_b']

        try:
            AudioPipelineEdge.objects.get(slot_a=slot_a, slot_b=slot_b).delete()
        except AudioPipelineEdge.DoesNotExist:
            return JsonResponse({'error': 'Edge not found'}, status=404)

        return JsonResponse({}, status=204)

    def put(self, request, pipeline_id):
        data = json.loads(request.body)
        serializer = EdgeCreateRequest(data=data)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        slot_a = serializer.validated_data['slot_a']
        slot_b = serializer.validated_data['slot_b']

        edge = AudioPipelineEdge.objects.create(slot_a_id=slot_a, slot_b_id=slot_b)
        data = {
            'id': edge.id,
            'slot_a': edge.slot_a.to_dict(),
            'slot_b': edge.slot_b.to_dict()
        }
        return JsonResponse(data, safe=False, status=201)


class AudioPipelineEdgeDetail(APIView):

    def delete(self, request, pipeline_id, edge_id):
        try:
            edge = AudioPipelineEdge.objects.get(id=edge_id)
            edge.delete()
            return JsonResponse({}, status=204)
        except AudioPipelineEdge.DoesNotExist:
            return JsonResponse({'error': 'Edge not found'}, status=404)