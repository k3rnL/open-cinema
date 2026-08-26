from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from api.models import RuntimeProjection

DEFAULT_RUNTIME_DIRECTORY = Path("/run/open-cinema")
DEFAULT_DURATION_MS = 2000
DEFAULT_RATE = 48000


class SpeakerTestError(RuntimeError):
    pass


class SpeakerTestUnavailable(SpeakerTestError):
    pass


class SpeakerTestInvalidChannel(SpeakerTestError):
    pass


@dataclass(frozen=True, slots=True)
class SpeakerTestOutput:
    runtime_key: str
    generation: int
    name: str
    description: str
    target_name: str
    channels: tuple[str, ...]
    rate: int

    def to_document(self) -> dict[str, object]:
        return {
            "runtimeKey": self.runtime_key,
            "runtimeGeneration": self.generation,
            "name": self.name,
            "description": self.description,
            "targetName": self.target_name,
            "channels": [
                {"position": position, "label": speaker_channel_label(position)}
                for position in self.channels
            ],
            "rate": self.rate,
        }


_CHANNEL_LABELS = {
    "FL": "Front left",
    "FR": "Front right",
    "FC": "Front center",
    "LFE": "Subwoofer",
    "RL": "Rear left",
    "RR": "Rear right",
    "SL": "Side left",
    "SR": "Side right",
    "FLC": "Front left of center",
    "FRC": "Front right of center",
    "RC": "Rear center",
    "MONO": "Mono",
}


def speaker_channel_label(position: str) -> str:
    if position in _CHANNEL_LABELS:
        return _CHANNEL_LABELS[position]
    if position.startswith("AUX") and position[3:].isdigit():
        return f"Auxiliary {int(position[3:]) + 1}"
    return position.replace("_", " ").title()


def _known_value(value: object) -> object | None:
    if not isinstance(value, Mapping) or not value.get("known", False):
        return None
    return value.get("value")


def _physical_input_channels(payload: Mapping[str, object]) -> set[str]:
    channels: set[str] = set()
    ports = payload.get("ports")
    if not isinstance(ports, list):
        return channels
    for port in ports:
        if not isinstance(port, Mapping) or port.get("direction") != "input":
            continue
        properties = port.get("properties")
        if not isinstance(properties, Mapping):
            continue
        physical = properties.get("port.physical")
        if physical not in (True, "true", "1", 1):
            continue
        channel = port.get("channel")
        if isinstance(channel, str) and channel:
            channels.add(channel)
    return channels


def output_from_projection(projection: RuntimeProjection) -> SpeakerTestOutput | None:
    payload = projection.payload
    if not projection.is_current or not isinstance(payload, Mapping):
        return None
    if (
        payload.get("direction") != "output"
        or payload.get("mediaClass") != "Audio/Sink"
        or payload.get("origin") != "runtime-device"
        or payload.get("managed") is True
        or payload.get("error")
    ):
        return None
    runtime_key = payload.get("runtimeKey")
    target_name = payload.get("name")
    if not isinstance(runtime_key, str) or not isinstance(target_name, str) or not target_name:
        return None
    physical_channels = _physical_input_channels(payload)
    if not physical_channels:
        return None
    capabilities = payload.get("audioCapabilities")
    formats = capabilities.get("formats") if isinstance(capabilities, Mapping) else None
    if not isinstance(formats, list):
        return None
    for audio_format in formats:
        if not isinstance(audio_format, Mapping) or audio_format.get("content") != "pcm":
            continue
        positions = _known_value(audio_format.get("positions"))
        channel_count = _known_value(audio_format.get("channels"))
        rate = _known_value(audio_format.get("rate"))
        if (
            not isinstance(positions, list)
            or not positions
            or not all(isinstance(item, str) and item for item in positions)
            or len(set(positions)) != len(positions)
            or not isinstance(channel_count, int)
            or channel_count != len(positions)
            or not set(positions).issubset(physical_channels)
        ):
            continue
        return SpeakerTestOutput(
            runtime_key=runtime_key,
            generation=projection.world_generation,
            name=str(payload.get("description") or target_name),
            description=(
                str(payload.get("device", {}).get("description") or "Physical audio output")
                if isinstance(payload.get("device"), Mapping)
                else "Physical audio output"
            ),
            target_name=target_name,
            channels=tuple(positions),
            rate=rate if isinstance(rate, int) and 8000 <= rate <= 384000 else DEFAULT_RATE,
        )
    return None


def discover_speaker_test_outputs() -> tuple[SpeakerTestOutput, ...]:
    outputs = []
    seen = set()
    projections = RuntimeProjection.objects.filter(
        is_current=True,
        projection_type__in=("endpoint", "endpoint-candidate"),
    ).order_by("subject_key")
    for projection in projections:
        output = output_from_projection(projection)
        if output is not None and output.runtime_key not in seen:
            outputs.append(output)
            seen.add(output.runtime_key)
    return tuple(outputs)


def build_speaker_test_command(
    output: SpeakerTestOutput,
    channel: str,
    token: str,
    *,
    duration_ms: int = DEFAULT_DURATION_MS,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "core.orchestration.speaker_test_worker",
        "--target",
        output.target_name,
        "--channel-map",
        ",".join(output.channels),
        "--channel",
        channel,
        "--rate",
        str(output.rate),
        "--duration-ms",
        str(duration_ms),
        "--token",
        token,
    ]


