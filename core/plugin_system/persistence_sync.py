from __future__ import annotations

from django.db import OperationalError, ProgrammingError

from api.models import PluginDesiredState as StoredDesiredState
from api.models import PluginInstallation

from .storage import PluginInstallationRepository
from .v2_contracts import PluginDesiredState
from .v2_registry import PluginDistributionRegistry


def synchronize_plugin_inventory(registry: PluginDistributionRegistry) -> bool:
    """Best-effort startup join between installed entry points and durable desired state.

    Migration and static-analysis commands may run before the plugin tables exist, so callers can
    continue startup when this returns false. Normal service readiness calls it again with the
    migrated schema.
    """

    try:
        for record in registry.records:
            existing = PluginInstallation.objects.filter(
                plugin_id=record.manifest.plugin_id,
                distribution_id=record.manifest.distribution_id,
                installed_version=record.manifest.version,
            ).first()
            provenance = record.provenance.to_document()
            # Runtime entry-point discovery can confirm the installed distribution,
            # but it cannot reconstruct the immutable acquisition URL, digest, or
            # resolved revision. Preserve that stronger evidence when startup sees
            # the exact distribution/version already recorded by an operation.
            if existing is not None and existing.provenance_snapshot:
                provenance = existing.provenance_snapshot
            installation = PluginInstallationRepository.save_snapshot(
                plugin_id=record.manifest.plugin_id,
                distribution_id=record.manifest.distribution_id,
                installed_version=record.manifest.version,
                manifest=record.manifest.to_document(),
                provenance=provenance,
                lifecycle_impact=record.manifest.lifecycle.to_document(),
                desired_state=StoredDesiredState.ENABLED,
            )
            record.desired_state = PluginDesiredState(installation.desired_state)
            PluginInstallationRepository.synchronize_capabilities(
                record.manifest.plugin_id,
                [item.to_document() for item in record.capabilities],
            )
        return True
    except (OperationalError, ProgrammingError):
        return False


def refresh_plugin_desired_state(registry: PluginDistributionRegistry) -> bool:
    try:
        desired = dict(
            PluginInstallation.objects.values_list("plugin_id", "desired_state")
        )
    except (OperationalError, ProgrammingError):
        return False
    for record in registry.records:
        value = desired.get(record.manifest.plugin_id)
        if value is not None:
            record.desired_state = PluginDesiredState(value)
    return True
