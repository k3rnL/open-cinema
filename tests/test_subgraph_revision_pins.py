import uuid

import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.revisions import (
    GraphPublicationValidationError,
    publish_draft_revision,
)
from core.orchestration.subgraphs import validate_pinned_subgraph_references


pytestmark = pytest.mark.django_db


def _document(*, graph_id, kind, nodes=None):
    return {
        "schemaVersion": 1,
        "id": graph_id,
        "kind": kind,
        "metadata": {"name": graph_id},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": nodes or [],
        "edges": [],
        "layout": {},
    }


@pytest.fixture
def pinned_revisions():
    owner = get_user_model().objects.create_user(username="subgraph-pins")
    subgraph = GraphDefinition.objects.create(
        name="Reusable filter",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=owner,
    )
    published = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=_document(graph_id="graph:filter", kind="subgraph"),
    )
    draft = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=2,
        state=GraphRevisionState.DRAFT,
        author=owner,
        content=_document(graph_id="graph:filter-next", kind="subgraph"),
    )
    parent = GraphDefinition.objects.create(name="Parent graph", owner=owner)
    return owner, subgraph, published, draft, parent


def _parent_document(definition_id, revision_id):
    return _document(
        graph_id="graph:parent",
        kind="graph",
        nodes=[
            {
                "id": "node:filter",
                "type": "core.subgraph-instance",
                "version": 1,
                "configuration": {},
                "subgraph": {
                    "definitionId": str(definition_id),
                    "revisionId": str(revision_id),
                    "parameterBindings": {},
                    "portBindings": {},
                },
            }
        ],
    )


def test_published_subgraph_revision_is_a_valid_pin(pinned_revisions) -> None:
    _, subgraph, published, _, _ = pinned_revisions

    assert validate_pinned_subgraph_references(
        _parent_document(subgraph.pk, published.pk)
    ) == ()


def test_mutable_missing_and_mismatched_subgraph_pins_are_rejected(
    pinned_revisions,
) -> None:
    owner, subgraph, _, draft, _ = pinned_revisions
    other = GraphDefinition.objects.create(
        name="Other reusable filter",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=owner,
    )
    missing = uuid.uuid4()

    mutable_issues = validate_pinned_subgraph_references(
        _parent_document(subgraph.pk, draft.pk)
    )
    missing_issues = validate_pinned_subgraph_references(
        _parent_document(missing, missing)
    )
    mismatch_issues = validate_pinned_subgraph_references(
        _parent_document(other.pk, draft.pk)
    )

    assert {issue.code for issue in mutable_issues} == {"mutable_subgraph_revision"}
    assert {issue.code for issue in missing_issues} == {
        "missing_subgraph_definition",
        "missing_subgraph_revision",
    }
    assert {issue.code for issue in mismatch_issues} >= {
        "subgraph_revision_definition_mismatch",
        "mutable_subgraph_revision",
    }


def test_publication_gate_rejects_mutable_subgraph_pin(pinned_revisions) -> None:
    owner, subgraph, _, draft_subgraph, parent = pinned_revisions
    parent_draft = GraphRevision.objects.create(
        definition=parent,
        revision_number=1,
        state=GraphRevisionState.DRAFT,
        author=owner,
        content=_parent_document(subgraph.pk, draft_subgraph.pk),
    )

    with pytest.raises(GraphPublicationValidationError) as caught:
        publish_draft_revision(
            revision_id=parent_draft.pk,
            expected_update_version=1,
        )

    assert "mutable_subgraph_revision" in {
        issue.code for issue in caught.value.result.issues
    }
    parent_draft.refresh_from_db()
    assert parent_draft.state == GraphRevisionState.DRAFT