class SpeakerTestController:
    def __init__(
        self,
        runtime_directory: Path = DEFAULT_RUNTIME_DIRECTORY,
        *,
        duration_ms: int = DEFAULT_DURATION_MS,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        startup_probe_seconds: float = 0.08,
    ) -> None:
        self.runtime_directory = Path(runtime_directory)
        self.duration_ms = duration_ms
        self._popen = popen
        self._startup_probe_seconds = startup_probe_seconds
        self._lock_path = self.runtime_directory / "speaker-test.lock"
        self._state_path = self.runtime_directory / "speaker-test.json"

    @contextmanager
    def _locked(self):
        self.runtime_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with os.fdopen(descriptor, "r+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                yield
        finally:
            pass

    def _read_state(self) -> dict[str, object] | None:
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def _write_state(self, state: dict[str, object]) -> None:
        temporary = self._state_path.with_suffix(f".{state['token']}.tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._state_path)

    def _remove_state(self) -> None:
        self._state_path.unlink(missing_ok=True)

    @staticmethod
    def _process_start_ticks(pid: int) -> int | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            tail = stat[stat.rfind(")") + 2 :].split()
            return int(tail[19])
        except (FileNotFoundError, IndexError, OSError, ValueError):
            return None

    @classmethod
    def _verified_process(cls, state: Mapping[str, object]) -> bool:
        pid = state.get("pid")
        start_ticks = state.get("processStartTicks")
        token = state.get("token")
        if (
            not isinstance(pid, int)
            or not isinstance(start_ticks, int)
            or not isinstance(token, str)
        ):
            return False
        if cls._process_start_ticks(pid) != start_ticks:
            return False
        try:
            arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, OSError):
            return False
        decoded = [item.decode("utf-8", "replace") for item in arguments if item]
        return "core.orchestration.speaker_test_worker" in decoded and token in decoded

    def _stop_locked(self) -> None:
        state = self._read_state()
        if state is None:
            self._remove_state()
            return
        if self._verified_process(state):
            pid = int(state["pid"])
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 0.6
            while self._verified_process(state) and time.monotonic() < deadline:
                time.sleep(0.02)
            if self._verified_process(state):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._remove_state()

    @staticmethod
    def _state_document(state: Mapping[str, object] | None) -> dict[str, object]:
        if state is None:
            return {
                "active": False,
                "token": None,
                "runtimeKey": None,
                "outputName": None,
                "channel": None,
                "startedAt": None,
                "endsAt": None,
                "durationMs": None,
            }
        return {
            key: state.get(key)
            for key in (
                "active",
                "token",
                "runtimeKey",
                "outputName",
                "channel",
                "startedAt",
                "endsAt",
                "durationMs",
            )
        }

    def status(self) -> dict[str, object]:
        with self._locked():
            state = self._read_state()
            if state is None or not self._verified_process(state):
                self._remove_state()
                state = None
            return self._state_document(state)

    def stop(self) -> dict[str, object]:
        with self._locked():
            self._stop_locked()
            return self._state_document(None)

    def start(self, output: SpeakerTestOutput, channel: str) -> dict[str, object]:
        if channel not in output.channels:
            raise SpeakerTestInvalidChannel(
                f"Channel {channel!r} is not declared by {output.name}."
            )
        with self._locked():
            self._stop_locked()
            token = str(uuid.uuid4())
            command = build_speaker_test_command(
                output,
                channel,
                token,
                duration_ms=self.duration_ms,
            )
            environment = os.environ.copy()
            environment.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            environment.setdefault(
                "DBUS_SESSION_BUS_ADDRESS",
                f"unix:path={environment['XDG_RUNTIME_DIR']}/bus",
            )
            environment.setdefault("PIPEWIRE_REMOTE", "pipewire-0")
            process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
            if self._startup_probe_seconds:
                time.sleep(self._startup_probe_seconds)
            if process.poll() is not None:
                raise SpeakerTestUnavailable(
                    "The PipeWire speaker-test stream could not be started."
                )
            start_ticks = self._process_start_ticks(process.pid)
            if start_ticks is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                raise SpeakerTestUnavailable("The speaker-test helper did not remain active.")
            started = datetime.now(UTC)
            state: dict[str, object] = {
                "active": True,
                "token": token,
                "pid": process.pid,
                "processStartTicks": start_ticks,
                "runtimeKey": output.runtime_key,
                "outputName": output.name,
                "channel": channel,
                "startedAt": started.isoformat(),
                "endsAt": (started + timedelta(milliseconds=self.duration_ms)).isoformat(),
                "durationMs": self.duration_ms,
            }
            self._write_state(state)
            threading.Thread(
                target=self._reap,
                args=(process, token),
                name=f"speaker-test-{token}",
                daemon=True,
            ).start()
            return self._state_document(state)

    def _reap(self, process: subprocess.Popen, token: str) -> None:
        process.wait()
        with self._locked():
            state = self._read_state()
            if state is not None and state.get("token") == token:
                self._remove_state()
