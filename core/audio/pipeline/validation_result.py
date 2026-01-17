from typing import NamedTuple


class ValidationResultNode(NamedTuple):
    node: int
    error: str | None
    fields: dict[str, str]
    slots: dict[str, str]
    def valid(self):
        return self.error is None and len(self.fields) == 0 and len(self.slots) == 0

class ValidationResult(NamedTuple):
    nodes: list[ValidationResultNode]
    def valid(self):
        return len(self.nodes) == 0