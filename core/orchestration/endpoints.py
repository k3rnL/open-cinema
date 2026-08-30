from __future__ import annotations

from copy import copy

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from api.models.orchestration import LogicalEndpoint

EDITABLE_ENDPOINT_FIELDS = frozenset(
    {
        "name",
        "direction",
        "selector",
        "tags",
        "groups",
        "policy_metadata",
        "explicit_binding",
        "last_known_summary",
    }
)


class LogicalEndpointUpdateConflict(RuntimeError):
    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"expected endpoint version {expected_version}, "
            f"but current version is {actual_version}"
        )


def update_logical_endpoint(
    endpoint_id,
    *,
    actor,
    expected_version: int,
    **changes,
) -> LogicalEndpoint:
    """Validate and atomically update one endpoint using optimistic locking."""

    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise TypeError("expected_version must be an integer")
    if expected_version < 1:
        raise ValueError("expected_version must be positive")
    unknown = set(changes) - EDITABLE_ENDPOINT_FIELDS
    if unknown:
        raise ValueError(f"unsupported endpoint field(s): {', '.join(sorted(unknown))}")
    if not changes:
        raise ValueError("at least one endpoint field must be changed")

    with transaction.atomic():
        current = LogicalEndpoint.objects.select_for_update().get(pk=endpoint_id)
        if not current.can_change(actor):
            raise PermissionDenied(
                "Logical endpoints are editable only by their owner or staff."
            )
        managed_source = current.policy_metadata.get("managedSource") is True
        protected = {"direction", "selector", "explicit_binding", "policy_metadata"}
        if managed_source and protected.intersection(changes):
            raise PermissionDenied(
                "Managed-source identity and binding are controlled by the owning plugin."
            )
        if current.update_version != expected_version:
            raise LogicalEndpointUpdateConflict(
                expected_version=expected_version,
                actual_version=current.update_version,
            )

        candidate = copy(current)
        for field, value in changes.items():
            setattr(candidate, field, value)
        candidate.update_version = current.update_version + 1
        candidate.full_clean()
        now = timezone.now()
        updated = LogicalEndpoint.objects.filter(
            pk=current.pk,
            update_version=current.update_version,
        ).update(
            **changes,
            update_version=current.update_version + 1,
            updated_at=now,
        )
        if updated != 1:
            observed = LogicalEndpoint.objects.get(pk=current.pk)
            raise LogicalEndpointUpdateConflict(
                expected_version=expected_version,
                actual_version=observed.update_version,
            )
        return LogicalEndpoint.objects.get(pk=current.pk)
