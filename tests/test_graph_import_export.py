import copy
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from api.models import GraphDefinition, GraphRevision, GraphRevisionState
from core.orchestration.graph_import_export import (
    GraphImportValidationError,
    canonical_graph_export_json,
    export_graph_revision,
    import_graph_bundle,
)


pytestmark = pytest.mark.django_db
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "orchestration"
    / "canonical"
    / "desired_graph.json"
)


def _revision():
    owner = get_user_model().objects.create_user(username=f"exporter-{uuid.uuid4()}")
    definition = GraphDefinition.objects.create(
        name="Exportable home cinema",
        owner=owner,
        labels={"room": "living-room"},
    )
    content = json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]
    revision = GraphRevision.objects.create(
        definition=definition,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=content,
        validation_summary={"valid": True},
    )
    return owner, definition, revision


def test_export_delete_and_import_preserves_stable_ids_and_digest() -> None:
    owner, definition, revision = _revision()
    bundle = export_graph_revision(revision)
    encoded = canonical_graph_export_json(revision)
    definition_id = definition.pk
    revision_id = revision.pk
    digest = revision.content_digest
    definition.delete()

    result = import_graph_bundle(json.loads(encoded), owner=owner)

    restored_revision = GraphRevision.objects.get(pk=revision_id)
    assert result.created is True
    assert result.definition_id == definition_id
    assert result.revision_id == revision_id
    assert restored_revision.definition_id == definition_id
    assert restored_revision.content_digest == digest == bundle["revision"]["contentDigest"]


def test_valid_dry_run_reports_ids_without_creating_rows() -> None:
    owner, definition, revision = _revision()
    bundle = export_graph_revision(revision)
    definition.delete()

    result = import_graph_bundle(bundle, owner=owner, dry_run=True)

    assert result.valid is True
    assert result.created is False
    assert result.dry_run is True
    assert result.issues == ()
    assert not GraphDefinition.objects.filter(pk=result.definition_id).exists()
    assert not GraphRevision.objects.filter(pk=result.revision_id).exists()


def test_future_schema_dry_run_is_rejected_without_partial_writes() -> None:
    owner, definition, revision = _revision()
    bundle = export_graph_revision(revision)
    definition.delete()
    bundle["revision"]["schemaVersion"] = 2
    bundle["revision"]["content"]["schemaVersion"] = 2

    result = import_graph_bundle(bundle, owner=owner, dry_run=True)

    assert result.valid is False
    assert {issue.code for issue in result.issues} >= {
        "unsupported_schema_version",
        "schema_const",
        "digest_mismatch",
    }
    assert not GraphDefinition.objects.filter(pk=result.definition_id).exists()


def test_live_invalid_import_raises_structured_error() -> None:
    owner, definition, revision = _revision()
    bundle = export_graph_revision(revision)

    with pytest.raises(GraphImportValidationError) as caught:
        import_graph_bundle(bundle, owner=owner)

    assert {issue.code for issue in caught.value.issues} >= {
        "id_conflict",
        "name_conflict",
    }


def test_revision_failure_rolls_back_definition_creation() -> None:
    owner, definition, revision = _revision()
    bundle = copy.deepcopy(export_graph_revision(revision))
    definition.delete()

    with patch.object(GraphRevision, "save", side_effect=RuntimeError("disk failure")):
        with pytest.raises(RuntimeError, match="disk failure"):
            import_graph_bundle(bundle, owner=owner)

    assert not GraphDefinition.objects.filter(pk=bundle["definition"]["id"]).exists()
