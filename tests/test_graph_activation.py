import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from api.models import (
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.activations import (
    GraphActivationConflict,
    activate_graph,
    deactivate_graph,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def activation_revisions():
    author = get_user_model().objects.create_user(username="activation-author")
    graph = GraphDefinition.objects.create(name="Activated graph", owner=author)
    revisions = tuple(
        GraphRevision.objects.create(
            definition=graph,
            revision_number=number,
            state=GraphRevisionState.PUBLISHED,
            author=author,
            content={"revision": number},
            validation_summary={"valid": True},
        )
        for number in (1, 2)
    )
    return author, graph, revisions


def test_activation_create_and_atomic_replace_increment_desired_version(
    activation_revisions,
) -> None:
    _, graph, (first, second) = activation_revisions
    created = activate_graph(
        definition=graph,
        revision=first,
        expected_version=0,
        parameter_bindings={"volume": 0.8},
        scene_bindings={"mode": "cinema"},
    )
    updated = activate_graph(
        definition=graph,
        revision=second,
        expected_version=1,
        parameter_bindings={"volume": 0.6},
        scene_bindings={"mode": "night"},
    )

    assert updated.pk == created.pk
    assert updated.revision == second
    assert updated.enabled is True
    assert updated.desired_state_version == 2
    assert updated.parameter_bindings == {"volume": 0.6}
    assert updated.scene_bindings == {"mode": "night"}
    assert updated.activated_at >= created.activated_at


def test_stale_activation_update_changes_nothing(activation_revisions) -> None:
    _, graph, (first, second) = activation_revisions
    current = activate_graph(
        definition=graph,
        revision=first,
        expected_version=0,
    )

    with pytest.raises(GraphActivationConflict) as error:
        activate_graph(
            definition=graph,
            revision=second,
            expected_version=0,
            parameter_bindings={"stale": True},
        )

    current.refresh_from_db()
    assert error.value.actual_version == 1
    assert current.revision == first
    assert current.desired_state_version == 1
    assert current.parameter_bindings == {}


def test_activation_rejects_draft_or_foreign_revision(activation_revisions) -> None:
    author, graph, _ = activation_revisions
    draft = GraphRevision.objects.create(
        definition=graph,
        revision_number=3,
        author=author,
        content={},
    )
    other = GraphDefinition.objects.create(name="Other graph", owner=author)
    foreign = GraphRevision.objects.create(
        definition=other,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={},
    )

    with pytest.raises(ValidationError, match="published"):
        activate_graph(
            definition=graph,
            revision=draft,
            expected_version=0,
        )
    with pytest.raises(ValidationError, match="another graph"):
        activate_graph(
            definition=graph,
            revision=foreign,
            expected_version=0,
        )
    assert not hasattr(graph, "activation")


def test_subgraphs_cannot_be_activated() -> None:
    author = get_user_model().objects.create_user(username="subgraph-author")
    subgraph = GraphDefinition.objects.create(
        name="Reusable processing",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=author,
    )
    revision = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=author,
        content={},
    )

    with pytest.raises(ValidationError, match="top-level"):
        activate_graph(
            definition=subgraph,
            revision=revision,
            expected_version=0,
        )


def test_successful_activation_schedules_wakeup_only_after_commit(
    activation_revisions,
    django_capture_on_commit_callbacks,
    monkeypatch,
) -> None:
    _, graph, (revision, _) = activation_revisions
    wakeups = []
    monkeypatch.setattr(
        "core.orchestration.activations._publish_activation_wakeup",
        lambda definition_id, version: wakeups.append((definition_id, version)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        activation = activate_graph(
            definition=graph,
            revision=revision,
            expected_version=0,
        )
        assert wakeups == []

    assert wakeups == [(activation.definition_id, 1)]


def test_deactivation_is_versioned_idempotent_and_reactivatable(
    activation_revisions,
) -> None:
    _, graph, (first, second) = activation_revisions
    activation = activate_graph(
        definition=graph,
        revision=first,
        expected_version=0,
        parameter_bindings={"volume": 0.8},
    )

    disabled = deactivate_graph(definition=graph, expected_version=1)
    repeated = deactivate_graph(definition=graph, expected_version=2)

    assert disabled is not None
    assert disabled.pk == activation.pk
    assert disabled.enabled is False
    assert disabled.revision == first
    assert disabled.desired_state_version == 2
    assert disabled.parameter_bindings == {}
    assert repeated is not None
    assert repeated.desired_state_version == 2

    reactivated = activate_graph(
        definition=graph,
        revision=second,
        expected_version=2,
    )
    assert reactivated.pk == activation.pk
    assert reactivated.enabled is True
    assert reactivated.revision == second
    assert reactivated.desired_state_version == 3


def test_stale_deactivation_preserves_current_activation(activation_revisions) -> None:
    _, graph, (revision, _) = activation_revisions
    activation = activate_graph(
        definition=graph,
        revision=revision,
        expected_version=0,
    )

    with pytest.raises(GraphActivationConflict) as error:
        deactivate_graph(definition=graph, expected_version=0)

    activation.refresh_from_db()
    assert error.value.actual_version == 1
    assert activation.enabled is True
    assert activation.desired_state_version == 1
