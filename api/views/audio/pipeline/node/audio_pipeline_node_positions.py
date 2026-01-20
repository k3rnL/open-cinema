import json

from django.http import JsonResponse
from rest_framework.views import APIView

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_node_position import AudioPipelineNodePosition


class AudioPipelineNodePositionList(APIView):

    def get(self, request, pipeline_id):
        pipeline = AudioPipeline.objects.get(id=pipeline_id)
        positions = AudioPipelineNodePosition.objects.filter(node__pipeline=pipeline).all()

        data = [
            {
                'node_id': position.node.id,
                'x': position.x,
                'y': position.y
            } for position in positions
        ]

        return JsonResponse(data, safe=False, status=200)

    def put(self, request, pipeline_id):
        data = json.loads(request.body)

        for position in data:
            AudioPipelineNodePosition.objects.update_or_create(
                node_id=position["node_id"],
                defaults={
                    "x": position["x"],
                    "y": position["y"],
                },
            )

        return JsonResponse({}, status=204)