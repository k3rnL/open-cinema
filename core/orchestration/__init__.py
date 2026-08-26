"""Desired-audio orchestration foundations."""

from .feature_flags import (
    AudioMutationDisabled,
    AudioOrchestrationFeatureFlags,
    get_audio_orchestration_feature_flags,
)
from .schema_version import (
    CURRENT_ORCHESTRATION_SCHEMA_VERSION,
    MissingOrchestrationSchemaMarker,
    OrchestrationSchemaCompatibilityError,
    UnsupportedOrchestrationSchema,
    ensure_persistent_orchestration_schema_compatible,
)
from .wyreplumber_contract import (
    SUPPORTED_WIREPLUMBER_API_FAMILY,
    SUPPORTED_WYREPLUMBER_CONTRACT,
    WyrePlumberCompatibility,
    WyrePlumberCompatibilityError,
    require_wyreplumber_contract,
)
from .graph_schema import (
    DESIRED_GRAPH_SCHEMA_VERSION,
    desired_graph_envelope_validator,
    desired_graph_schema,
)
from .signal_contracts import (
    AudioContent,
    ChannelLayout,
    KnownSampleFormat,
    LatencyRange,
    MediaKind,
    PortCompatibility,
    PortContract,
    PortDirection,
    SignalContract,
)
from .signal_descriptors import (
    SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalContentKind,
    SignalDescriptor,
    SignalObservationSource,
    SignalObservationSourceKind,
    SignalTransportDescriptor,
    SignalTransportKind,
)

__all__ = [
    "AudioMutationDisabled",
    "AudioOrchestrationFeatureFlags",
    "get_audio_orchestration_feature_flags",
    "CURRENT_ORCHESTRATION_SCHEMA_VERSION",
    "MissingOrchestrationSchemaMarker",
    "OrchestrationSchemaCompatibilityError",
    "UnsupportedOrchestrationSchema",
    "ensure_persistent_orchestration_schema_compatible",
    "SUPPORTED_WIREPLUMBER_API_FAMILY",
    "SUPPORTED_WYREPLUMBER_CONTRACT",
    "WyrePlumberCompatibility",
    "WyrePlumberCompatibilityError",
    "require_wyreplumber_contract",
    "DESIRED_GRAPH_SCHEMA_VERSION",
    "desired_graph_envelope_validator",
    "desired_graph_schema",
    "AudioContent",
    "ChannelLayout",
    "KnownSampleFormat",
    "LatencyRange",
    "MediaKind",
    "PortCompatibility",
    "PortContract",
    "PortDirection",
    "SignalContract",
    "SIGNAL_DESCRIPTOR_SCHEMA_VERSION",
    "AudioFormatDescriptor",
    "SignalContentDescriptor",
    "SignalContentKind",
    "SignalDescriptor",
    "SignalObservationSource",
    "SignalObservationSourceKind",
    "SignalTransportDescriptor",
    "SignalTransportKind",
]
