import json
from threading import Event

import pytest

from core.orchestration.controller_lock import (
    ControllerLock,
    ControllerLockError,
    ControllerLockState,
)
from core.orchestration.orchestrator_service import OrchestratorService


def test_only_one_controller_holds_the_deployment_lock(tmp_path) -> None:
    path = tmp_path / "orchestrator.lock"
    active = ControllerLock(path)
    contender = ControllerLock(path)

    active_status = active.acquire()
    standby_status = contender.acquire()

    assert active_status.state is ControllerLockState.ACTIVE
    assert active_status.owner["process"] == "open-cinema-orchestrator"
    assert standby_status.state is ControllerLockState.STANDBY
    assert standby_status.owner == active_status.owner
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == (active_status.owner["pid"])

    active.release()
    promoted = contender.acquire()
    assert promoted.state is ControllerLockState.ACTIVE
    contender.release()


def test_lock_open_failure_has_distinct_failed_diagnostic(tmp_path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied", encoding="utf-8")
    lock = ControllerLock(parent_file / "orchestrator.lock")

    with pytest.raises(ControllerLockError) as caught:
        lock.acquire()

    assert caught.value.status.state is ControllerLockState.FAILED
    assert caught.value.status.reason.startswith("controller_lock_open_failed")


def test_service_reports_active_then_released_controller_state(tmp_path) -> None:
    stop_event = Event()

    class OneShotService(OrchestratorService):
        active_status = None

        def run_active_controller(self, received_stop_event):
            self.active_status = self.controller_status
            received_stop_event.set()

    service = OneShotService(
        lock_path=str(tmp_path / "orchestrator.lock"),
        lock_retry_seconds=0.01,
    )

    service.run(stop_event)

    assert service.active_status.state is ControllerLockState.ACTIVE
    assert service.controller_status.state is ControllerLockState.RELEASED
