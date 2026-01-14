from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode


class AudioPipelineIONode(AudioPipelineNode):
    class Meta:
        abstract = True