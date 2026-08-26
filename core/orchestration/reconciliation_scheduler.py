from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition, Lock, RLock
from time import monotonic

from django.conf import settings


def _scope(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ReconciliationWork:
    graph_scope: str
    generation: int
    causes: tuple[str, ...]

    def __post_init__(self) -> None:
        _scope(self.graph_scope, field="graph_scope")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
        ):
            raise ValueError("generation must be a positive integer")
        causes = tuple(dict.fromkeys(self.causes))
        if not causes or any(not isinstance(cause, str) or not cause for cause in causes):
            raise ValueError("causes must contain non-empty strings")
        object.__setattr__(self, "causes", causes)


@dataclass(frozen=True, slots=True)
class ReconciliationSubmitResult:
    accepted: bool
    coalesced: bool
    replaced_generation: int | None
    pending_graphs: int
    work: ReconciliationWork


class ReconciliationQueueClosed(RuntimeError):
    pass


class CoalescingReconciliationQueue:
    """Keep only the newest pending generation for each graph scope."""

    def __init__(
        self,
        *,
        max_pending_graphs: int | None = None,
        max_causes: int | None = None,
    ) -> None:
        configured = settings.AUDIO_RECONCILIATION_QUEUE_LIMITS
        expected = {"max_pending_graphs", "max_causes"}
        if not isinstance(configured, dict) or set(configured) != expected:
            raise ValueError(
                "AUDIO_RECONCILIATION_QUEUE_LIMITS must define exactly "
                f"{', '.join(sorted(expected))}"
            )
        max_pending_graphs = (
            configured["max_pending_graphs"]
            if max_pending_graphs is None
            else max_pending_graphs
        )
        max_causes = configured["max_causes"] if max_causes is None else max_causes
        for field, value in (
            ("max_pending_graphs", max_pending_graphs),
            ("max_causes", max_causes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field} must be a positive integer")
        self.max_pending_graphs = max_pending_graphs
        self.max_causes = max_causes
        self._condition = Condition(RLock())
        self._pending: dict[str, ReconciliationWork] = {}
        self._order = deque()
        self._closed = False

    @property
    def pending_graphs(self) -> int:
        with self._condition:
            return len(self._pending)

    def submit(self, work: ReconciliationWork) -> ReconciliationSubmitResult:
        if not isinstance(work, ReconciliationWork):
            raise TypeError("work must be ReconciliationWork")
        with self._condition:
            if self._closed:
                raise ReconciliationQueueClosed("reconciliation queue is closed")
            previous = self._pending.get(work.graph_scope)
            if previous is not None and work.generation < previous.generation:
                return ReconciliationSubmitResult(
                    accepted=False,
                    coalesced=False,
                    replaced_generation=None,
                    pending_graphs=len(self._pending),
                    work=previous,
                )
            causes = tuple(
                dict.fromkeys((previous.causes if previous is not None else ()) + work.causes)
            )[-self.max_causes :]
            merged = ReconciliationWork(
                graph_scope=work.graph_scope,
                generation=max(
                    work.generation,
                    previous.generation if previous is not None else work.generation,
                ),
                causes=causes,
            )
            if previous is None:
                if len(self._pending) >= self.max_pending_graphs:
                    raise OverflowError("reconciliation queue reached max_pending_graphs")
                self._order.append(work.graph_scope)
            self._pending[work.graph_scope] = merged
            self._condition.notify()
            return ReconciliationSubmitResult(
                accepted=True,
                coalesced=previous is not None,
                replaced_generation=(
                    previous.generation
                    if previous is not None and merged.generation > previous.generation
                    else None
                ),
                pending_graphs=len(self._pending),
                work=merged,
            )

    def take(self, *, timeout: float | None = None) -> ReconciliationWork:
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0
        ):
            raise ValueError("timeout must be a non-negative number or null")
        deadline = monotonic() + float(timeout) if timeout is not None else None
        with self._condition:
            while not self._order:
                if self._closed:
                    raise ReconciliationQueueClosed("reconciliation queue is closed")
                remaining = None if deadline is None else max(0.0, deadline - monotonic())
                if remaining == 0:
                    raise TimeoutError("no reconciliation work became available")
                self._condition.wait(timeout=remaining)
            graph_scope = self._order.popleft()
            return self._pending.pop(graph_scope)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class MutationScopeBusy(TimeoutError):
    def __init__(self, scopes: tuple[str, ...]) -> None:
        self.scopes = scopes
        super().__init__(f"timed out acquiring mutation scopes: {', '.join(scopes)}")


class MutationScopeCoordinator:
    """Serialize graph/resource mutations without blocking read-only diagnostics."""

    def __init__(self) -> None:
        self._guard = RLock()
        self._locks: dict[str, Lock] = {}

    def _lock(self, key: str) -> Lock:
        with self._guard:
            return self._locks.setdefault(key, Lock())

    @staticmethod
    def _keys(graph_scope: str, resource_scopes: Iterable[str]) -> tuple[str, ...]:
        graph_scope = _scope(graph_scope, field="graph_scope")
        resources = tuple(resource_scopes)
        if any(not isinstance(resource, str) or not resource for resource in resources):
            raise ValueError("resource_scopes must contain non-empty strings")
        return tuple(
            sorted({f"graph:{graph_scope}"} | {f"resource:{resource}" for resource in resources})
        )

    @contextmanager
    def mutation(
        self,
        graph_scope: str,
        resource_scopes: Iterable[str] = (),
        *,
        timeout: float | None = None,
    ):
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0
        ):
            raise ValueError("timeout must be a non-negative number or null")
        keys = self._keys(graph_scope, resource_scopes)
        deadline = monotonic() + float(timeout) if timeout is not None else None
        acquired = []
        try:
            for key in keys:
                lock = self._lock(key)
                if deadline is None:
                    locked = lock.acquire()
                else:
                    locked = lock.acquire(timeout=max(0.0, deadline - monotonic()))
                if not locked:
                    raise MutationScopeBusy(keys)
                acquired.append(lock)
            yield keys
        finally:
            for lock in reversed(acquired):
                lock.release()

    @staticmethod
    def run_diagnostic(function: Callable, /, *args, **kwargs):
        """Diagnostics deliberately take no mutation scope and remain independent."""

        if not callable(function):
            raise TypeError("diagnostic function must be callable")
        return function(*args, **kwargs)
