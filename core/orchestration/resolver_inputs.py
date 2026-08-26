from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from wyreplumber.runtime import FrozenDict

from .endpoint_inventory import EndpointInventorySnapshot
from .graph_documents import graph_content_digest


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _version(value: object, name: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be a {qualifier} integer")
    return value


def _ordered_unique(values: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{name} must be a sequence")
    result = tuple(values)
    if any(not isinstance(value, str) or not value for value in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class ResolverWorldVersion:
    runtime_generation: int
    runtime_sequence: int
    endpoint_version: int
    signal_version: int
    processor_version: int
    override_version: int
    resource_policy_version: int

    def __post_init__(self) -> None:
        for name in (
            "runtime_generation",
            "runtime_sequence",
            "endpoint_version",
            "signal_version",
            "processor_version",
            "override_version",
            "resource_policy_version",
        ):
            _version(getattr(self, name), name)

    @property
    def token(self) -> str:
        return ":".join(
            str(getattr(self, name))
            for name in (
                "runtime_generation",
                "runtime_sequence",
                "endpoint_version",
                "signal_version",
                "processor_version",
                "override_version",
                "resource_policy_version",
            )
        )


@dataclass(frozen=True, slots=True)
class ResolverGraphRevisionInput:
    definition_id: str
    revision_id: str
    revision_number: int
    schema_version: int
    content_digest: str
    document: FrozenDict | Mapping[str, object]

    def __post_init__(self) -> None:
        _nonempty(self.definition_id, "definition_id")
        _nonempty(self.revision_id, "revision_id")
        _version(self.revision_number, "revision_number", positive=True)
        _version(self.schema_version, "schema_version", positive=True)
        _nonempty(self.content_digest, "content_digest")
        frozen = (
            self.document if isinstance(self.document, FrozenDict) else FrozenDict(self.document)
        )
        actual_digest = graph_content_digest(frozen.to_dict())
        if actual_digest != self.content_digest:
            raise ValueError("graph document does not match content_digest")
        object.__setattr__(self, "document", frozen)

    @classmethod
    def from_model(cls, revision) -> ResolverGraphRevisionInput:
        return cls(
            definition_id=str(revision.definition_id),
            revision_id=str(revision.pk),
            revision_number=revision.revision_number,
            schema_version=revision.schema_version,
            content_digest=revision.content_digest,
            document=revision.content,
        )


@dataclass(frozen=True, slots=True)
class ResolverActivationInput:
    activation_id: str
    definition_id: str
    revision_id: str
    desired_state_version: int
    parameter_bindings: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)
    scene_bindings: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _nonempty(self.activation_id, "activation_id")
        _nonempty(self.definition_id, "definition_id")
        _nonempty(self.revision_id, "revision_id")
        _version(self.desired_state_version, "desired_state_version", positive=True)
        object.__setattr__(self, "parameter_bindings", FrozenDict(self.parameter_bindings))
        object.__setattr__(self, "scene_bindings", FrozenDict(self.scene_bindings))

    @classmethod
    def from_model(cls, activation) -> ResolverActivationInput:
        return cls(
            activation_id=str(activation.pk),
            definition_id=str(activation.definition_id),
            revision_id=str(activation.revision_id),
            desired_state_version=activation.desired_state_version,
            parameter_bindings=activation.parameter_bindings,
            scene_bindings=activation.scene_bindings,
        )


@dataclass(frozen=True, slots=True)
class ResolverLogicalEndpointInput:
    endpoint_id: str
    name: str
    direction: str
    selector: FrozenDict | Mapping[str, object]
    tags: tuple[str, ...] | Sequence[str] = ()
    groups: tuple[str, ...] | Sequence[str] = ()
    policy_metadata: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)
    explicit_binding: FrozenDict | Mapping[str, object] | None = None
    update_version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.endpoint_id, "endpoint_id")
        _nonempty(self.name, "name")
        if self.direction not in {"input", "output"}:
            raise ValueError("direction must be input or output")
        object.__setattr__(self, "selector", FrozenDict(self.selector))
        object.__setattr__(self, "tags", _ordered_unique(self.tags, "tags"))
        object.__setattr__(self, "groups", _ordered_unique(self.groups, "groups"))
        object.__setattr__(self, "policy_metadata", FrozenDict(self.policy_metadata))
        if self.explicit_binding is not None:
            object.__setattr__(self, "explicit_binding", FrozenDict(self.explicit_binding))
        _version(self.update_version, "update_version", positive=True)

    @classmethod
    def from_model(cls, endpoint) -> ResolverLogicalEndpointInput:
        return cls(
            endpoint_id=str(endpoint.pk),
            name=endpoint.name,
            direction=endpoint.direction,
            selector=endpoint.selector,
            tags=endpoint.tags,
            groups=endpoint.groups,
            policy_metadata=endpoint.policy_metadata,
            explicit_binding=endpoint.explicit_binding,
            update_version=endpoint.update_version,
        )


