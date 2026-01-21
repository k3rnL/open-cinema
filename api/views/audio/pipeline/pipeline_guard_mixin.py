from django.http import JsonResponse

from api.models.audio.audio_pipeline import AudioPipeline
from core.audio.pipeline.pipeline_read_only_exception import PipelineReadOnlyException


class PipelineGuardMixin:
    pipeline_kwarg = "pipeline_id"  # set per view if needed
    guard_unsafe_methods_only = True  # common: allow GET, block writes

    def get_pipeline(self):
        pipeline_id = self.kwargs.get(self.pipeline_kwarg)
        return AudioPipeline.objects.get(id=pipeline_id)

    def handle_exception(self, exception):
        if isinstance(exception, PipelineReadOnlyException):
            return JsonResponse({"error": str(exception)}, safe=False, status=409)
        raise exception

    def initial(self, request, *args, **kwargs):
        # Call super first so authentication happens (optional preference).
        super().initial(request, *args, **kwargs)

        if self.guard_unsafe_methods_only and request.method in ("GET", "HEAD", "OPTIONS"):
            return

        try:
            pipeline = self.get_pipeline()
            if pipeline and (pipeline.active or pipeline.stale):
                if pipeline.stale:
                   raise PipelineReadOnlyException(f"Pipeline {pipeline.name} is stale")
                raise PipelineReadOnlyException(f"Pipeline {pipeline.name} is active")
        except AudioPipeline.DoesNotExist:
            pass