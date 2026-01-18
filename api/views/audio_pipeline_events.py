from django.http import JsonResponse
from rest_framework.views import APIView

from api.models.audio.pipeline.audio_pipeline_apply_event import AudioPipelineApplyEvent
from api.models.audio.pipeline.audio_pipeline_apply_job import AudioPipelineApplyJob

def job_to_json(job: AudioPipelineApplyJob):
    return {
            'id': job.id,
            'status': job.status,
            'created_at': job.created_at,
            'events': [
                {
                    'id': event.id,
                    'event_type': event.event_type,
                    'created_at': event.created_at,
                    'node': event.node.id if event.node else None,
                    'data': event.data
                }
                for event in job.audiopipelineapplyevent_set.all()]
        }

class AudioPipelineApplyEventList(APIView):

    def get(self, request, pipeline_id, job_id):
        job = AudioPipelineApplyJob.objects.get(id=job_id)

        return JsonResponse(job_to_json(job), safe=False)
