from django.http import JsonResponse
from rest_framework.views import APIView

from api.models.audio.audio_pipeline import AudioPipeline
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

class AudioPipelineJobList(APIView):

    def get(self, request, pipeline_id):
        try:
            pipeline = AudioPipeline.objects.get(id=pipeline_id)
            jobs = [job_to_json(job) for job in pipeline.audiopipelineapplyjob_set.all()]
            return JsonResponse(data=jobs, safe=False)
        except AudioPipeline.DoesNotExist:
            return JsonResponse({'error': 'Pipeline not found'}, status=404)


class AudioPipelineJobDetail(APIView):

    def get(self, request, pipeline_id, job_id):
        try:
            job = AudioPipelineApplyJob.objects.get(id=job_id)
            return JsonResponse(data=job_to_json(job), safe=False)
        except AudioPipelineApplyJob.DoesNotExist:
            return JsonResponse({'error': 'Job not found'}, status=404)

    def delete(self, request, pipeline_id, job_id):
        try:
            job = AudioPipelineApplyJob.objects.get(id=job_id)
            job.delete()
            return JsonResponse({}, status=204)
        except AudioPipelineApplyJob.DoesNotExist:
            return JsonResponse({'error': 'Job not found'}, status=404)