import copy

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from api.models import GraphDefinition, GraphRevision, GraphRevisionState
from core.orchestration.activations import GraphActivationConflict, activate_graph
from core.orchestration.revisions import (
    GraphPublicationValidationError,
    GraphRevisionConflict,
    GraphRevisionNotDraft,
    compare_graph_revisions,
    edit_draft_revision,
    publish_draft_revision,
)


pytestmark = pytest.mark.django_db


def _document(name="Draft graph"):
    return {
        "schemaVersion": 1,
        "id": "graph:draft-workflow",
        "kind": "graph",
        "metadata": {"name": name},
        "parameters": [],
        "publicPorts": [],
        "conditions": [],
        "nodes": [
            {
                "id": "node:endpoint",
                "type": "core.endpoint-reference",
                "version": 1,
                "configuration": {
                    "logicalEndpointId": "endpoint:headset",
                    "direction": "output",
                },
                "layout": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
        "layout": {"viewport": {"x": 0, "y": 0, "zoom": 1}},
    }


@pytest.fixture
def revision_workflow():
    author = get_user_model().objects.create_user(username="revision-workflow")
    graph = GraphDefinition.objects.create(name="Workflow graph", owner=author)
    draft = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        state=GraphRevisionState.DRAFT,
        author=author,
        content=_document(),
    )
    return author, graph, draft


def test_draft_edit_is_optimistic_and_can_remain_structurally_invalid(
    revision_workflow,
) -> None:
    _, _, draft = revision_workflow
    invalid = _document("Invalid work in progress")
    invalid["nodes"][0]["type"] = "plugin.not-installed"

    edited = edit_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
        content=invalid,
    )

    assert edited.update_version == 2
    assert edited.state == GraphRevisionState.DRAFT
    assert edited.content["metadata"]["name"] == "Invalid work in progress"
    assert edited.validation_summary["valid"] is False
    assert edited.validation_summary["issues"][0]["code"] == "node_type_unavailable"


def test_stale_draft_edit_cannot_overwrite_newer_content(revision_workflow) -> None:
    _, _, draft = revision_workflow
    first = edit_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
        content=_document("First writer"),
    )

    with pytest.raises(GraphRevisionConflict, match="found 2"):
        edit_draft_revision(
            revision_id=draft.pk,
            expected_update_version=1,
            content=_document("Stale writer"),
        )

    first.refresh_from_db()
    assert first.content["metadata"]["name"] == "First writer"


def test_valid_draft_publication_is_one_way_and_detects_competing_request(
    revision_workflow,
) -> None:
    _, _, draft = revision_workflow

    published = publish_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
    )

    assert published.state == GraphRevisionState.PUBLISHED
    assert published.published_at is not None
    assert published.update_version == 2
    assert published.validation_summary["valid"] is True
    with pytest.raises(GraphRevisionConflict, match="another request"):
        publish_draft_revision(
            revision_id=draft.pk,
            expected_update_version=1,
        )
    with pytest.raises(GraphRevisionNotDraft, match="immutable"):
        edit_draft_revision(
            revision_id=draft.pk,
            expected_update_version=2,
            content=_document("Forbidden edit"),
        )
    published.content = _document("Direct edit")
    with pytest.raises(ValidationError, match="draft service"):
        published.save()


def test_invalid_draft_cannot_be_published(revision_workflow) -> None:
    _, _, draft = revision_workflow
    invalid = _document()
    invalid["nodes"][0]["configuration"] = {}
    draft = edit_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
        content=invalid,
    )

    with pytest.raises(GraphPublicationValidationError) as caught:
        publish_draft_revision(
            revision_id=draft.pk,
            expected_update_version=2,
        )

    draft.refresh_from_db()
    assert draft.state == GraphRevisionState.DRAFT
    assert "configuration_schema_oneOf" in {
        issue.code for issue in caught.value.result.issues
    }


def test_publish_and_activation_roll_back_together_on_activation_conflict(
    revision_workflow,
) -> None:
    author, graph, draft = revision_workflow
    current = GraphRevision.objects.create(
        definition=graph,
        revision_number=2,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={**_document("Current"), "id": "graph:current"},
    )
    activation = activate_graph(
        definition=graph,
        revision=current,
        expected_version=0,
    )

    with pytest.raises(GraphActivationConflict):
        publish_draft_revision(
            revision_id=draft.pk,
            expected_update_version=1,
            activate=True,
            expected_activation_version=0,
        )

    draft.refresh_from_db()
    activation.refresh_from_db()
    assert draft.state == GraphRevisionState.DRAFT
    assert draft.update_version == 1
    assert activation.revision == current


def test_publish_and_activate_commits_one_desired_state_change(revision_workflow) -> None:
    _, graph, draft = revision_workflow

    published = publish_draft_revision(
        revision_id=draft.pk,
        expected_update_version=1,
        activate=True,
        expected_activation_version=0,
        parameter_bindings={"volume": 0.5},
    )

    activation = graph.activation
    assert published.state == GraphRevisionState.PUBLISHED
    assert activation.revision == published
    assert activation.desired_state_version == 1
    assert activation.parameter_bindings == {"volume": 0.5}


def test_revision_comparison_separates_layout_from_audio_semantics() -> None:
    left = _document()
    layout_edit = copy.deepcopy(left)
    layout_edit["nodes"][0]["layout"] = {"x": 500, "y": 200}
    semantic_edit = copy.deepcopy(left)
    semantic_edit["nodes"][0]["configuration"]["logicalEndpointId"] = "endpoint:speakers"

    layout_comparison = compare_graph_revisions(left, layout_edit)
    semantic_comparison = compare_graph_revisions(left, semantic_edit)

    assert layout_comparison.semantic_equal is True
    assert layout_comparison.layout_equal is False
    assert semantic_comparison.semantic_equal is False
    assert semantic_comparison.collections["nodes"].changed == ("node:endpoint",)
