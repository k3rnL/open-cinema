from typing import NamedTuple


class ValidationResultEdge(NamedTuple):
    edge: int
    errors: list[str]

    def valid(self):
        return len(self.errors) == 0


class ValidationResultNode(NamedTuple):
    node: int
    errors: list[str]  # Node specific errors
    fields: dict[str, str]
    slots: dict[str, str]

    def valid(self):
        return len(self.errors) == 0 and len(self.fields) == 0 and len(self.slots) == 0


class ValidationResult(NamedTuple):
    nodes: list[ValidationResultNode] = list
    edges: list[ValidationResultEdge] = list
    graph_errors: list[str] = list

    def valid(self):
        return (len(self.nodes) == 0
                and len(self.graph_errors) == 0
                and len(self.edges) == 0)
