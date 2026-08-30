"""Unified version-2 registry compatibility import.

The name ``PluginRegistry`` remains an internal convenience, but it is the version-2 distribution
registry. Version-1 entry-point groups and adapters no longer exist.
"""

from .v2_registry import (
    DuplicatePluginDistributionError,
    PluginCapabilityRecord,
    PluginDistributionRecord,
    PluginDistributionRegistrationError,
    PluginDistributionRegistry,
    PluginIdentityMismatchError,
    PluginProvenance,
    ProhibitedPluginCapabilityError,
)

PluginRegistry = PluginDistributionRegistry
PluginRecord = PluginDistributionRecord
PluginRegistrationError = PluginDistributionRegistrationError

__all__ = [
    "DuplicatePluginDistributionError",
    "PluginCapabilityRecord",
    "PluginDistributionRecord",
    "PluginDistributionRegistrationError",
    "PluginDistributionRegistry",
    "PluginIdentityMismatchError",
    "PluginProvenance",
    "PluginRecord",
    "PluginRegistrationError",
    "PluginRegistry",
    "ProhibitedPluginCapabilityError",
]
