import json
from datetime import datetime, timezone

import pytest

from core.orchestration.redis_events import (
    OrchestrationRedisEventKind,
    OrchestrationRedisEventPublisher,
)


class FakeRedis:
    def __init__(self):
        self.entries = []
        self.expiries = []

    def xadd(self, key, fields, *, maxlen, approximate):
        self.entries.append((key, fields, maxlen, approximate))
        return f"{len(self.entries)}-0".encode()

    def expire(self, key, ttl):
        self.expiries.append((key, ttl))


def _publisher(client, *, max_bytes=1024):
    return OrchestrationRedisEventPublisher(
        client,
        stream_key="orchestration-events",
        max_entries=50,
        max_bytes=max_bytes,
        ttl_seconds=60,
        clock=lambda: datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("kind", tuple(OrchestrationRedisEventKind))
def test_every_ephemeral_event_kind_is_bounded_and_expiring(kind) -> None:
    redis = FakeRedis()

    result = _publisher(redis).publish(
        kind,
        {"state": "changed"},
        correlation_id="correlation:1",
        graph_definition_id="graph:main",
    )
    key, fields, maxlen, approximate = redis.entries[0]
    document = json.loads(fields["event"])

    assert result.delivered is True
    assert result.stream_id == "1-0"
    assert result.size_bytes <= 1024
    assert key == "orchestration-events"
    assert maxlen == 50
    assert approximate is True
    assert document["kind"] == kind.value
    assert document["payload"] == {"state": "changed"}
    assert redis.expiries == [("orchestration-events", 60)]


def test_oversized_event_is_rejected_before_redis_write() -> None:
    redis = FakeRedis()

    result = _publisher(redis, max_bytes=256).publish(
        "runtime",
        {"large": "x" * 512},
    )

    assert result.delivered is False
    assert result.reason == "event_exceeds_max_bytes"
    assert redis.entries == []


def test_redis_failure_does_not_escape_or_become_authoritative() -> None:
    class FailedRedis:
        def xadd(self, *_args, **_kwargs):
            raise ConnectionError("offline")

    publisher = _publisher(FailedRedis())

    result = publisher.publish("health", {"state": "degraded"})

    assert result.delivered is False
    assert result.reason == "redis_publish_failed"
    assert not hasattr(publisher, "load")
