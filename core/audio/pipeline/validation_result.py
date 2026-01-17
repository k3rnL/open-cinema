from typing import NamedTuple


class ValidationResultNode(NamedTuple):
    node: int
    errors: list[str] # Node specific errors
    fields: dict[str, str]
    slots: dict[str, str]
    def valid(self):
        return len(self.errors) == 0 and len(self.fields) == 0 and len(self.slots) == 0

class ValidationResult(NamedTuple):
    nodes: list[ValidationResultNode]
    graph_errors: list[str]
    def valid(self):
        return len(self.nodes) == 0 and len(self.graph_errors) == 0