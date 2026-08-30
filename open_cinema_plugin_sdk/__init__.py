"""Stable public imports for Open Cinema plugin authors.

The SDK is shipped by the Open Cinema runtime. Plugin projects should use this
module instead of importing private registry, persistence, or orchestration
implementation modules.
"""

from core.plugin_system import *  # noqa: F403
from core.plugin_system import (
    ActionConfirmation,
    AdminUICapability,
    ApiCapability,
    AudioContent,
    AutomationCapability,
    ChannelLayout,
    DistributionLifecycleContext,
    LifecycleImpact,
    ManagedAudioSourceCapability,
    ManagedResourceCapability,
    ManagedResourceContext,
    ManagedResourceObservation,
    MediaKind,
    NodePortDefinition,
    OpenCinemaPlugin,
    PluginActionDescriptor,
    PluginCapabilityContribution,
    PluginRuntimeResult,
    PortContract,
    PortDirection,
    ProcessingCapability,
    ProcessingHookContext,
    ProcessingNodeTypeManifest,
    ProcessingPlan,
    ProcessingValidationIssue,
    RuntimePluginIdentity,
    RuntimeStatus,
    SignalContract,
)
from core.plugin_system import __all__ as _contract_exports

from .contract_testing import (
    PluginContractReport,
    assert_plugin_contract,
    validate_built_wheel,
    validate_runtime_plugin,
    validate_source_checkout,
)
from .errors import PluginConcurrencyError
from .host_storage import (
    PluginDocument,
    PluginDocumentStore,
    PluginInstanceDocument,
    PluginInstanceStore,
    PluginSecretStore,
)
from .managed_sources import managed_source_endpoint_id

SDK_CONTRACT_VERSION = 2

__all__ = [
    *_contract_exports,
    "ActionConfirmation",
    "AdminUICapability",
    "ApiCapability",
    "AudioContent",
    "AutomationCapability",
    "ChannelLayout",
    "DistributionLifecycleContext",
    "LifecycleImpact",
    "ManagedAudioSourceCapability",
    "ManagedResourceCapability",
    "ManagedResourceContext",
    "ManagedResourceObservation",
    "MediaKind",
    "NodePortDefinition",
    "OpenCinemaPlugin",
    "PluginActionDescriptor",
    "PluginCapabilityContribution",
    "PluginRuntimeResult",
    "PortContract",
    "PortDirection",
    "ProcessingCapability",
    "ProcessingHookContext",
    "ProcessingNodeTypeManifest",
    "ProcessingPlan",
    "ProcessingValidationIssue",
    "RuntimePluginIdentity",
    "RuntimeStatus",
    "SignalContract",
    "SDK_CONTRACT_VERSION",
    "PluginContractReport",
    "assert_plugin_contract",
    "validate_built_wheel",
    "validate_runtime_plugin",
    "validate_source_checkout",
    "PluginInstanceDocument",
    "PluginInstanceStore",
    "PluginSecretStore",
    "PluginDocument",
    "PluginDocumentStore",
    "managed_source_endpoint_id",
    "PluginConcurrencyError",
]
