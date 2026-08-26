from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from api.models import ManualOverride, ManualOverrideScope
from core.orchestration.overrides import cancel_manual_override


pytestmark = pytest.mark.django_db


@pytest.fixture
def override_users():
    users = get_user_model()
    return (
        users.objects.create_user(username="override-creator"),
        users.objects.create_user(username="override-other"),
        users.objects.create_user(username="override-staff", is_staff=True),
    )


def test_override_active_window_and_query(override_users) -> None:
    creator, _, _ = override_users
    now = timezone.now()
    override = ManualOverride.objects.create(
        scope_type=ManualOverrideScope.ENDPOINT,
        scope_id="primary-output",
        value="headset",
        priority=200,
        creator=creator,
        reason="Use the headset for this film",
        starts_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert not override.is_active(now - timedelta(seconds=1))
    assert override.is_active(now)
    assert not override.is_active(now + timedelta(hours=1))
    assert list(ManualOverride.objects.active_at(now)) == [override]


@pytest.mark.parametrize(
    ("scope", "value", "message"),
    (
        (ManualOverrideScope.MUTE, "yes", "boolean"),
        (ManualOverrideScope.VOLUME, 1.1, "between 0 and 1"),
        (ManualOverrideScope.ENDPOINT, "", "non-empty string"),
        (ManualOverrideScope.GRAPH_PARAMETER, {}, "containing 'value'"),
    ),
)
def test_override_value_is_validated_by_scope(
    override_users,
    scope,
    value,
    message,
) -> None:
    creator, _, _ = override_users
    override = ManualOverride(
        scope_type=scope,
        scope_id="test-scope",
        value=value,
        creator=creator,
        reason="test invalid value",
    )
    with pytest.raises(ValidationError, match=message):
        override.full_clean()


def test_override_expiry_must_follow_start(override_users) -> None:
    creator, _, _ = override_users
    now = timezone.now()
    override = ManualOverride(
        scope_type=ManualOverrideScope.MUTE,
        scope_id="main-speakers",
        value=True,
        creator=creator,
        reason="quiet",
        starts_at=now,
        expires_at=now,
    )
    with pytest.raises(ValidationError, match="after the override start"):
        override.full_clean()


def test_cancel_is_authorized_audited_and_idempotent(override_users) -> None:
    creator, other, staff = override_users
    override = ManualOverride.objects.create(
        scope_type=ManualOverrideScope.SCENE,
        scope_id="active-scene",
        value="night",
        creator=creator,
        reason="Children are asleep",
    )

    with pytest.raises(PermissionDenied):
        cancel_manual_override(override.id, actor=other)
    cancelled = cancel_manual_override(override.id, actor=staff)
    cancelled_again = cancel_manual_override(override.id, actor=creator)

    assert cancelled.cancelled_by == staff
    assert cancelled.cancelled_at is not None
    assert not cancelled.is_active()
    assert cancelled_again.cancelled_at == cancelled.cancelled_at
    assert cancelled_again.cancelled_by == staff
