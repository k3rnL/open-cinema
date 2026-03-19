import os
import signal
import subprocess
from typing import Any

from api.models import KnownAudioDevice
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager
from core.audio.pipeline.validation_result import ValidationResultNode
from plugin.pcmautodecoder.models.auto_decoder_node_state import AutoDecoderNodeState


class AutoDecoderNodeManager(AudioPipelineNodeManager):

    def __init__(self, node):
        from plugin.pcmautodecoder.models.auto_decoder_node import AutoDecoderNode
        self.node: AutoDecoderNode = node

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        return [
            AudioPipelineNodeSlot(name="Input", type=SlotType.AUDIO_CONSUMER, direction=SlotDirection.INPUT, node=self),
            AudioPipelineNodeSlot(name="PCM Output", type=SlotType.AUDIO_PRODUCER, direction=SlotDirection.OUTPUT, node=self),
            AudioPipelineNodeSlot(name="Decoded output", type=SlotType.AUDIO_PRODUCER, direction=SlotDirection.OUTPUT, node=self),
        ]

    def apply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        previous_node = graph_node.incoming[0].from_node.data
        previous_node_slot = graph_node.incoming[0].data.incoming_slot
        previous_device: KnownAudioDevice = previous_node.get_manager().get_slot_data(previous_node_slot.name)

        next_node = graph_node.outgoing[0].to_node.data
        next_node_slot = graph_node.outgoing[0].data.outgoing_slot
        next_device: KnownAudioDevice = next_node.get_manager().get_slot_data(next_node_slot.name)

        args = [
            '--source', previous_device.name,
            '--sink', next_device.name
        ]
        process = subprocess.Popen(['pcm-auto-decoder'] + args)
        AutoDecoderNodeState(node=self.node, pid=process.pid).save()

    def unapply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        try:
            state = self.node.autodecodernodestate
        except AutoDecoderNodeState.DoesNotExist:
            return
        try:
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        state.delete()

    def get_slot_data(self, slot_name: str) -> Any:
        pass

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        previous_node = graph_node.incoming[0].from_node.data
        previous_node_slot = graph_node.incoming[0].data.incoming_slot
        previous_device: KnownAudioDevice = previous_node.get_manager().get_slot_data(previous_node_slot.name)

        if previous_device.backend != 'pulseaudio':
            return ValidationResultNode(
                node=self.node.id,
                slots= {
                    "Input": "Invalid device type. Only PulseAudio devices are supported."
                },
                fields={},
                errors=[],
            )

        return None