@dataclass(frozen=True, slots=True)
class ResolverSignalFactsInput:
    version: int
    facts: FrozenDict | Mapping[str, object]

    def __post_init__(self) -> None:
        _version(self.version, "signal facts version")
        object.__setattr__(self, "facts", FrozenDict(self.facts))


@dataclass(frozen=True, slots=True)
class ResolverProcessorHealthInput:
    processor_id: str
    health: str
    ready: bool
    facts: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _nonempty(self.processor_id, "processor_id")
        _nonempty(self.health, "health")
        if not isinstance(self.ready, bool):
            raise TypeError("ready must be a boolean")
        object.__setattr__(self, "facts", FrozenDict(self.facts))


@dataclass(frozen=True, slots=True)
class ResolverOverrideInput:
    override_id: str
    scope_type: str
    scope_id: str
    value: object
    priority: int
    starts_at: str
    expires_at: str | None
    cancelled_at: str | None
    active: bool
    reason: str

    def __post_init__(self) -> None:
        _nonempty(self.override_id, "override_id")
        _nonempty(self.scope_type, "scope_type")
        _nonempty(self.scope_id, "scope_id")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        _nonempty(self.starts_at, "starts_at")
        if self.expires_at is not None:
            _nonempty(self.expires_at, "expires_at")
        if self.cancelled_at is not None:
            _nonempty(self.cancelled_at, "cancelled_at")
        if not isinstance(self.active, bool):
            raise TypeError("active must be a boolean")
        _nonempty(self.reason, "reason")
        from wyreplumber.runtime import freeze_json

        object.__setattr__(self, "value", freeze_json(self.value))

    @classmethod
    def from_model(
        cls,
        override,
        *,
        at: datetime,
    ) -> ResolverOverrideInput:
        if not isinstance(at, datetime):
            raise TypeError("at must be a datetime")
        return cls(
            override_id=str(override.pk),
            scope_type=override.scope_type,
            scope_id=override.scope_id,
            value=override.value,
            priority=override.priority,
            starts_at=override.starts_at.isoformat(),
            expires_at=(override.expires_at.isoformat() if override.expires_at else None),
            cancelled_at=(override.cancelled_at.isoformat() if override.cancelled_at else None),
            active=override.is_active(at),
            reason=override.reason,
        )


@dataclass(frozen=True, slots=True)
class ResolverResourceInput:
    resource_id: str
    kind: str
    capacity: int
    allocated: int
    health: str
    attributes: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _nonempty(self.resource_id, "resource_id")
        _nonempty(self.kind, "kind")
        _version(self.capacity, "capacity")
        _version(self.allocated, "allocated")
        if self.allocated > self.capacity:
            raise ValueError("allocated resources cannot exceed capacity")
        _nonempty(self.health, "health")
        object.__setattr__(self, "attributes", FrozenDict(self.attributes))


