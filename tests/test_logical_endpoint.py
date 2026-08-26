import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from api.models import LogicalEndpoint, LogicalEndpointDirection
from api.permissions import IsLogicalEndpointOwnerOrStaff
from core.orchestration.endpoints import (
    LogicalEndpointUpdateConflict,
    update_logical_endpoint,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def endpoint():
    owner = get_user_model().objects.create_user(username="endpoint-owner")
    endpoint = LogicalEndpoint.objects.create(
        name="Main speakers",
        owner=owner,
        direction=LogicalEndpointDirection.OUTPUT,
        selector={"device.serial": {"equals": "speaker-1"}},
        tags=["speaker", "preferred-output"],
        groups=["all-outputs", "room-outputs"],
        policy_metadata={"priority": 100},
        explicit_binding={"device.serial": "speaker-1"},
        last_known_summary={"availability": "unavailable"},
    )
    return endpoint


def test_endpoint_has_stable_identity_and_ordered_groups(endpoint) -> None:
    identity = endpoint.id
    endpoint.name = "Living room speakers"
    endpoint.save()
    endpoint.refresh_from_db()

    assert isinstance(identity, uuid.UUID)
    assert endpoint.id == identity
    assert endpoint.direction == LogicalEndpointDirection.OUTPUT
    assert endpoint.tags == ["speaker", "preferred-output"]
    assert endpoint.groups == ["all-outputs", "room-outputs"]
    assert endpoint.update_version == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("selector", [], "object"),
        ("tags", ["speaker", "speaker"], "unique"),
        ("groups", [""], "non-empty"),
        ("policy_metadata", [], "object"),
        ("explicit_binding", "runtime-id", "object or null"),
        ("last_known_summary", [], "object"),
    ),
)
def test_endpoint_envelopes_are_validated(endpoint, field, value, message) -> None:
    setattr(endpoint, field, value)
    with pytest.raises(ValidationError, match=message):
        endpoint.full_clean()


def test_optimistic_endpoint_update_is_atomic(endpoint) -> None:
    updated = update_logical_endpoint(
        endpoint.id,
        actor=endpoint.owner,
        expected_version=1,
        tags=["speaker", "headless"],
        groups=["preferred-outputs", "all-outputs"],
        last_known_summary={"availability": "route-available"},
    )

    assert updated.update_version == 2
    assert updated.tags == ["speaker", "headless"]
    assert updated.groups == ["preferred-outputs", "all-outputs"]
    assert updated.last_known_summary == {"availability": "route-available"}


def test_stale_endpoint_update_changes_nothing(endpoint) -> None:
    current = update_logical_endpoint(
        endpoint.id,
        actor=endpoint.owner,
        expected_version=1,
        name="Current name",
    )

    with pytest.raises(LogicalEndpointUpdateConflict) as error:
        update_logical_endpoint(
            endpoint.id,
            actor=endpoint.owner,
            expected_version=1,
            name="Stale name",
        )

    current.refresh_from_db()
    assert error.value.actual_version == 2
    assert current.name == "Current name"
    assert current.update_version == 2


def test_endpoint_update_requires_owner_or_staff(endpoint) -> None:
    user_model = get_user_model()
    other = user_model.objects.create_user(username="endpoint-other")
    staff = user_model.objects.create_user(username="endpoint-staff", is_staff=True)

    with pytest.raises(PermissionDenied, match="owner or staff"):
        update_logical_endpoint(
            endpoint.id,
            actor=other,
            expected_version=1,
            tags=["unauthorized"],
        )
    endpoint.refresh_from_db()
    assert endpoint.tags == ["speaker", "preferred-output"]
    assert endpoint.update_version == 1

    updated = update_logical_endpoint(
        endpoint.id,
        actor=staff,
        expected_version=1,
        tags=["speaker", "staff-reviewed"],
    )
    assert updated.tags == ["speaker", "staff-reviewed"]
    assert updated.update_version == 2


@pytest.mark.parametrize("method", ("get", "patch", "delete"))
def test_endpoint_api_permission_is_owner_scoped(endpoint, method) -> None:
    other = get_user_model().objects.create_user(username=f"permission-other-{method}")
    staff = get_user_model().objects.create_user(
        username=f"permission-staff-{method}", is_staff=True
    )
    permission = IsLogicalEndpointOwnerOrStaff()
    factory = APIRequestFactory()

    for user, expected in (
        (endpoint.owner, True),
        (staff, True),
        (other, False),
        (AnonymousUser(), False),
    ):
        request = getattr(factory, method)("/api/audio/v1/endpoints/example")
        request.user = user
        assert permission.has_permission(request, None) is bool(user.is_authenticated)
        assert permission.has_object_permission(request, None, endpoint) is expected
