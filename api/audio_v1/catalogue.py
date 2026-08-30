from __future__ import annotations

from api.apps import PLUGIN_REGISTRY
from core.orchestration.audio_node_catalogue import audio_node_type_registry


def api_node_type_registry():
    from api.apps import refresh_plugin_runtime

    refresh_plugin_runtime()
    return audio_node_type_registry(plugin_registry=PLUGIN_REGISTRY)


def catalogue_items() -> list[dict[str, object]]:
    registry = api_node_type_registry()
    items = []
    registered = {(definition.type_id, definition.version) for definition in registry.definitions()}
    for definition in registry.definitions():
        owner = PLUGIN_REGISTRY.node_type_owner(definition.type_id, definition.version)
        source = "plugin" if owner is not None else "managed"
        if definition.type_id.startswith("core."):
            source = "core"
        document = definition.to_document()
        document.update(
            {
                "available": True,
                "source": source,
                "pluginId": owner.manifest.plugin_id if owner is not None else None,
                "ui": {
                    "advanced": True,
                    "paletteGroup": definition.category,
                    "icon": definition.category,
                },
            }
        )
        items.append(document)
    for record, capability, manifest in PLUGIN_REGISTRY.processing_node_manifests():
        if (manifest.type_id, manifest.version) in registered:
            continue
        document = manifest.to_document()
        document.update(
            {
                "available": False,
                "source": "plugin",
                "pluginId": record.manifest.plugin_id,
                "pluginState": record.state.value,
                "availabilityDiagnostics": [
                    item.to_document() for item in (*record.diagnostics, *capability.diagnostics)
                ],
                "ui": {
                    "advanced": True,
                    "paletteGroup": manifest.category,
                    "icon": manifest.category,
                },
            }
        )
        items.append(document)
    items.sort(key=lambda item: (item["id"], item["version"]))
    return items