@dataclass(frozen=True, slots=True)
class ResolverResourcePolicyInput:
    version: int
    resources: tuple[ResolverResourceInput, ...] | Sequence[ResolverResourceInput]
    policy: FrozenDict | Mapping[str, object] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _version(self.version, "resource policy version")
        resources = tuple(sorted(self.resources, key=lambda resource: resource.resource_id))
        if any(not isinstance(resource, ResolverResourceInput) for resource in resources):
            raise TypeError("resources must contain ResolverResourceInput values")
        identifiers = [resource.resource_id for resource in resources]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("resource identifiers must be unique")
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "policy", FrozenDict(self.policy))


@dataclass(frozen=True, slots=True)
class ResolverInputs:
    graph: ResolverGraphRevisionInput
    subgraph_revisions: (
        tuple[ResolverGraphRevisionInput, ...] | Sequence[ResolverGraphRevisionInput]
    )
    activation: ResolverActivationInput
    logical_endpoints: (
        tuple[ResolverLogicalEndpointInput, ...] | Sequence[ResolverLogicalEndpointInput]
    )
    runtime_inventory: EndpointInventorySnapshot
    signal_facts: ResolverSignalFactsInput
    processors: tuple[ResolverProcessorHealthInput, ...] | Sequence[ResolverProcessorHealthInput]
    overrides: tuple[ResolverOverrideInput, ...] | Sequence[ResolverOverrideInput]
    resource_policy: ResolverResourcePolicyInput
    world_version: ResolverWorldVersion
    evaluated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.graph, ResolverGraphRevisionInput):
            raise TypeError("graph must be ResolverGraphRevisionInput")
        if not isinstance(self.activation, ResolverActivationInput):
            raise TypeError("activation must be ResolverActivationInput")
        if self.graph.definition_id != self.activation.definition_id:
            raise ValueError("activation and graph definition do not match")
        if self.graph.revision_id != self.activation.revision_id:
            raise ValueError("activation and graph revision do not match")
        subgraph_revisions = tuple(
            sorted(
                self.subgraph_revisions,
                key=lambda revision: (revision.definition_id, revision.revision_id),
            )
        )
        if any(
            not isinstance(revision, ResolverGraphRevisionInput) for revision in subgraph_revisions
        ):
            raise TypeError("subgraph_revisions contains an invalid value")
        revision_ids = [revision.revision_id for revision in subgraph_revisions]
        if self.graph.revision_id in revision_ids or len(revision_ids) != len(set(revision_ids)):
            raise ValueError("subgraph revision identifiers must be unique")
        object.__setattr__(self, "subgraph_revisions", subgraph_revisions)
        if not isinstance(self.runtime_inventory, EndpointInventorySnapshot):
            raise TypeError("runtime_inventory must be EndpointInventorySnapshot")
        if (
            self.runtime_inventory.generation != self.world_version.runtime_generation
            or self.runtime_inventory.sequence != self.world_version.runtime_sequence
        ):
            raise ValueError("runtime inventory and world version do not match")
        if self.signal_facts.version != self.world_version.signal_version:
            raise ValueError("signal facts and world version do not match")
        if self.resource_policy.version != self.world_version.resource_policy_version:
            raise ValueError("resource policy and world version do not match")
        _nonempty(self.evaluated_at, "evaluated_at")

        endpoints = tuple(sorted(self.logical_endpoints, key=lambda endpoint: endpoint.endpoint_id))
        processors = tuple(sorted(self.processors, key=lambda processor: processor.processor_id))
        overrides = tuple(
            sorted(
                self.overrides,
                key=lambda override: (
                    -override.priority,
                    override.starts_at,
                    override.override_id,
                ),
            )
        )
        for values, value_type, name, identity in (
            (endpoints, ResolverLogicalEndpointInput, "logical_endpoints", "endpoint_id"),
            (processors, ResolverProcessorHealthInput, "processors", "processor_id"),
            (overrides, ResolverOverrideInput, "overrides", "override_id"),
        ):
            if any(not isinstance(value, value_type) for value in values):
                raise TypeError(f"{name} contains an invalid value")
            identifiers = [getattr(value, identity) for value in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} identifiers must be unique")
        object.__setattr__(self, "logical_endpoints", endpoints)
        object.__setattr__(self, "processors", processors)
        object.__setattr__(self, "overrides", overrides)
