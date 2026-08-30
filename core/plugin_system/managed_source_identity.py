from __future__ import annotations

import uuid

_MANAGED_SOURCE_NAMESPACE = uuid.UUID("314013d3-1a1b-4a8d-9007-12a916019fed")


def managed_source_endpoint_id(
    plugin_id: str,
    capability_id: str,
    instance_id: str,
) -> str:
    """Return the stable logical-endpoint UUID for one managed source instance."""

    for value, name in (
        (plugin_id, "plugin_id"),
        (capability_id, "capability_id"),
        (instance_id, "instance_id"),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
    identity = f"{plugin_id}\n{capability_id}\n{instance_id}"
    return str(uuid.uuid5(_MANAGED_SOURCE_NAMESPACE, identity))
