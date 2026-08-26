from __future__ import annotations

import fcntl
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from wyreplumber.runtime import FrozenDict


class ControllerLockState(StrEnum):
    ACTIVE = "active"
    STANDBY = "standby"
    FAILED = "failed"
    RELEASED = "released"


@dataclass(frozen=True, slots=True)
class ControllerLockStatus:
    state: ControllerLockState
    path: str
    owner: FrozenDict
    reason: str

    def to_document(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "path": self.path,
            "owner": self.owner.to_dict(),
            "reason": self.reason,
        }


class ControllerLockError(RuntimeError):
    def __init__(self, status: ControllerLockStatus):
        super().__init__(status.reason)
        self.status = status


class ControllerLock:
    """Non-blocking inter-process lock for the one live orchestration controller."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._file = None
        self.status = ControllerLockStatus(
            ControllerLockState.RELEASED,
            str(self.path),
            FrozenDict(),
            "controller_lock_not_held",
        )

    @staticmethod
    def _owner_document() -> dict[str, object]:
        return {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "process": "open-cinema-orchestrator",
            "acquiredAt": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _read_owner(file_object) -> FrozenDict:
        try:
            file_object.seek(0)
            document = json.loads(file_object.read() or "{}")
            return FrozenDict(document if isinstance(document, dict) else {})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return FrozenDict()

    def acquire(self) -> ControllerLockStatus:
        if self._file is not None:
            raise RuntimeError("controller lock is already held by this object")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_object = self.path.open("a+", encoding="utf-8")
        except OSError as error:
            self.status = ControllerLockStatus(
                ControllerLockState.FAILED,
                str(self.path),
                FrozenDict(),
                f"controller_lock_open_failed: {error}",
            )
            raise ControllerLockError(self.status) from error
        try:
            fcntl.flock(file_object.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            owner = self._read_owner(file_object)
            file_object.close()
            self.status = ControllerLockStatus(
                ControllerLockState.STANDBY,
                str(self.path),
                owner,
                "another_open_cinema_orchestrator_is_active",
            )
            return self.status
        except OSError as error:
            file_object.close()
            self.status = ControllerLockStatus(
                ControllerLockState.FAILED,
                str(self.path),
                FrozenDict(),
                f"controller_lock_acquire_failed: {error}",
            )
            raise ControllerLockError(self.status) from error

        owner = self._owner_document()
        file_object.seek(0)
        file_object.truncate()
        json.dump(owner, file_object, sort_keys=True, separators=(",", ":"))
        file_object.flush()
        self._file = file_object
        self.status = ControllerLockStatus(
            ControllerLockState.ACTIVE,
            str(self.path),
            FrozenDict(owner),
            "controller_lock_acquired",
        )
        return self.status

    def release(self) -> ControllerLockStatus:
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
        self.status = ControllerLockStatus(
            ControllerLockState.RELEASED,
            str(self.path),
            FrozenDict(),
            "controller_lock_released",
        )
        return self.status

    def __enter__(self) -> ControllerLock:
        status = self.acquire()
        if status.state is not ControllerLockState.ACTIVE:
            raise ControllerLockError(status)
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()
