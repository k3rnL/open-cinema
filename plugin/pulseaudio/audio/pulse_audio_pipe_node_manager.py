from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from api.models import KnownAudioDevice
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager
from core.audio.pipeline.validation_result import ValidationResultNode
from plugin.pulseaudio.audio.backend import PulseAudioBackend
from plugin.pulseaudio.models.pulse_audio_pipe_node import PulseAudioPipeNode
from plugin.pulseaudio.models.pulse_audio_pipe_node_state import PulseAudioPipeNodeState


class PulseAudioPipeNodeManager(AudioPipelineNodeManager):

    def __init__(self, node):
        self.node: PulseAudioPipeNode = node

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        return [
            AudioPipelineNodeSlot(name="Input", type=SlotType.AUDIO_CONSUMER, direction=SlotDirection.INPUT,
                                          node=self.node),
            AudioPipelineNodeSlot(name="Output", type=SlotType.AUDIO_PRODUCER, direction=SlotDirection.OUTPUT,
                                  node=self.node)
        ]

    def apply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        previous_node = graph_node.incoming[0].from_node.data
        previous_node_slot = graph_node.incoming[0].data.incoming_slot
        previous_device: KnownAudioDevice = previous_node.get_manager().get_slot_data(previous_node_slot.name)

        next_node = graph_node.outgoing[0].to_node.data
        next_node_slot = graph_node.outgoing[0].data.outgoing_slot
        next_device: KnownAudioDevice = next_node.get_manager().get_slot_data(next_node_slot.name)

        kind = f'module-loopback'
        args = [
            f'source={previous_device.name}',
            f'sink={next_device.name}',
        ]

        module = PulseAudioBackend().add_module(kind, args)
        PulseAudioPipeNodeState.objects.create(node=self.node, module=module)

    def unapply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        try:
            self.node.pulseaudiopipenodestate
        except ObjectDoesNotExist:
            return
        PulseAudioBackend().del_module(self.node.pulseaudiopipenodestate.module)
        self.node.pulseaudiopipenodestate.delete()

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        field_errors = {}

        return ValidationResultNode(self.node.id, [], field_errors, {}) if len(field_errors) > 0 else None

    def get_slot_data(self, slot_name: str) -> Any:
        pass

