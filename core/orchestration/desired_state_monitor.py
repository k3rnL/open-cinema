from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic

from wyreplumber.runtime import FrozenDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DesiredStateSnapshot:
    version: int
    digest: str
    activations: FrozenDict


@dataclass(frozen=True, slots=True)
class DesiredStatePollResult:
    changed: bool
    snapshot: DesiredStateSnapshot
    changed_activation_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DesiredStateWakeupResult:
    delivered: bool
    subscriber_count: int
    reason: str


def _database_activation_documents() -> tuple[dict[str, object], ...]:
    from api.models import EndpointAudioLevel, GraphActivation, MasterAudioLevel

    master = (
        MasterAudioLevel.objects.filter(pk=1).values("level", "muted", "update_version").first()
    )
    endpoints = list(
        EndpointAudioLevel.objects.order_by("endpoint_id").values(
            "endpoint_id", "level", "muted", "update_version"
        )
    )
    audio_levels = {
        "master": (
            {
                "level": master["level"],
                "muted": master["muted"],
                "updateVersion": master["update_version"],
            }
            if master is not None
            else None
        ),
        "endpoints": [
            {
                "endpointId": str(item["endpoint_id"]),
                "level": item["level"],
                "muted": item["muted"],
                "updateVersion": item["update_version"],
            }
            for item in endpoints
        ],
    }

    values = GraphActivation.objects.order_by("id").values(
        "id",
        "definition_id",
        "revision_id",
        "enabled",
        "desired_state_version",
        "updated_at",
    )
    return tuple(
        {
            "activationId": str(value["id"]),
            "definitionId": str(value["definition_id"]),
            "revisionId": str(value["revision_id"]) if value["enabled"] else None,
            "enabled": value["enabled"],
            "desiredStateVersion": value["desired_state_version"],
            "updatedAt": value["updated_at"].isoformat(),
            "audioLevels": audio_levels,
        }
        for value in values
    )


