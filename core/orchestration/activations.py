from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from api.models.orchestration import GraphActivation


class GraphActivationConflict(RuntimeError):
    """The caller attempted to replace a newer desired-state selection."""

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"expected desired-state version {expected_version}, "
            f"but current version is {actual_version}"
        )


def _publish_activation_wakeup(definition_id, desired_state_version) -> None:
    from .desired_state_monitor import publish_desired_state_wakeup

    publish_desired_state_wakeup(
        definition_id=str(definition_id),
        desired_state_version=desired_state_version,
    )


def activate_graph(
    *,
    definition,
    revision,
    expected_version: int,
    parameter_bindings: dict[str, object] | None = None,
    scene_bindings: dict[str, object] | None = None,
) -> GraphActivation:
    """Atomically create or replace one graph activation with compare-and-swap."""

    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise TypeError("expected_version must be an integer")
    if expected_version < 0:
        raise ValueError("expected_version must not be negative")
    parameter_bindings = dict(parameter_bindings or {})
    scene_bindings = dict(scene_bindings or {})
    now = timezone.now()

    with transaction.atomic():
        current = GraphActivation.objects.select_for_update().filter(definition=definition).first()
        actual_version = 0 if current is None else current.desired_state_version
        if expected_version != actual_version:
            raise GraphActivationConflict(
                expected_version=expected_version,
                actual_version=actual_version,
            )

        next_version = actual_version + 1
        candidate = GraphActivation(
            definition_id=definition.pk,
            revision_id=revision.pk,
            enabled=True,
            parameter_bindings=parameter_bindings,
            scene_bindings=scene_bindings,
            desired_state_version=next_version,
            activated_at=now,
        )
        candidate.full_clean(validate_unique=False, validate_constraints=False)

        if current is None:
            try:
                with transaction.atomic():
                    candidate.save(force_insert=True)
            except IntegrityError as error:
                observed = (
                    GraphActivation.objects.filter(definition=definition)
                    .values_list("desired_state_version", flat=True)
                    .first()
                )
                raise GraphActivationConflict(
                    expected_version=expected_version,
                    actual_version=observed or 0,
                ) from error
            transaction.on_commit(
                lambda: _publish_activation_wakeup(
                    candidate.definition_id,
                    candidate.desired_state_version,
                )
            )
            return candidate

        updated = GraphActivation.objects.filter(
            pk=current.pk,
            desired_state_version=actual_version,
        ).update(
            revision=revision,
            enabled=True,
            parameter_bindings=parameter_bindings,
            scene_bindings=scene_bindings,
            desired_state_version=next_version,
            activated_at=now,
            updated_at=now,
        )
        if updated != 1:
            observed = GraphActivation.objects.get(pk=current.pk)
            raise GraphActivationConflict(
                expected_version=expected_version,
                actual_version=observed.desired_state_version,
            )
        activation = GraphActivation.objects.get(pk=current.pk)
        transaction.on_commit(
            lambda: _publish_activation_wakeup(
                activation.definition_id,
                activation.desired_state_version,
            )
        )
        return activation


def deactivate_graph(
    *,
    definition,
    expected_version: int,
) -> GraphActivation | None:
    """Atomically disable one graph activation without deleting saved state."""

    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise TypeError("expected_version must be an integer")
    if expected_version < 0:
        raise ValueError("expected_version must not be negative")
    now = timezone.now()

    with transaction.atomic():
        current = GraphActivation.objects.select_for_update().filter(definition=definition).first()
        actual_version = 0 if current is None else current.desired_state_version
        if expected_version != actual_version:
            raise GraphActivationConflict(
                expected_version=expected_version,
                actual_version=actual_version,
            )
        if current is None or not current.enabled:
            return current

        next_version = actual_version + 1
        updated = GraphActivation.objects.filter(
            pk=current.pk,
            desired_state_version=actual_version,
            enabled=True,
        ).update(
            enabled=False,
            parameter_bindings={},
            scene_bindings={},
            desired_state_version=next_version,
            updated_at=now,
        )
        if updated != 1:
            observed = GraphActivation.objects.get(pk=current.pk)
            raise GraphActivationConflict(
                expected_version=expected_version,
                actual_version=observed.desired_state_version,
            )
        activation = GraphActivation.objects.get(pk=current.pk)
        transaction.on_commit(
            lambda: _publish_activation_wakeup(
                activation.definition_id,
                activation.desired_state_version,
            )
        )
        return activation
