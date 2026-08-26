import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.orchestration.resolver_replay import (
    RESOLVER_REPLAY_FORMAT,
    ResolverReplayError,
    ResolverReplayMismatch,
    create_resolver_replay_bundle,
    replay_resolver_bundle,
    resolver_inputs_from_document,
    resolver_inputs_to_document,
)
from tests.test_resolver_pipeline import _registry, _resolver_inputs

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "orchestration" / "resolver_replay_pipeline.json"
)


def test_resolver_inputs_round_trip_through_detached_json() -> None:
    inputs = _resolver_inputs()

    encoded = json.loads(json.dumps(resolver_inputs_to_document(inputs)))
    restored = resolver_inputs_from_document(encoded)

    assert resolver_inputs_to_document(restored) == resolver_inputs_to_document(inputs)


def test_created_bundle_contains_minimal_reproduction_sections() -> None:
    bundle = create_resolver_replay_bundle(_resolver_inputs(), registry=_registry())

    assert bundle["format"] == RESOLVER_REPLAY_FORMAT
    assert set(bundle) == {
        "format",
        "schemaVersion",
        "versions",
        "desired",
        "world",
        "policies",
        "outputPlan",
    }
    assert bundle["desired"]["graphRevision"]["document"]["id"] == "graph:pipeline"
    assert bundle["world"]["version"]["token"] == "3:9:1:1:1:1:1"
    assert bundle["policies"]["resourcePolicy"]["resources"][0]["kind"] == ("decoder")
    assert len(bundle["outputPlan"]["digest"]) == 64


def test_recorded_bundle_replays_to_exact_expected_plan() -> None:
    bundle = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    replay = replay_resolver_bundle(bundle, registry=_registry())

    assert replay.matches_expected is True
    assert replay.expected_digest == replay.plan.digest
    assert replay.inputs.world_version.token == bundle["versions"]["world"]


def test_replay_detects_expected_output_drift() -> None:
    bundle = create_resolver_replay_bundle(_resolver_inputs(), registry=_registry())
    changed = deepcopy(bundle)
    changed["outputPlan"]["digest"] = "0" * 64

    with pytest.raises(ResolverReplayMismatch, match="does not match"):
        replay_resolver_bundle(changed, registry=_registry())

    diagnostic = replay_resolver_bundle(
        changed,
        registry=_registry(),
        verify_expected=False,
    )
    assert diagnostic.matches_expected is False


@pytest.mark.parametrize(
    "change",
    (
        {"format": "unknown"},
        {"schemaVersion": 99},
    ),
)
def test_replay_rejects_unsupported_bundle_envelopes(change) -> None:
    bundle = create_resolver_replay_bundle(_resolver_inputs(), registry=_registry())
    bundle.update(change)

    with pytest.raises(ResolverReplayError):
        replay_resolver_bundle(bundle, registry=_registry())
