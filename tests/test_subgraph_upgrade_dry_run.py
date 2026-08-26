import copy

import pytest
from django.contrib.auth import get_user_model

from api.models import (
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.subgraph_upgrades import dry_run_subgraph_upgrade
from tests.test_subgraph_expansion import (
    _instance,
    _parent_document,
    _subgraph_document,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def upgrade_revisions():
    owner = get_user_model().objects.create_user(username="subgraph-upgrade")
    subgraph = GraphDefinition.objects.create(
        name="Upgradeable filter",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=owner,
    )
    previous = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=_subgraph_document(),
    )
    compatible_content = copy.deepcopy(previous.content)
    compatible_content["id"] = "graph:filter-v2"
    compatible_content["metadata"]["description"] = "Implementation-only update"
    compatible = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=2,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=compatible_content,
    )
    incompatible_content = copy.deepcopy(compatible_content)
    incompatible_content["id"] = "graph:filter-v3"
    incompatible_content["publicPorts"] = [incompatible_content["publicPorts"][0]]
    incompatible = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=3,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=incompatible_content,
    )
    draft = GraphRevision.objects.create(
        definition=subgraph,
        revision_number=4,
        state=GraphRevisionState.DRAFT,
        author=owner,
        content=compatible_content,
    )
    parent = GraphDefinition.objects.create(name="Upgrade parent", owner=owner)
    instance = _instance(
        "node:filter",
        subgraph.pk,
        previous.pk,
        {"value": 0.5},
    )
    parent_revision = GraphRevision.objects.create(
        definition=parent,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=_parent_document([instance]),
    )
    return previous, compatible, incompatible, draft, parent_revision


def test_compatible_upgrade_validates_parent_without_changing_pin(
    upgrade_revisions,
) -> None:
    previous, candidate, _, _, parent_revision = upgrade_revisions
    original = copy.deepcopy(parent_revision.content)

    result = dry_run_subgraph_upgrade(
        previous_revision=previous,
        candidate_revision=candidate,
    )

    assert result.valid is True, result.parents[0].issues
    assert len(result.parents) == 1
    assert result.parents[0].valid is True
    assert result.parents[0].expanded_digest
    assert result.parents[0].proposed_document["nodes"][1]["subgraph"][
        "revisionId"
    ] == str(candidate.pk)
    parent_revision.refresh_from_db()
    assert parent_revision.content == original
    assert parent_revision.content["nodes"][1]["subgraph"]["revisionId"] == str(
        previous.pk
    )


def test_incompatible_upgrade_reports_broken_parent_route(upgrade_revisions) -> None:
    previous, _, candidate, _, _ = upgrade_revisions

    result = dry_run_subgraph_upgrade(
        previous_revision=previous,
        candidate_revision=candidate,
    )

    assert result.valid is False
    assert result.comparison.compatible is False
    assert result.parents[0].valid is False
    assert "missing_subgraph_port_binding" in {
        issue.code for issue in result.parents[0].issues
    }


def test_dry_run_rejects_mutable_candidate(upgrade_revisions) -> None:
    previous, _, _, draft, _ = upgrade_revisions

    with pytest.raises(ValueError, match="candidate.*published"):
        dry_run_subgraph_upgrade(
            previous_revision=previous,
            candidate_revision=draft,
        )
