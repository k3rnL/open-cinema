from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from wyreplumber.runtime import freeze_json, thaw_json

logger = logging.getLogger(__name__)


class OrchestrationRedisEventKind(StrEnum):
    RUNTIME = "runtime"
    PLAN = "plan"
    PROGRESS = "progress"
    PROCESSOR = "processor"
    HEALTH = "health"


@dataclass(frozen=True, slots=True)
class RedisEventPublishResult:
    delivered: bool
    stream_id: str | None
    event_id: uuid.UUID
    size_bytes: int
    reason: str


class OrchestrationRedisEventPublisher:
    """Write bounded, expiring event hints without becoming a state store."""

    def __init__(
        self,
        client,
        *,
        stream_key: str,
        max_entries: int,
        max_bytes: int,
        ttl_seconds: int,
        clock=None,
    ) -> None:
        if not isinstance(stream_key, str) or not stream_key:
            raise ValueError("stream_key must be a non-empty string")
        for name, value, minimum in (
            ("max_entries", max_entries, 1),
            ("max_bytes", max_bytes, 256),
            ("ttl_seconds", ttl_seconds, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        self.client = client
        self.stream_key = stream_key
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(
        self,
        kind: OrchestrationRedisEventKind,
        payload,
        *,
        correlation_id=None,
        graph_definition_id=None,
    ) -> RedisEventPublishResult:
        kind = OrchestrationRedisEventKind(kind)
        frozen_payload = freeze_json(payload)
        event_id = uuid.uuid4()
        envelope = {
            "schemaVersion": 1,
            "eventId": str(event_id),
            "kind": kind.value,
            "occurredAt": self.clock().astimezone(timezone.utc).isoformat(),
            "correlationId": str(correlation_id) if correlation_id is not None else None,
            "graphDefinitionId": (
                str(graph_definition_id) if graph_definition_id is not None else None
            ),
            "payload": thaw_json(frozen_payload),
        }
        encoded = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > self.max_bytes:
            return RedisEventPublishResult(
                False,
                None,
                event_id,
                len(encoded),
                "event_exceeds_max_bytes",
            )
        try:
            stream_id = self.client.xadd(
                self.stream_key,
                {"event": encoded},
                maxlen=self.max_entries,
                approximate=True,
            )
            self.client.expire(self.stream_key, self.ttl_seconds)
        except Exception as error:  # The database/in-memory state remains authoritative.
            logger.warning("Ephemeral orchestration event was not published: %s", error)
            return RedisEventPublishResult(
                False,
                None,
                event_id,
                len(encoded),
                "redis_publish_failed",
            )
        if isinstance(stream_id, bytes):
            stream_id = stream_id.decode("ascii")
        return RedisEventPublishResult(
            True,
            str(stream_id),
            event_id,
            len(encoded),
            "redis_event_published",
        )
