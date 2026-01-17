from typing import NamedTuple, TYPE_CHECKING

from core.audio.pipeline.validation_result import ValidationResult, ValidationResultNode
from core.utils.graph import GraphEdge, Graph, GraphNode

if TYPE_CHECKING:
    from api.models.audio.pipeline.audio_pipeline_node import AudioPipelineNode
    from api.models.audio.audio_pipeline import AudioPipeline
    from api.models.audio.pipeline.audio_pipeline_node_slot import AudioPipelineNodeSlot


class EdgeSlots(NamedTuple):
    incoming_slot: 'AudioPipelineNodeSlot'
    outgoing_slot: 'AudioPipelineNodeSlot'

type AudioPipelineGraphEdge = GraphEdge['AudioPipelineNode', EdgeSlots]
type AudioPipelineGraphNode = GraphNode['AudioPipelineNode', EdgeSlots]

class AudioPipelineGraph(Graph['AudioPipelineNode', EdgeSlots]):

    def __init__(self, pipeline: 'AudioPipeline'):
        from api.views.audio_pipelines import find_model_by_name

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

                        graph_edge = GraphEdge(
                            data=db_edge,
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
            validation_result = real_node.validate(node, self)
            if validation_result is not None:
                node_validations[validation_result.node] = validation_result

        graph_errors: list[str] = []
        if len(self.get_roots()) > 1:
            graph_errors.append("Pipeline must have exactly one root node")
            for root in self.get_roots():
                node_validation = node_validations[root.data.id] if root.data.id in node_validations else ValidationResultNode(root.data.id, [], {}, {})
                if len(root.incoming) == 0 and len(root.outgoing) == 0:
                    node_validation.errors.append("This node is orphaned")
                else:
                    node_validation.errors.append("Pipeline must have exactly one root node")
                node_validations[root.data.id] = node_validation

        return ValidationResult(list(node_validations.values()), graph_errors)
