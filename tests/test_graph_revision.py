import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from api.models import (
    GraphDefinition,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.graph_documents import canonical_graph_json


pytestmark = pytest.mark.django_db


@pytest.fixture
def graph_and_author():
    author = get_user_model().objects.create_user(username="revision-author")
    graph = GraphDefinition.objects.create(name="Cinema", owner=author)
    return graph, author


def test_revision_has_canonical_digest_and_publication_metadata(graph_and_author) -> None:
    graph, author = graph_and_author
    first = GraphRevision.objects.create(
        definition=graph,
        schema_version=1,
        revision_number=1,
        state=GraphRevisionState.DRAFT,
        author=author,
        content={"nodes": [], "metadata": {"name": "Cinema"}},
        validation_summary={"valid": True, "errors": []},
    )
    published = GraphRevision.objects.create(
        definition=graph,
        schema_version=1,
        revision_number=2,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={"metadata": {"name": "Cinema"}, "nodes": []},
        validation_summary={"valid": True, "errors": []},
    )

    assert first.content_digest == published.content_digest
    assert len(first.content_digest) == 64
    assert first.published_at is None
    assert published.published_at is not None
    assert canonical_graph_json(first.content) == canonical_graph_json(published.content)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("content", {"nodes": [{"id": "changed"}]}),
        ("schema_version", 2),
        ("state", GraphRevisionState.PUBLISHED),
        ("validation_summary", {"valid": False}),
    ),
)
def test_revision_cannot_be_edited_in_place(graph_and_author, field, value) -> None:
    graph, author = graph_and_author
    revision = GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        author=author,
        content={"nodes": []},
    )
    setattr(revision, field, value)

    with pytest.raises(ValidationError, match="create a new revision"):
        revision.save()


def test_revision_number_is_unique_within_definition(graph_and_author) -> None:
    graph, author = graph_and_author
    GraphRevision.objects.create(
        definition=graph,
        revision_number=1,
        author=author,
        content={},
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        GraphRevision.objects.create(
            definition=graph,
            revision_number=1,
            author=author,
            content={"different": True},
        )


@pytest.mark.parametrize(
    ("content", "summary", "message"),
    (([], {}, "Graph content"), ({}, [], "Validation summary")),
)
def test_revision_json_envelopes_must_be_objects(
    graph_and_author,
    content,
    summary,
    message,
) -> None:
    graph, author = graph_and_author
    with pytest.raises(ValidationError, match=message):
        GraphRevision.objects.create(
            definition=graph,
            revision_number=1,
            author=author,
            content=content,
            validation_summary=summary,
        )
