import json
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from core.orchestration.action_retry import ActionRetryPolicy
from core.orchestration.condition_validation import validate_condition_document
from core.orchestration.driver_actions import (
    ActionAssertionOperator,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)
from core.orchestration.graph_validation import validate_graph_structure
from core.orchestration.orchestrator_service import OrchestratorService
from core.orchestration.reconciliation_scheduler import (
    CoalescingReconciliationQueue,
    ReconciliationWork,
)

FIXTURE = Path(__file__).parent / "fixtures" / "orchestration" / "canonical" / "desired_graph.json"


def _action(timeout_seconds: float) -> DriverAction:
    return DriverAction.create(
        identity=DriverActionIdentity(
            "bounded-driver",
            "processor",
            "processor:test",
            "prepare",
        ),
        command=DriverCommand("prepare", {}),
        intent_scope="safety-bounds-test",
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                "processor.test.ready",
                ActionAssertionOperator.EQUALS,
                True,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.NONE_REQUIRED,
            "The test action has no side effects.",
        ),
    )


def test_local_defaults_are_conservative_and_finite() -> None:
    assert settings.AUDIO_GRAPH_VALIDATION_LIMITS == {
        "max_nodes": 256,
        "max_edges": 1024,
        "max_path_depth": 64,
        "max_document_bytes": 1_048_576,
    }
    assert settings.AUDIO_SUBGRAPH_MAX_DEPTH == 8
    assert settings.AUDIO_CONDITION_VALIDATION_LIMITS["max_depth"] == 16
    assert settings.AUDIO_REDIS_EVENT_STREAM["max_entries"] == 2_000
    assert settings.AUDIO_RUNTIME_REDIS_PROJECTION["max_bytes"] == 262_144
    assert settings.AUDIO_RUNTIME_REDIS_PROJECTION["max_endpoints"] == 256
    assert settings.AUDIO_ORCHESTRATION_RETENTION["diagnostic_hours"] == 24
    assert settings.AUDIO_ACTION_EXECUTION_LIMITS == {
        "max_timeout_seconds": 30.0,
        "max_attempts": 5,
        "max_retry_delay_seconds": 30.0,
    }
    assert settings.AUDIO_RECONCILIATION_CATCHUP == {
        "max_passes": 8,
        "retry_initial_seconds": 0.1,
        "retry_max_seconds": 2.0,
        "retry_multiplier": 2.0,
    }


@override_settings(
    AUDIO_RECONCILIATION_CATCHUP={
        "max_passes": 0,
        "retry_initial_seconds": 0.1,
        "retry_max_seconds": 2.0,
        "retry_multiplier": 2.0,
    }
)
def test_reconciliation_catchup_pass_limit_is_validated() -> None:
    with pytest.raises(ValueError, match="between 1 and 64"):
        OrchestratorService()


@override_settings(
    AUDIO_GRAPH_VALIDATION_LIMITS={
        "max_nodes": 32,
        "max_edges": 64,
        "max_path_depth": 16,
        "max_document_bytes": 1_048_576,
    }
)
def test_graph_validation_stops_an_oversized_local_stress_document() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))["graph"]
    template = document["nodes"][0]
    document["nodes"] = [{**template, "id": f"stress-node:{index}"} for index in range(2_000)]
    document["edges"] = []

    result = validate_graph_structure(document)

    assert result.node_count == 2_000
    assert any(issue.code == "node_limit_exceeded" for issue in result.issues)


@override_settings(
    AUDIO_CONDITION_VALIDATION_LIMITS={
        "max_depth": 3,
        "max_nodes": 8,
        "max_group_arguments": 4,
        "max_membership_values": 4,
        "max_document_bytes": 1_024,
    }
)
def test_condition_depth_is_configurable_and_walk_is_bounded() -> None:
    expression = {"op": "exists", "fact": "mode.cinema"}
    for _ in range(100):
        expression = {"op": "not", "arg": expression}

    result = validate_condition_document({"version": 1, "expression": expression})

    assert result.maximum_depth == 4
    assert any(issue.code == "depth_limit_exceeded" for issue in result.issues)


@override_settings(
    AUDIO_RECONCILIATION_QUEUE_LIMITS={
        "max_pending_graphs": 2,
        "max_causes": 3,
    }
)
def test_event_burst_is_coalesced_and_distinct_graph_queue_is_bounded() -> None:
    queue = CoalescingReconciliationQueue()
    for generation in range(1, 10_001):
        queue.submit(ReconciliationWork("graph:one", generation, (str(generation),)))
    queue.submit(ReconciliationWork("graph:two", 1, ("first",)))

    with pytest.raises(OverflowError, match="max_pending_graphs"):
        queue.submit(ReconciliationWork("graph:three", 1, ("first",)))

    latest = queue.take(timeout=0)
    assert latest.generation == 10_000
    assert latest.causes == ("9998", "9999", "10000")


@override_settings(
    AUDIO_ACTION_EXECUTION_LIMITS={
        "max_timeout_seconds": 2.0,
        "max_attempts": 2,
        "max_retry_delay_seconds": 1.0,
    }
)
def test_action_timeout_attempts_and_retry_delay_have_global_ceilings() -> None:
    assert _action(2).timeout_seconds == 2
    with pytest.raises(ValueError, match="max_timeout_seconds"):
        _action(2.01)
    with pytest.raises(ValueError, match="max_attempts"):
        ActionRetryPolicy(3, 0.1, 1)
    with pytest.raises(ValueError, match="retry delay maximum"):
        ActionRetryPolicy(2, 0.1, 1.01)
