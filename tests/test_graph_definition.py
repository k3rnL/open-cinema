import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIRequestFactory

from api.models import GraphDefinition, GraphDefinitionKind
from api.permissions import IsGraphDefinitionOwnerOrStaff


pytestmark = pytest.mark.django_db


@pytest.fixture
def users():
    user_model = get_user_model()
    return {
        "owner": user_model.objects.create_user(username="graph-owner"),
        "other": user_model.objects.create_user(username="other-user"),
        "staff": user_model.objects.create_user(username="staff-user", is_staff=True),
    }


def test_graph_definition_has_stable_identity_and_lifecycle(users) -> None:
    graph = GraphDefinition.objects.create(
        name="Living room",
        kind=GraphDefinitionKind.GRAPH,
        owner=users["owner"],
        labels={"room": "living-room", "purpose": "cinema"},
    )
    identity = graph.id
    created_at = graph.created_at
    graph.name = "Living room cinema"
    graph.save()
    graph.refresh_from_db()

    assert isinstance(identity, uuid.UUID)
    assert graph.id == identity
    assert graph.kind == GraphDefinitionKind.GRAPH
    assert graph.created_at == created_at
    assert graph.updated_at >= created_at
    assert graph.archived_at is None


def test_owner_scoped_name_and_label_validation(users) -> None:
    GraphDefinition.objects.create(name="Reusable", owner=users["owner"])
    GraphDefinition.objects.create(name="Reusable", owner=users["other"])

    with pytest.raises(IntegrityError), transaction.atomic():
        GraphDefinition.objects.create(name="Reusable", owner=users["owner"])

    invalid = GraphDefinition(
        name="Invalid labels",
        owner=users["owner"],
        labels={"priority": 1},
    )
    with pytest.raises(ValidationError, match="must all be strings"):
        invalid.full_clean()


def test_visibility_is_owner_scoped_with_staff_access(users) -> None:
    own = GraphDefinition.objects.create(name="Owned", owner=users["owner"])
    other = GraphDefinition.objects.create(name="Other", owner=users["other"])

    assert list(GraphDefinition.objects.visible_to(users["owner"])) == [own]
    assert set(GraphDefinition.objects.visible_to(users["staff"])) == {own, other}
    assert not GraphDefinition.objects.visible_to(AnonymousUser()).exists()


@pytest.mark.parametrize("method", ("get", "patch", "delete"))
def test_api_object_permission_allows_owner_and_staff(users, method) -> None:
    graph = GraphDefinition.objects.create(name="Private", owner=users["owner"])
    permission = IsGraphDefinitionOwnerOrStaff()
    factory = APIRequestFactory()

    for user, expected in (
        (users["owner"], True),
        (users["staff"], True),
        (users["other"], False),
        (AnonymousUser(), False),
    ):
        request = getattr(factory, method)("/api/audio/v1/graphs/example")
        request.user = user
        assert permission.has_permission(request, None) is bool(user.is_authenticated)
        assert permission.has_object_permission(request, None, graph) is expected
