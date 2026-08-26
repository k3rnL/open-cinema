from datetime import datetime, timezone

from core.orchestration.orchestrator_lifecycle import (
    BoundedReconnectBackoff,
    DependencyHealth,
    OrchestratorLifecycle,
    OrchestratorLifecycleState,
)


def test_required_dependencies_control_readiness_but_redis_is_optional() -> None:
    lifecycle = OrchestratorLifecycle(clock=lambda: datetime(2026, 8, 22, tzinfo=timezone.utc))

    assert lifecycle.snapshot.live is True
    assert lifecycle.snapshot.ready is False

    lifecycle.dependency("database", DependencyHealth.READY)
    lifecycle.dependency("pipewire", DependencyHealth.READY)
    lifecycle.dependency("wireplumber", DependencyHealth.READY)
    healthy = lifecycle.dependency(
        "redis",
        DependencyHealth.UNAVAILABLE,
        reason="connection refused",
    )

    assert healthy.state is OrchestratorLifecycleState.DEGRADED
    assert healthy.live is True
    assert healthy.ready is True
    assert healthy.last_success_at == "2026-08-22T00:00:00+00:00"

    unavailable = lifecycle.dependency(
        "database",
        DependencyHealth.UNAVAILABLE,
        reason="database restarting",
    )

    assert unavailable.state is OrchestratorLifecycleState.DEGRADED
    assert unavailable.live is True
    assert unavailable.ready is False


def test_reconnecting_and_shutdown_have_explicit_health_states() -> None:
    lifecycle = OrchestratorLifecycle()

    reconnecting = lifecycle.reconnecting(
        "wireplumber",
        reason="event queue closed",
        next_retry_seconds=0.5,
    )

    assert reconnecting.state is OrchestratorLifecycleState.RECONNECTING
    assert reconnecting.live is True
    assert reconnecting.ready is False
    assert reconnecting.next_retry_seconds == 0.5
    assert reconnecting.last_failure["dependency"] == "wireplumber"
    assert lifecycle.stopping().live is True
    stopped = lifecycle.stopped()
    assert stopped.state is OrchestratorLifecycleState.STOPPED
    assert stopped.live is False
    assert stopped.ready is False


def test_reconnect_backoff_is_bounded_jittered_and_resettable() -> None:
    backoff = BoundedReconnectBackoff(
        initial_seconds=0.25,
        max_seconds=2,
        multiplier=2,
        jitter_ratio=0.5,
        random_value=lambda: 0.5,
    )

    assert [backoff.next_delay() for _ in range(5)] == [0.25, 0.5, 1.0, 2.0, 2.0]
    backoff.reset()
    assert backoff.next_delay() == 0.25
