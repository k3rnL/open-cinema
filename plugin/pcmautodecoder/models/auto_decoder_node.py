from api.models.audio.pipeline.audio_pipeline_io_node import AudioPipelineIONode


class AutoDecoderNode(AudioPipelineIONode):

    class Meta:
        app_label = 'api'

    def get_manager(self) -> 'AudioPipelineNodeManager':
        from plugin.pcmautodecoder.audio.auto_decoder_node_manager import AutoDecoderNodeManager
        return AutoDecoderNodeManager(self)
