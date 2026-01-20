from typing import NamedTuple, TYPE_CHECKING

from api.models.audio.pipeline.audio_pipeline_edge import AudioPipelineEdge
from core.audio.pipeline.validation_result import ValidationResult, ValidationResultNode, ValidationResultEdge
from core.utils.graph import GraphEdge, Graph, GraphNode
from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot, SlotType

if TYPE_CHECKING:
    from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode
    from api.models.audio.audio_pipeline import AudioPipeline


class EdgeSlots(NamedTuple):
    id: int
    data: AudioPipelineEdge
    incoming_node: 'AudioPipelineNode'
    outgoing_node: 'AudioPipelineNode'
    incoming_slot: 'AudioPipelineNodeSlot'
    outgoing_slot: 'AudioPipelineNodeSlot'


type AudioPipelineGraphEdge = GraphEdge['AudioPipelineNode', EdgeSlots]
type AudioPipelineGraphNode = GraphNode['AudioPipelineNode', EdgeSlots]


class AudioPipelineGraph(Graph['AudioPipelineNode', EdgeSlots]):

    def __init__(self, pipeline: 'AudioPipeline'):
        from api.views.audio.pipeline.audio_pipelines import find_model_by_name

        # Create graph nodes from pipeline nodes
        node_map = {}  # Map AudioPipelineNode.id -> GraphNode
        for db_node in pipeline.audiopipelinenode_set.all():
            # We must find the real node type for validation functions to be called
            cls = find_model_by_name(db_node.type_name)
            real_node = cls.objects.get(id=db_node.id)
            graph_node: AudioPipelineGraphNode = GraphNode(data=real_node)
            node_map[db_node.id] = graph_node

        # Create graph edges from slot connections
        graph_edges = []
        seen_edges = set()

        for db_node in pipeline.audiopipelinenode_set.all():
            for slot in db_node.slots.all():
                # Process outgoing edges from this slot
                for db_edge in slot.outgoing_edges.all():
                    if db_edge.id not in seen_edges:
                        seen_edges.add(db_edge.id)

                        from_node = node_map[db_edge.slot_a.node_id]
                        to_node = node_map[db_edge.slot_b.node_id]
                        from_slot = db_edge.slot_a
                        to_slot = db_edge.slot_b

                        graph_edge = GraphEdge['AudioPipelineNode', EdgeSlots](
                            data=EdgeSlots(db_edge.id, db_edge, from_node, to_node, from_slot, to_slot),
                            from_node=from_node,
                            to_node=to_node
                        )
                        graph_edges.append(graph_edge)

        # Build the graph
        super().__init__()

        # Add all nodes first (including orphans with no connections)
        self.nodes = list(node_map.values())

        # Then build edges and update node connections
        self.edges = graph_edges
        for edge in graph_edges:
            if edge not in edge.from_node.outgoing:
                edge.from_node.outgoing.append(edge)
            if edge not in edge.to_node.incoming:
                edge.to_node.incoming.append(edge)

    def validate(self) -> ValidationResult:
        node_validations: dict[int, ValidationResultNode] = {}
        for node in self.nodes:
            real_node = node.data
            validation_result = real_node.get_manager().validate(node, self)
            if validation_result is not None and not validation_result.valid():
                node_validations[validation_result.node] = validation_result

        graph_errors: list[str] = []
        if len(self.get_roots()) > 1:
            graph_errors.append("Pipeline must have exactly one root node")
            for root in self.get_roots():
                node_validation = node_validations[
                    root.data.id] if root.data.id in node_validations else ValidationResultNode(root.data.id, [], {},
                                                                                                {})
                if len(root.incoming) == 0 and len(root.outgoing) == 0:
                    node_validation.errors.append("This node is orphaned")
                else:
                    node_validation.errors.append("Pipeline must have exactly one root node")
                node_validations[root.data.id] = node_validation

        if self.has_cycle():
            graph_errors.append("Pipeline contains a cycle")

        edge_errors: list[ValidationResultEdge] = []
        for edge in self.edges:
            for slot_a in edge.from_node.data.get_manager().get_dynamic_slots_schematics():
                print(edge.data)
                if slot_a.name != edge.data.incoming_slot.name:
                    continue
                for slot_b in edge.to_node.data.get_manager().get_dynamic_slots_schematics():
                    if slot_b.name != edge.data.outgoing_slot.name:
                        continue
                    if slot_a.type == SlotType.DEVICE_AUDIO_OUTPUT:
                        edge_errors.append(ValidationResultEdge(edge.data.id, [f"Output device cannot only receive audio"]))
                    if slot_b.type == SlotType.DEVICE_AUDIO_INPUT:
                        edge_errors.append(ValidationResultEdge(edge.data.id, [f"Input device cannot only send audio"]))
                    if slot_a.type == SlotType.DEVICE_AUDIO_INPUT and slot_b.type != SlotType.AUDIO_CONSUMER:
                        edge_errors.append(ValidationResultEdge(edge.data.id, [f"Input device must be connected to an audio consumer"]))
                    if slot_a.type == SlotType.AUDIO_PRODUCER and slot_b.type != SlotType.DEVICE_AUDIO_OUTPUT:
                        edge_errors.append(ValidationResultEdge(edge.data.id, [f"Producer cannot only send audio to an output device"]))
                    break
                break

        return ValidationResult(list(node_validations.values()), edge_errors, graph_errors)
