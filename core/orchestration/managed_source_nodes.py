from __future__ import annotations

from collections.abc import Mapping

from core.plugin_system.managed_source_identity import managed_source_endpoint_id

from .node_catalogue import NodeTypeRegistry

MANAGED_AUDIO_SOURCE_SCHEMA_KEY = "x-open-cinema-managed-audio-source"


def managed_source_endpoint_for_node(
    node: Mapping[str, object],
    registry: NodeTypeRegistry,
) -> str | None:
    """Resolve a declarative plugin source node to its durable endpoint identity."""

    type_id = node.get("type")
    version = node.get("version")
    configuration = node.get("configuration")
    if (
        not isinstance(type_id, str)
        or isinstance(version, bool)
        or not isinstance(version, int)
        or not isinstance(configuration, Mapping)
    ):
        return None
    definition = registry.get(type_id, version)
    if definition is None:
        return None
    declaration = definition.configuration_schema.get(MANAGED_AUDIO_SOURCE_SCHEMA_KEY)
    if not isinstance(declaration, Mapping):
        return None
    plugin_id = declaration.get("pluginId")
    capability_id = declaration.get("capabilityId")
    instance_property = declaration.get("instanceProperty")
    if not all(
        isinstance(value, str) and value for value in (plugin_id, capability_id, instance_property)
    ):
        return None
    instance_id = configuration.get(instance_property)
    if not isinstance(instance_id, str) or not instance_id:
        return None
    return managed_source_endpoint_id(plugin_id, capability_id, instance_id)
