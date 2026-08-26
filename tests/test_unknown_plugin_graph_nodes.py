import copy
import uuid

import pytest
from django.contrib.auth import get_user_model

from api.models import GraphDefinition, GraphRevision, GraphRevisionState
from core.orchestration.graph_import_export import (
    export_graph_revision,
    import_graph_bundle,
)
from core.orchestration.graph_validation import validate_graph_structure
from core.orchestration.revisions import edit_draft_revision


pytestmark = pytest.mark.django_db


OPAQUE_CONFIGURATION = {
    "futureSchema": 7,
    "nested": {
        "pluginSpecific": [
            {"band": 0, "coefficients": [1.0, -0.5, 0.25]},
            {"band": 1, "mode": "experimental"},
        ],
        "nullValue": None,
    },
    "orderedPolicy": ["first", "second", "third"],
}


def _unknown_plugin_document():
    return {
        "schemaVersion": 1,
        "id": "graph:unknown-plugin-roundtrip",
        "kind": "graph",
        "metadata": {"name": "Unavailable plugin graph"},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "node:future-processor",
                "type": "thirdparty.future-processor",
                "version": 7,
                "configuration": copy.deepcopy(OPAQUE_CONFIGURATION),
                "extensions": {
                    "thirdparty.ui": {"customPanel": "advanced"}
                },
                "layout": {"x": 15, "y": 25},
            }
        ],
        "edges": [],
        "layout": {},
    }


def _draft():
    owner = get_user_model().objects.create_user(
        username=f"unknown-plugin-{uuid.uuid4()}"
    )
    definition = GraphDefinition.objects.create(
        name="Unknown plugin preservation",
        owner=owner,
    )
    revision = GraphRevision.objects.create(
        definition=definition,
        revision_number=1,
        state=GraphRevisionState.DRAFT,
        author=owner,
        content=_unknown_plugin_document(),
    )
    return owner, definition, revision


def test_unavailable_plugin_is_diagnostic_not_destructive() -> None:
    document = _unknown_plugin_document()
    original = copy.deepcopy(document)

    result = validate_graph_structure(document)

    assert result.valid is False
    assert [issue.code for issue in result.issues] == ["node_type_unavailable"]
    assert document == original
    assert document["nodes"][0]["configuration"] == OPAQUE_CONFIGURATION


def test_editing_other_fields_preserves_opaque_plugin_configuration() -> None:
    _, _, draft = _draft()
    edited_document = copy.deepcopy(draft.content)
    edited_document["metadata"]["description"] = "A safe edit while plugin is absent"

    edited = edit_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
        content=edited_document,
    )

    assert edited.validation_summary["valid"] is False
    assert edited.content["nodes"][0]["configuration"] == OPAQUE_CONFIGURATION
    assert edited.content["nodes"][0]["extensions"] == {
        "thirdparty.ui": {"customPanel": "advanced"}
    }


def test_export_import_round_trip_preserves_unknown_plugin_fields() -> None:
    owner, definition, revision = _draft()
    expected_content = copy.deepcopy(revision.content)
    bundle = export_graph_revision(revision)
    definition_id = definition.pk
    revision_id = revision.pk
    definition.delete()

    result = import_graph_bundle(bundle, owner=owner)

    restored = GraphRevision.objects.get(pk=result.revision_id)
    assert result.definition_id == definition_id
    assert result.revision_id == revision_id
    assert restored.content == expected_content
    assert restored.content["nodes"][0]["configuration"] == OPAQUE_CONFIGURATION
