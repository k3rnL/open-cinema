from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist

from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager
from core.audio.pipeline.validation_result import ValidationResultNode
from core.camilladsp import CamillaDSPAudioPipelineNode


class CamillaDSPAudioPipelineNodeManager(AudioPipelineNodeManager):

    def __init__(self, node: CamillaDSPAudioPipelineNode):
        self.node = node

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        if self.node.camilladsp_pipeline is None:
            return []

        input_device = self.node.camilladsp_pipeline.input_device
        output_device = self.node.camilladsp_pipeline.output_device
        return [
            AudioPipelineNodeSlot(name=input_device.name, type=SlotType.AUDIO_CONSUMER, direction=SlotDirection.INPUT,
                                  node=self.node),
            AudioPipelineNodeSlot(name=output_device.name, type=SlotType.AUDIO_PRODUCER, direction=SlotDirection.OUTPUT,
                                  node=self.node)
        ]

    def apply(self):
        pass

    def unapply(self):
        pass

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        field_errors = {}
        try:
            self.node.camilladsp_pipeline
        except ObjectDoesNotExist:
            field_errors['camilladsp_pipeline'] = 'CamillaDSP Pipeline not set'

        return ValidationResultNode(self.node.id, [], field_errors, {})