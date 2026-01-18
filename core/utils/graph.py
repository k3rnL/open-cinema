from typing import Generic, TypeVar

T = TypeVar('T')
V = TypeVar('V')

class GraphEdge(Generic[T, V]):
    def __init__(self, data: V, from_node: 'GraphNode[T, V]', to_node: 'GraphNode[T, V]'):
        self.data = data
        self.from_node = from_node
        self.to_node = to_node

class GraphNode(Generic[T, V]):
    def __init__(self, data: T, incoming: list['GraphEdge[T, V]'] = None, outgoing: list['GraphEdge[T, V]'] = None):
        self.data = data
        self.incoming: list[GraphEdge[T, V]] = []
        self.outgoing: list[GraphEdge[T, V]] = []
        if incoming is not None:
            self.incoming.extend(incoming)
        if outgoing is not None:
            self.outgoing.extend(outgoing)


class Graph(Generic[T, V]):

    def __init__(self, initial_nodes: list[GraphNode[T, V]] = None, initial_edges: list[GraphEdge[T, V]] = None):
        self.nodes: list[GraphNode[T, V]] = []
        self.edges: list[GraphEdge[T, V]] = []
        if initial_edges is not None:
            self.edges = initial_edges
        if initial_nodes is not None:
            self.nodes = initial_nodes

    def build_from_edges(self, edges: list[GraphEdge[T, V]]):
        """
        Builds the graph from a list of edges, ensuring nodes are added and connections are updated.
        """
        self.edges = edges
        seen_nodes = set()
        for edge in edges:
            if edge.from_node not in seen_nodes:
                self.nodes.append(edge.from_node)
                seen_nodes.add(edge.from_node)
            if edge.to_node not in seen_nodes:
                self.nodes.append(edge.to_node)
                seen_nodes.add(edge.to_node)

            # Update node connections
            if edge not in edge.from_node.outgoing:
                edge.from_node.outgoing.append(edge)
            if edge not in edge.to_node.incoming:
                edge.to_node.incoming.append(edge)

    def build_from_nodes(self, nodes: list[GraphNode[T, V]]):
        """
        Builds the graph from a list of nodes, collecting all edges from their connections.
        """
        self.nodes = nodes
        seen_edges = set()
        for node in nodes:
            for edge in node.outgoing:
                if edge not in seen_edges:
                    self.edges.append(edge)
                    seen_edges.add(edge)
            for edge in node.incoming:
                if edge not in seen_edges:
                    self.edges.append(edge)
                    seen_edges.add(edge)

    def has_cycle(self) -> bool:
        """
        Checks if the graph contains a cycle by performing a depth-first search.
        Returns True if a cycle is detected, False otherwise.
        """
        visited: set[GraphNode[T, V]] = set()
        stack: list[GraphNode[T, V]] = [self.nodes[0]]
        while stack:
            node: GraphNode[T, V] = stack.pop()
            if node in visited:
                return True
            visited.add(node)
            stack.extend([e.to_node for e in node.outgoing])
        return False

    def get_roots(self) -> list[GraphNode[T, V]]:
        """
        Returns a list of root nodes in the graph, i.e., nodes with no incoming edges.
        """
        return [node for node in self.nodes if not node.incoming]