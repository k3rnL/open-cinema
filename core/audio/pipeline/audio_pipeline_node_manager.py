from abc import ABC, abstractmethod

from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraph, AudioPipelineGraphNode
from core.audio.pipeline.validation_result import ValidationResultNode


class AudioPipelineNodeManager(ABC):

    def get_dynamic_slots_schematics(self) -> list[AudioPipelineNodeSlot]:
        """
        Compute the slots for this node dynamically. The function must be idempotent.
        Meaning that it must return the same result when it is called if the state of the node does not change.
        :return:
        """
        return []

    @abstractmethod
    def apply(self):
        """
        Must be implemented by subclasses.
        This function is never called twice on the same resource. Except if the resource is unapplied first.
        """
        pass

    @abstractmethod
    def unapply(self):
        """
        Must be implemented by subclasses.
        The call to this function must not raise an error if the resource is already unapplied.
        But it can raise an error for any other reason.
        It can be called multiple times even if the resource is already unapplied.
        """
        pass

    def validate(self, graph_node: AudioPipelineGraphNode, graph: AudioPipelineGraph) -> ValidationResultNode | None:
        """
        Validates the node's configuration within the given graph.

        :param graph_node: The graph node representation of this pipeline node.
        :param graph: The audio pipeline graph containing this node.
        :return: A validation result node if the node is invalid, otherwise None.
        """
        return None