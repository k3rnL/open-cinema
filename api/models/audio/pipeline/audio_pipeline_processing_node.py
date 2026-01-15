from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode


class AudioPipelineProcessingNode(AudioPipelineNode):
    class Meta:
        abstract = True