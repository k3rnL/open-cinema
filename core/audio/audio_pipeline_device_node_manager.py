from typing import Any

from api.models import AudioPipelineDeviceNode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager


class AudioPipelineDeviceNodeManager(AudioPipelineNodeManager):

    def __init__(self, node):
        self.node: AudioPipelineDeviceNode = node

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        if self.node.device is None:
            return []
        elif self.node.device.device_type == 'CAPTURE':
            return [
                AudioPipelineNodeSlot(name='device',
                                      type=SlotType.DEVICE_AUDIO_INPUT,
                                      direction=SlotDirection.OUTPUT,
                                      node=self.node)
            ]
        else:
            return [
                AudioPipelineNodeSlot(name='device',
                                      type=SlotType.DEVICE_AUDIO_OUTPUT,
                                      direction=SlotDirection.INPUT,
                                      node=self.node)
            ]

    def apply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        pass

    def unapply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        pass

    def get_slot_data(self, slot_name: str) -> Any:
        if slot_name == 'device':
            return self.node.device
        return None