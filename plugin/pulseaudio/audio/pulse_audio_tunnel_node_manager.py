from django.core.exceptions import ObjectDoesNotExist

from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType, SlotDirection
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraphNode, AudioPipelineGraph
from core.audio.pipeline.audio_pipeline_node_manager import AudioPipelineNodeManager
from core.audio.pipeline.validation_result import ValidationResultNode
from plugin.pulseaudio.audio.backend import PulseAudioBackend
from plugin.pulseaudio.models.pulse_audio_tunnel_node import PulseAudioTunnelNode
from plugin.pulseaudio.models.pulse_audio_tunnel_node_state import PulseAudioTunnelNodeState


class PulseAudioTunnelNodeManager(AudioPipelineNodeManager):

    def __init__(self, node):
        self.node: PulseAudioTunnelNode = node

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        if self.node.mode == 'SOURCE' or self.node.mode == 'source':
            name = self.node.source if self.node.source is not None else 'Source Name'
            return [AudioPipelineNodeSlot(name=name, type=SlotType.DEVICE_AUDIO_INPUT, direction=SlotDirection.OUTPUT, node=self.node)]
        elif self.node.mode == 'SINK' or self.node.mode == 'sink':
            name = self.node.sink if self.node.sink is not None else 'Sink Name'
            return [AudioPipelineNodeSlot(name=name, type=SlotType.DEVICE_AUDIO_OUTPUT, direction=SlotDirection.INPUT, node=self.node)]
        return []

    def apply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        kind = f'module-tunnel-{self.node.mode.lower()}'
        args = [f'server={self.node.server}']
        if self.node.source is not None and self.node.source != '': args.append(f'source={self.node.source}')
        if self.node.sink is not None and self.node.sink != '': args.append(f'sink={self.node.sink}')
        if self.node.cookie is not None and self.node.cookie != '': args.append(f'cookie={self.node.cookie}')

        module = PulseAudioBackend().add_module(kind, args)
        PulseAudioTunnelNodeState.objects.create(node=self.node, module=module)

    def unapply(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph):
        try:
            self.node.pulseaudiotunnelnodestate
        except ObjectDoesNotExist:
            return
        PulseAudioBackend().del_module(self.node.pulseaudiotunnelnodestate.module)
        self.node.pulseaudiotunnelnodestate.delete()

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        field_errors = {}

        if self.node.server is None or self.node.server == '':
            field_errors['server'] = 'Server must be specified'
        if self.node.mode is None or self.node.mode == '':
            field_errors['mode'] = 'Mode must be specified'
        if self.node.mode == 'SOURCE' or self.node.mode == 'source' and self.node.source is None:
            field_errors['source'] = 'Source must be specified when mode is source'
        if self.node.mode == 'SINK' or self.node.mode == 'sink' and self.node.sink is None:
            field_errors['sink'] = 'Sink must be specified when mode is sink'

        return ValidationResultNode(self.node.id, [], field_errors, {}) if len(field_errors) > 0 else None