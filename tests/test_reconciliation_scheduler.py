from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from core.orchestration.reconciliation_scheduler import (
    CoalescingReconciliationQueue,
    MutationScopeBusy,
    MutationScopeCoordinator,
    ReconciliationQueueClosed,
    ReconciliationWork,
)


def test_event_burst_coalesces_to_latest_generation_per_graph() -> None:
    queue = CoalescingReconciliationQueue(max_causes=4)

    for generation in range(1, 101):
        result = queue.submit(
            ReconciliationWork(
                "graph:main",
                generation,
                (f"runtime-event:{generation}",),
            )
        )

    assert result.coalesced is True
    assert result.replaced_generation == 99
    assert queue.pending_graphs == 1
    latest = queue.take(timeout=0)
    assert latest.generation == 100
    assert latest.causes == (
        "runtime-event:97",
        "runtime-event:98",
        "runtime-event:99",
        "runtime-event:100",
    )


def test_older_pending_generation_cannot_replace_newer_work() -> None:
    queue = CoalescingReconciliationQueue()
    newer = queue.submit(ReconciliationWork("graph:main", 7, ("newer",)))
    stale = queue.submit(ReconciliationWork("graph:main", 6, ("stale",)))

    assert newer.accepted is True
    assert stale.accepted is False
    assert queue.take(timeout=0).generation == 7


def test_distinct_graphs_remain_fairly_ordered() -> None:
    queue = CoalescingReconciliationQueue()
    queue.submit(ReconciliationWork("graph:first", 1, ("first",)))
    queue.submit(ReconciliationWork("graph:second", 1, ("second",)))
    queue.submit(ReconciliationWork("graph:first", 2, ("updated",)))

    assert queue.take(timeout=0).graph_scope == "graph:first"
    assert queue.take(timeout=0).graph_scope == "graph:second"


def test_queue_close_wakes_consumers_and_rejects_new_work() -> None:
    queue = CoalescingReconciliationQueue()
    queue.close()

    with pytest.raises(ReconciliationQueueClosed):
        queue.take(timeout=0)
    with pytest.raises(ReconciliationQueueClosed):
        queue.submit(ReconciliationWork("graph:main", 1, ("event",)))


def test_same_graph_mutations_are_serialized() -> None:
    coordinator = MutationScopeCoordinator()
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first():
        with coordinator.mutation("graph:main", ("endpoint:headset",)):
            first_entered.set()
            assert release_first.wait(timeout=1)

    def second():
        assert first_entered.wait(timeout=1)
        with coordinator.mutation("graph:main", ("endpoint:speakers",)):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first)
        second_future = executor.submit(second)
        assert first_entered.wait(timeout=1)
        assert second_entered.wait(timeout=0.05) is False
        release_first.set()
        first_future.result(timeout=1)
        second_future.result(timeout=1)

    assert second_entered.is_set()


def test_shared_resource_serializes_different_graphs_but_unrelated_scope_runs() -> None:
    coordinator = MutationScopeCoordinator()
    owner_entered = Event()
    release_owner = Event()
    shared_entered = Event()
    unrelated_entered = Event()

    def owner():
        with coordinator.mutation("graph:one", ("processor:camilladsp",)):
            owner_entered.set()
            assert release_owner.wait(timeout=1)

    def shared():
        with coordinator.mutation("graph:two", ("processor:camilladsp",)):
            shared_entered.set()

    def unrelated():
        with coordinator.mutation("graph:three", ("endpoint:headset",)):
            unrelated_entered.set()

    with ThreadPoolExecutor(max_workers=3) as executor:
        owner_future = executor.submit(owner)
        assert owner_entered.wait(timeout=1)
        shared_future = executor.submit(shared)
        unrelated_future = executor.submit(unrelated)
        assert unrelated_entered.wait(timeout=1)
        assert shared_entered.wait(timeout=0.05) is False
        release_owner.set()
        owner_future.result(timeout=1)
        shared_future.result(timeout=1)
        unrelated_future.result(timeout=1)


def test_read_only_diagnostic_runs_while_mutation_scope_is_held() -> None:
    coordinator = MutationScopeCoordinator()
    mutation_entered = Event()
    release_mutation = Event()

    def mutation():
        with coordinator.mutation("graph:main", ("processor:decoder",)):
            mutation_entered.set()
            assert release_mutation.wait(timeout=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(mutation)
        assert mutation_entered.wait(timeout=1)
        assert coordinator.run_diagnostic(lambda: "runtime snapshot") == "runtime snapshot"
        release_mutation.set()
        future.result(timeout=1)


def test_mutation_scope_has_bounded_wait() -> None:
    coordinator = MutationScopeCoordinator()
    with coordinator.mutation("graph:main"):
        with pytest.raises(MutationScopeBusy):
            with coordinator.mutation("graph:main", timeout=0):
                raise AssertionError("scope unexpectedly acquired")
