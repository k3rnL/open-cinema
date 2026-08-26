import json

import pytest

from core.orchestration.fact_catalogue import (
    FACT_CATALOGUE_VERSION,
    FactCatalogue,
    FactDefinition,
    FactNamespace,
    FactValueType,
    core_fact_catalogue,
)


def test_core_catalogue_covers_every_required_namespace() -> None:
    catalogue = core_fact_catalogue()

    assert {definition.namespace for definition in catalogue.definitions()} == set(
        FactNamespace
    )
    assert catalogue.resolve("endpoint.endpoint:headset.availability").definition.value_type is (
        FactValueType.ENUM
    )
    assert catalogue.resolve("signal.node:decoder.content.codec").definition.value_type is (
        FactValueType.STRING
    )
    assert catalogue.resolve("processor.camilladsp.room.health").definition.value_type is (
        FactValueType.ENUM
    )
    assert catalogue.resolve("resource.decoder/capacity.capacity").definition.value_type is (
        FactValueType.INTEGER
    )


def test_dynamic_identifiers_with_dots_colons_and_slashes_resolve() -> None:
    result = core_fact_catalogue().resolve(
        "endpoint.room/living.left:headset.activeSignal"
    )

    assert result is not None
    assert result.bindings == {"endpoint": "room/living.left:headset"}
    assert result.definition.namespace is FactNamespace.ENDPOINT


def test_unknown_or_unsafe_fact_paths_do_not_resolve() -> None:
    catalogue = core_fact_catalogue()

    assert catalogue.resolve("runtime.node.42") is None
    assert catalogue.resolve("endpoint. availability") is None
    assert catalogue.resolve("endpoint.headset.unknown") is None
    assert catalogue.resolve("endpoint.../../secret.availability") is None


def test_graph_parameter_definitions_refine_generic_parameter_metadata() -> None:
    catalogue = core_fact_catalogue().with_graph_parameters(
        (
            {
                "name": "volume",
                "type": "number",
                "required": True,
                "description": "Requested listening volume.",
            },
            {
                "name": "profile",
                "type": "enum",
                "required": False,
                "enum": ["cinema", "music"],
            },
        )
    )

    volume = catalogue.resolve("parameter.volume").definition
    profile = catalogue.resolve("parameter.profile").definition
    other = catalogue.resolve("parameter.pluginValue").definition

    assert volume.path_pattern == "parameter.volume"
    assert volume.value_schema() == {"type": "number"}
    assert profile.value_schema() == {
        "anyOf": [
            {"type": "string", "enum": ["cinema", "music"]},
            {"type": "null"},
        ]
    }
    assert other.value_type is FactValueType.JSON


def test_catalogue_document_is_versioned_deterministic_and_json_serializable() -> None:
    catalogue = core_fact_catalogue()

    first = catalogue.to_document()
    second = catalogue.to_document()

    assert first == second
    assert first["version"] == FACT_CATALOGUE_VERSION
    assert json.loads(json.dumps(first, sort_keys=True)) == first
    assert first["facts"] == sorted(
        first["facts"],
        key=lambda item: (item["namespace"], item["pathPattern"]),
    )


def test_duplicate_fact_pattern_is_rejected() -> None:
    definition = FactDefinition(
        path_pattern="mode.{mode}",
        namespace=FactNamespace.MODE,
        value_type=FactValueType.JSON,
        description="Mode.",
    )
    catalogue = FactCatalogue((definition,))

    with pytest.raises(ValueError, match="already registered"):
        catalogue.register(definition)
