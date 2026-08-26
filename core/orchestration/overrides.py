from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from api.models.orchestration import ManualOverride


def cancel_manual_override(override_id, *, actor, at=None) -> ManualOverride:
    """Idempotently cancel an override while retaining its audit record."""

    with transaction.atomic():
        override = ManualOverride.objects.select_for_update().get(pk=override_id)
        if not (
            getattr(actor, "is_authenticated", False)
            and (actor.pk == override.creator_id or actor.is_staff or actor.is_superuser)
        ):
            raise PermissionDenied("Only the override creator or staff may cancel it.")
        if override.cancelled_at is not None:
            return override
        override.cancelled_at = at or timezone.now()
        override.cancelled_by = actor
        override.full_clean()
        override.save(update_fields=("cancelled_at", "cancelled_by"))
        return override