class DesiredStateMonitor:
    """Poll the authoritative database for every active desired-state version."""

    def __init__(
        self,
        query: Callable[[], Sequence[Mapping[str, object]]] = _database_activation_documents,
    ) -> None:
        self.query = query
        self.current: DesiredStateSnapshot | None = None

    @staticmethod
    def _canonical_activations(
        documents: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        activations = {}
        for document in documents:
            activation_id = document.get("activationId")
            if not isinstance(activation_id, str) or not activation_id:
                raise ValueError("activationId must be a non-empty string")
            if activation_id in activations:
                raise ValueError(f"duplicate activationId {activation_id!r}")
            version = document.get("desiredStateVersion")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("desiredStateVersion must be a positive integer")
            activations[activation_id] = dict(document)
        return dict(sorted(activations.items()))

    def poll(self) -> DesiredStatePollResult:
        activations = self._canonical_activations(tuple(self.query()))
        encoded = json.dumps(
            activations,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        previous = self.current
        if previous is not None and previous.digest == digest:
            return DesiredStatePollResult(False, previous, (), ())

        previous_activations = previous.activations.to_dict() if previous is not None else {}
        changed_ids = tuple(
            sorted(
                activation_id
                for activation_id in set(previous_activations) | set(activations)
                if previous_activations.get(activation_id) != activations.get(activation_id)
            )
        )
        reasons = []
        for activation_id in changed_ids:
            before = previous_activations.get(activation_id)
            after = activations.get(activation_id)
            if before is None:
                reasons.append("activation_added")
            elif after is None:
                reasons.append("activation_removed")
            elif after["desiredStateVersion"] < before["desiredStateVersion"]:
                reasons.append("desired_state_version_regressed")
            elif after.get("audioLevels") != before.get("audioLevels"):
                reasons.append("audio_level_intent_changed")
            else:
                reasons.append("desired_state_version_advanced")
        snapshot = DesiredStateSnapshot(
            version=(previous.version + 1 if previous is not None else 1),
            digest=digest,
            activations=FrozenDict(activations),
        )
        self.current = snapshot
        return DesiredStatePollResult(
            True,
            snapshot,
            changed_ids,
            tuple(sorted(set(reasons))),
        )


class RedisDesiredStateWakeupListener:
    """Lossy Pub/Sub hint; callers must still poll DesiredStateMonitor."""

    def __init__(self, client, channel: str) -> None:
        if not isinstance(channel, str) or not channel:
            raise ValueError("desired-state wake-up channel must be non-empty")
        self.channel = channel
        self.pubsub = client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(channel)

    def poll(self) -> bool:
        message = self.pubsub.get_message(timeout=0)
        return bool(message and message.get("type") == "message")

    def close(self) -> None:
        self.pubsub.close()


class DesiredStateCoordinator:
    """Use wake-ups for latency and periodic polling for correctness."""

    def __init__(
        self,
        monitor: DesiredStateMonitor,
        *,
        poll_seconds: float,
        wakeup_listener: RedisDesiredStateWakeupListener | None = None,
        wakeup_listener_factory=None,
        clock=monotonic,
    ) -> None:
        if not isinstance(monitor, DesiredStateMonitor):
            raise TypeError("monitor must be a DesiredStateMonitor")
        if (
            isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, (int, float))
            or poll_seconds <= 0
        ):
            raise ValueError("poll_seconds must be a positive number")
        self.monitor = monitor
        self.poll_seconds = float(poll_seconds)
        self.wakeup_listener = wakeup_listener
        self.wakeup_listener_factory = wakeup_listener_factory
        self.wakeup_healthy = wakeup_listener is not None
        self.last_wakeup_error: str | None = None
        self.clock = clock
        self.last_poll_at: float | None = None

    def step(self, *, force: bool = False) -> DesiredStatePollResult | None:
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")
        now = self.clock()
        if self.wakeup_listener is None and self.wakeup_listener_factory is not None:
            try:
                self.wakeup_listener = self.wakeup_listener_factory()
                self.wakeup_healthy = True
                self.last_wakeup_error = None
            except Exception as error:
                self.wakeup_healthy = False
                self.last_wakeup_error = str(error)
        try:
            woken = self.wakeup_listener.poll() if self.wakeup_listener is not None else False
            if self.wakeup_listener is not None:
                self.wakeup_healthy = True
                self.last_wakeup_error = None
        except Exception as error:
            self.wakeup_healthy = False
            self.last_wakeup_error = str(error)
            try:
                self.wakeup_listener.close()
            finally:
                self.wakeup_listener = None
            woken = False
        due = force or self.last_poll_at is None or now - self.last_poll_at >= self.poll_seconds
        if not woken and not due:
            return None
        result = self.monitor.poll()
        self.last_poll_at = now
        return result

    def close(self) -> None:
        if self.wakeup_listener is not None:
            try:
                self.wakeup_listener.close()
            finally:
                self.wakeup_listener = None


def publish_desired_state_wakeup(
    *,
    definition_id: str,
    desired_state_version: int,
) -> DesiredStateWakeupResult:
    """Best-effort notification after commit; database polling remains authoritative."""

    from django.conf import settings

    if not settings.AUDIO_ORCHESTRATION_FEATURES["runtime_observation"]:
        return DesiredStateWakeupResult(False, 0, "runtime_observation_disabled")
    from redis import Redis

    projection = settings.AUDIO_RUNTIME_REDIS_PROJECTION
    channel = settings.AUDIO_DESIRED_STATE_MONITOR["channel"]
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "definitionId": str(definition_id),
            "desiredStateVersion": desired_state_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        subscribers = int(Redis.from_url(projection["url"]).publish(channel, payload))
    except Exception as error:  # Redis wake-ups are explicitly lossy.
        logger.warning("Desired-state Redis wake-up was lost: %s", error)
        return DesiredStateWakeupResult(False, 0, "redis_publish_failed")
    return DesiredStateWakeupResult(True, subscribers, "redis_wakeup_published")


def publish_adapter_state_wakeup(
    *,
    adapter_id: str,
    update_version: int,
) -> DesiredStateWakeupResult:
    """Best-effort hint for adapter desired-state changes."""

    from django.conf import settings

    if not settings.AUDIO_ORCHESTRATION_FEATURES["runtime_observation"]:
        return DesiredStateWakeupResult(False, 0, "runtime_observation_disabled")
    from redis import Redis

    projection = settings.AUDIO_RUNTIME_REDIS_PROJECTION
    channel = settings.AUDIO_DESIRED_STATE_MONITOR["channel"]
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "resource": "audio-adapter",
            "adapterId": str(adapter_id),
            "updateVersion": update_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        subscribers = int(Redis.from_url(projection["url"]).publish(channel, payload))
    except Exception as error:
        logger.warning("Adapter desired-state Redis wake-up was lost: %s", error)
        return DesiredStateWakeupResult(False, 0, "redis_publish_failed")
    return DesiredStateWakeupResult(True, subscribers, "redis_wakeup_published")


def publish_audio_level_wakeup(*, scope_id: str, update_version: int) -> DesiredStateWakeupResult:
    """Best-effort hint; the desired-state digest remains authoritative."""

    from django.conf import settings

    if not settings.AUDIO_ORCHESTRATION_FEATURES["runtime_observation"]:
        return DesiredStateWakeupResult(False, 0, "runtime_observation_disabled")
    from redis import Redis

    projection = settings.AUDIO_RUNTIME_REDIS_PROJECTION
    channel = settings.AUDIO_DESIRED_STATE_MONITOR["channel"]
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "resource": "audio-level",
            "scopeId": scope_id,
            "updateVersion": update_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        subscribers = int(Redis.from_url(projection["url"]).publish(channel, payload))
    except Exception as error:
        logger.warning("Audio-level desired-state wake-up was lost: %s", error)
        return DesiredStateWakeupResult(False, 0, "redis_publish_failed")
    return DesiredStateWakeupResult(True, subscribers, "redis_wakeup_published")
