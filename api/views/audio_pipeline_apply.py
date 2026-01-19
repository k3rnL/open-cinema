from django.forms.models import model_to_dict
from django.http import JsonResponse
from rest_framework.views import APIView

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_apply_event import AudioPipelineApplyEvent, EventType
from api.models.audio.pipeline.audio_pipeline_apply_job import AudioPipelineApplyJob
from api.tasks.audio_pipeline_job import apply_audio_pipeline, unapply_audio_pipeline
from api.views.audio_pipeline_events import job_to_json
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraph


class AudioPipelineApplyView(APIView):

    def post(self, request, pipeline_id):
        pipeline = AudioPipeline.objects.get(id=pipeline_id)

        job = AudioPipelineApplyJob.objects.create(pipeline=pipeline)
        AudioPipelineApplyEvent.objects.create(job=job, event_type=EventType.START)

        apply_audio_pipeline.delay(pipeline_id, job.id)

        return JsonResponse(data=job_to_json(job), status=200)

    def delete(self, request, pipeline_id):
        pipeline = AudioPipeline.objects.get(id=pipeline_id)

        job = AudioPipelineApplyJob.objects.create(pipeline=pipeline)
        AudioPipelineApplyEvent.objects.create(job=job, event_type=EventType.START)

        unapply_audio_pipeline.delay(pipeline_id, job.id)

        return JsonResponse(data=job_to_json(job), status=200)