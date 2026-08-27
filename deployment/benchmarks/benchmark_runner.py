#!/usr/bin/env python3
"""Manifest-driven benchmark runner for the Open Cinema Raspberry Pi fixture.

Raw evidence remains private on the appliance.  ``finalize`` creates a redacted,
checksummed export and deliberately keeps characterization distinct from
acceptance.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform as python_platform
from queue import Empty, SimpleQueue
import re
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
import uuid

from jsonschema import Draft202012Validator, FormatChecker
import yaml

_BENCHMARK_MODULE_ROOT = Path(__file__).resolve().parent
if str(_BENCHMARK_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCHMARK_MODULE_ROOT))

from benchmark_workload_driver import (  # noqa: E402
    BenchmarkWorkloadDriver,
    CamillaDSPConfigurationRejected,
)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
HARDWARE_ADDRESS_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
    r"|(?<![0-9a-f])(?:[0-9a-f]{2}_){5}[0-9a-f]{2}(?![0-9a-f])"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(r"(?i)((?:token|password|secret)\s*[=:]\s*)([^\s,;]+)")
SECRET_KEY_PATTERN = re.compile(r"(?i)(token|password|secret|credential|authorization)")
IMPLEMENTATION_COMPONENTS = (
    "benchmarkRunner",
    "intentAdapter",
    "workloadDriver",
)
CONTRACT_FILES = (
    "fixtures.yml",
    "cases.yml",
    "criteria-policy.yml",
    "fixture.schema.json",
    "cases.schema.json",
    "evidence-envelope.schema.json",
)
WORKLOAD_REGISTRY_FILES = (
    "media/manifest.json",
    "media/camilladsp/profiles.json",
    "media/physical-path.yml",
)

RUNTIME_SERVICES = (
    "open-cinema-orchestrator.service",
    "camilladsp@camilladsp-0.service",
    "pcm-auto-decoder@decoder-0.service",
    "pipewire.service",
    "wireplumber.service",
)
USER_SERVICES = frozenset(("pipewire.service", "wireplumber.service"))
INTENT_TABLES = (
    "api_graphdefinition",
    "api_graphrevision",
    "api_graphactivation",
    "api_logicalendpoint",
    "api_camilladspprofile",
    "api_managedaudioadapter",
    "api_manualoverride",
)
COUNT_TABLES = (
    "api_resolvedplan",
    "api_orchestrationevent",
    "api_diagnosticrecord",
    "api_runtimeprojection",
    "api_transitionjournal",
)
DEFAULT_STATIC_PATHS = (
    "/etc/open-cinema",
    "/etc/systemd/system/open-cinema-orchestrator.service",
    "/etc/systemd/system/camilladsp@.service",
    "/etc/systemd/system/pcm-auto-decoder@.service",
    "/etc/systemd/user/pipewire.service.d",
    "/etc/systemd/user/wireplumber.service.d",
    "/etc/wireplumber/wireplumber.conf.d",
)


class BenchmarkError(RuntimeError):
    """Base class for bounded runner failures."""


class ContractError(BenchmarkError):
    """The checked-in benchmark contracts are inconsistent."""


class CaseTimeout(BenchmarkError):
    """A case exceeded its predeclared timeout."""


class RestorationError(BenchmarkError):
    """The appliance did not return to its saved state."""


class InterruptedCase(BenchmarkError):
    """A case received SIGINT or SIGTERM."""


@dataclass
class _PlaybackProcess:
    feeder: subprocess.Popen[bytes]
    player: subprocess.Popen[bytes]
    logs: tuple[Any, ...]
    evidence: dict[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def boottime_ns() -> int:
    clock = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)
    return time.clock_gettime_ns(clock)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest_document(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str, *, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o640)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain an object")
    return value


def validate_json(instance: object, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ContractError(f"{schema_path.name}: {rendered}")


def redact_string(value: str) -> str:
    value = HARDWARE_ADDRESS_PATTERN.sub("[redacted]", value)
    return SECRET_ASSIGNMENT_PATTERN.sub(r"\1[redacted]", value)


def redact_document(value: object, *, key: str = "") -> object:
    if SECRET_KEY_PATTERN.search(key):
        return "[redacted]"
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, list):
        return [redact_document(item) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): redact_document(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    return value


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile for an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def summary_statistics(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("cannot summarize an empty sample")
    return {
        "count": len(values),
        "median": statistics.median(values),
        "p95NearestRank": percentile_nearest_rank(values, 0.95),
        "maximum": max(values),
    }


def checked_identifier(value: str, *, case: bool = False) -> str:
    pattern = CASE_ID_PATTERN if case else RUN_ID_PATTERN
    if not pattern.fullmatch(value):
        kind = "case" if case else "run"
        raise BenchmarkError(f"invalid {kind} identifier: {value!r}")
    return value


@dataclass(frozen=True)
class Contracts:
    root: Path
    fixture: dict[str, Any]
    cases: dict[str, Any]
    criteria: dict[str, Any]
    evidence_schema_path: Path

    @classmethod
    def load(cls, root: Path) -> "Contracts":
        fixture = load_yaml(root / "fixtures.yml")
        cases = load_yaml(root / "cases.yml")
        criteria = load_yaml(root / "criteria-policy.yml")
        validate_json(fixture, root / "fixture.schema.json")
        validate_json(cases, root / "cases.schema.json")
        if cases["fixture_contract_id"] != fixture["fixture_contract_id"]:
            raise ContractError("case and fixture identifiers differ")
        if cases["suite_id"] != fixture["suite_id"]:
            raise ContractError("case and fixture suite identifiers differ")
        if cases["criteria_policy_id"] != criteria["criteria_policy_id"]:
            raise ContractError("case and criteria policy identifiers differ")
        identifiers = [item["id"] for item in cases["cases"]]
        if len(identifiers) != len(set(identifiers)):
            raise ContractError("case identifiers must be unique")
        restoration_actions = cases["restoration_actions"]
        for declared in cases["cases"]:
            case = {**cases["defaults"], **declared}
            action = restoration_actions[case["restoration_action"]]
            allowed = set(action.get("allowed_services", []))
            service_sets = [case.get("disruptive_services", [])]
            service_sets.extend(case.get("service_matrix", []))
            for service_set in service_sets:
                outside_boundary = set(service_set) - allowed
                if outside_boundary:
                    raise ContractError(
                        f"case {case['id']} injects services outside its restoration action: "
                        f"{sorted(outside_boundary)}"
                    )
                unknown = set(service_set) - set(RUNTIME_SERVICES)
                if unknown:
                    raise ContractError(
                        f"case {case['id']} names unknown runtime services: {sorted(unknown)}"
                    )
        return cls(root, fixture, cases, criteria, root / "evidence-envelope.schema.json")

    def case(self, case_id: str) -> dict[str, Any]:
        checked_identifier(case_id, case=True)
        for declared in self.cases["cases"]:
            if declared["id"] == case_id:
                return {**self.cases["defaults"], **declared}
        raise ContractError(f"unknown benchmark case: {case_id}")

    def selected_cases(
        self, case_ids: Sequence[str] = (), campaign: str | None = None
    ) -> list[dict[str, Any]]:
        selected = [self.case(case_id) for case_id in case_ids]
        if campaign is not None:
            selected.extend(
                {**self.cases["defaults"], **item}
                for item in self.cases["cases"]
                if item["campaign"] == campaign
            )
        if not case_ids and campaign is None:
            selected = [{**self.cases["defaults"], **item} for item in self.cases["cases"]]
        unique = {item["id"]: item for item in selected}
        if not unique:
            raise ContractError("the selection contains no benchmark cases")
        return [unique[key] for key in sorted(unique)]

    def fixture_available(self, case: Mapping[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if case.get("execution_mode") == "manual":
            reasons.append(f"case-manual:{case['id']}")
        input_fixture = self.fixture["input_fixtures"][case["input_fixture"]]
        if input_fixture.get("registry_status") == "pending-registration":
            reasons.append(f"input-fixture-pending:{case['input_fixture']}")
        input_automation = input_fixture.get("automation")
        if not isinstance(input_automation, Mapping):
            reasons.append(f"input-fixture-unbound:{case['input_fixture']}")
        elif input_automation.get("driver") == "manual":
            reasons.append(f"input-fixture-manual:{case['input_fixture']}")
        processor_names = [case["processor_fixture"], *case.get("processor_fixture_matrix", [])]
        for name in processor_names:
            processor = self.fixture["processor_fixtures"][name]
            if processor.get("profile_status") == "pending-registration":
                reasons.append(f"processor-fixture-pending:{name}")
            processor_automation = processor.get("automation")
            if not isinstance(processor_automation, Mapping):
                reasons.append(f"processor-fixture-unbound:{name}")
            elif processor_automation.get("driver") == "manual":
                reasons.append(f"processor-fixture-manual:{name}")
        return not reasons, reasons


class LinuxPlatform:
    """Bounded target-side probes and mutations used by the runner."""

    def __init__(
        self,
        *,
        audio_user: str,
        database_path: Path,
        result_root: Path,
        runtime_redis_key: str,
        static_paths: Sequence[Path],
        venv_python: Path = Path("/opt/home-cinema/open-cinema/venv/bin/python"),
        app_path: Path = Path("/opt/home-cinema/open-cinema"),
        intent_adapter: Path = Path("/usr/local/libexec/open-cinema-benchmark-intent-adapter"),
        benchmark_contracts_root: Path = Path("/usr/local/share/open-cinema/benchmarks"),
        camilladsp_host: str = "127.0.0.1",
        camilladsp_port: int = 1234,
        command_timeout: float = 5.0,
    ) -> None:
        self.audio_user = audio_user
        self.database_path = database_path
        self.result_root = result_root
        self.runtime_redis_key = runtime_redis_key
        self.static_paths = tuple(static_paths)
        self.venv_python = venv_python
        self.app_path = app_path
        self.intent_adapter = intent_adapter
        self.benchmark_contracts_root = benchmark_contracts_root
        self.camilladsp_host = camilladsp_host
        self.camilladsp_port = camilladsp_port
        self.command_timeout = command_timeout
        self.audio_uid = self._resolve_audio_uid()
        self._last_cpu: tuple[int, int] | None = None
        self._playback_processes: dict[str, _PlaybackProcess] = {}
        self._camilladsp_client: Any | None = None
        self._camilladsp_lock = threading.Lock()
        self._event_storage_lock = threading.Lock()
        self._event_storage_last_sequence = 0
        self._event_storage_counts = {
            "offered": 0,
            "processed": 0,
            "coalesced": 0,
            "retried": 0,
            "dropped": 0,
        }
        self._transition_database_lock = threading.Lock()
        self._transition_database_worker: threading.Thread | None = None
        self._transition_database_cache: dict[str, Any] = {
            "observedMonotonicNs": None,
            "processorProjections": {
                "available": False,
                "error": "database-snapshot-pending",
            },
            "reconciliation": {
                "available": False,
                "error": "database-snapshot-pending",
            },
        }

    def _resolve_audio_uid(self) -> int:
        result = subprocess.run(
            ["id", "-u", self.audio_user],
            check=True,
            capture_output=True,
            text=True,
            timeout=self.command_timeout,
        )
        return int(result.stdout.strip())

    def monotonic_ns(self) -> int:
        return boottime_ns()

    def utc_now(self) -> str:
        return utc_now()

    def boot_id(self) -> str:
        return self._read(Path("/proc/sys/kernel/random/boot_id"), "unknown")

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def command(
        self,
        argv: Sequence[str],
        *,
        audio_session: bool = False,
        timeout: float | None = None,
        check: bool = False,
        input_text: str | None = None,
        cwd: Path | None = None,
    ) -> dict[str, Any]:
        command = list(argv)
        if audio_session:
            command = self._audio_argv(command)
        started = self.monotonic_ns()
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                input=input_text,
                cwd=str(cwd) if cwd is not None else None,
                timeout=timeout or self.command_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise CaseTimeout(f"command timed out: {command[0]}") from error
        document = {
            "argv": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "durationNs": self.monotonic_ns() - started,
        }
        if check and result.returncode:
            raise BenchmarkError(
                f"command failed ({result.returncode}): {' '.join(command[:3])}: "
                f"{result.stderr.strip()}"
            )
        return document

    def _audio_command(self, argv: Sequence[str], **kwargs: Any) -> dict[str, Any]:
        return self.command(argv, audio_session=True, **kwargs)

    def _audio_argv(self, argv: Sequence[str]) -> list[str]:
        return [
            "runuser",
            "-u",
            self.audio_user,
            "--",
            "env",
            f"XDG_RUNTIME_DIR=/run/user/{self.audio_uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{self.audio_uid}/bus",
            "PIPEWIRE_REMOTE=pipewire-0",
            *argv,
        ]

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> int | None:
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        return process.returncode

    def start_file_playback(
        self,
        *,
        asset_path: Path,
        source_kind: str,
        sample_format: str,
        sample_rate_hz: int,
        channels: int,
        channel_map: str,
        target_node: str,
        evidence_dir: Path,
    ) -> tuple[object, Mapping[str, Any]]:
        if source_kind not in {"container", "raw-s16le"}:
            raise BenchmarkError(f"unsupported playback source kind: {source_kind}")
        if sample_format != "s16" or sample_rate_hz != 48_000:
            raise BenchmarkError("benchmark playback requires 48 kHz signed 16-bit PCM")
        if not 1 <= channels <= 8:
            raise BenchmarkError("benchmark playback channels must be between one and eight")
        if not re.fullmatch(r"[A-Z0-9,-]{2,80}", channel_map):
            raise BenchmarkError("benchmark playback channel map is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", target_node):
            raise BenchmarkError("benchmark playback target node is invalid")
        if not asset_path.is_file():
            raise BenchmarkError(f"benchmark playback asset is missing: {asset_path.name}")

        token = uuid.uuid4().hex
        feeder_log_path = evidence_dir / f"playback-{token}-ffmpeg.log"
        player_log_path = evidence_dir / f"playback-{token}-pw-cat.log"
        feeder_log = feeder_log_path.open("wb")
        player_log = player_log_path.open("wb")
        input_arguments = ["-re", "-stream_loop", "-1"]
        if source_kind == "raw-s16le":
            input_arguments.extend(
                (
                    "-f",
                    "s16le",
                    "-ar",
                    str(sample_rate_hz),
                    "-ac",
                    str(channels),
                )
            )
        input_arguments.extend(("-i", str(asset_path)))
        codec_arguments = (
            ["-c:a", "copy"]
            if source_kind == "raw-s16le"
            else [
                "-c:a",
                "pcm_s16le",
            ]
        )
        process_marker = f"OPEN_CINEMA_BENCHMARK_HANDLE={token}"
        # FFmpeg does not need PipeWire access and deliberately stays root-side
        # so frozen run inputs can remain private.  WAV framing lets pw-cat
        # discover the stdin stream while preserving the exact s16 carrier.
        feeder_argv = [
            "env",
            process_marker,
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            *input_arguments,
            "-map",
            "0:a:0",
            "-vn",
            *codec_arguments,
            "-f",
            "wav",
            "pipe:1",
        ]
        player_name = f"open-cinema.benchmark.playback.{token}"
        player_argv = self._audio_argv(
            [
                "env",
                process_marker,
                "pw-cat",
                "--playback",
                "--target",
                target_node,
                "--rate",
                str(sample_rate_hz),
                "--channels",
                str(channels),
                "--channel-map",
                channel_map,
                "--format",
                sample_format,
                "--latency",
                "128",
                "--properties",
                f"node.name={player_name}",
                "-",
            ]
        )
        feeder: subprocess.Popen[bytes] | None = None
        player: subprocess.Popen[bytes] | None = None
        try:
            feeder = subprocess.Popen(
                feeder_argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=feeder_log,
                start_new_session=True,
            )
            if feeder.stdout is None:  # pragma: no cover - subprocess contract.
                raise BenchmarkError("ffmpeg playback pipe was not created")
            player = subprocess.Popen(
                player_argv,
                stdin=feeder.stdout,
                stdout=subprocess.DEVNULL,
                stderr=player_log,
                start_new_session=True,
            )
            feeder.stdout.close()
        except BaseException:
            if player is not None:
                self._stop_process(player)
            if feeder is not None:
                self._stop_process(feeder)
            feeder_log.close()
            player_log.close()
            raise
        evidence = {
            "handleId": token,
            "nodeName": player_name,
            "targetNode": target_node,
            "sourceAsset": asset_path.name,
            "sourceKind": source_kind,
            "sampleFormat": sample_format,
            "sampleRateHz": sample_rate_hz,
            "channels": channels,
            "channelMap": channel_map,
            "ffmpegLog": feeder_log_path.name,
            "pipewireLog": player_log_path.name,
            "feederPid": feeder.pid,
            "feederProcessGroup": os.getpgid(feeder.pid),
            "playerPid": player.pid,
            "playerProcessGroup": os.getpgid(player.pid),
        }
        self._playback_processes[token] = _PlaybackProcess(
            feeder=feeder,
            player=player,
            logs=(feeder_log, player_log),
            evidence=evidence,
        )
        readiness_deadline = self.monotonic_ns() + 5_000_000_000
        last_status: Mapping[str, Any] = {}
        while self.monotonic_ns() < readiness_deadline:
            last_status = self.playback_status(token)
            if (
                last_status.get("feederAlive") is True
                and last_status.get("playerAlive") is True
                and last_status.get("linked") is True
                and last_status.get("active") is True
            ):
                break
            if not last_status.get("feederAlive") or not last_status.get("playerAlive"):
                break
            time.sleep(0.1)
        else:
            last_status = self.playback_status(token)
        if not (
            last_status.get("feederAlive") is True
            and last_status.get("playerAlive") is True
            and last_status.get("linked") is True
            and last_status.get("active") is True
        ):
            result = self.stop_file_playback(token)
            raise BenchmarkError(
                f"benchmark playback did not become active on its target: "
                f"status={last_status}, cleanup={result}"
            )
        return token, evidence

    def wait_for_audio_node(
        self, node_name: str, *, timeout_seconds: float
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", node_name):
            raise BenchmarkError("benchmark playback target node is invalid")
        started = self.monotonic_ns()
        deadline = started + int(timeout_seconds * 1_000_000_000)
        attempts = 0
        last_error: str | None = None
        while self.monotonic_ns() < deadline:
            attempts += 1
            remaining = max(0.05, (deadline - self.monotonic_ns()) / 1_000_000_000)
            try:
                document = self.pipewire_document(timeout_seconds=min(0.5, remaining))
            except CaseTimeout:
                document = {"error": "pw-dump-timeout"}
            if isinstance(document, list):
                for item in document:
                    if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Node":
                        continue
                    info = item.get("info") if isinstance(item.get("info"), dict) else {}
                    props = info.get("props") if isinstance(info.get("props"), dict) else {}
                    if props.get("node.name") == node_name:
                        return {
                            "ready": True,
                            "nodeName": node_name,
                            "attempts": attempts,
                            "durationNs": self.monotonic_ns() - started,
                        }
            elif isinstance(document, dict):
                last_error = str(document.get("error") or "pipewire-dump-unavailable")
            self.sleep(0.1)
        raise BenchmarkError(
            f"benchmark playback target did not reappear after service fault: "
            f"node={node_name!r}, attempts={attempts}, lastError={last_error!r}"
        )

    @staticmethod
    def playback_link_status_from_dump(
        document: object, *, node_name: str, target_node: str
    ) -> dict[str, Any]:
        if not isinstance(document, list):
            return {"linked": False, "active": False, "reason": "pipewire-dump-unavailable"}

        def identifier(value: object) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        node_ids: dict[str, set[int]] = {}
        for item in document:
            if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Node":
                continue
            item_id = identifier(item.get("id"))
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            props = info.get("props") if isinstance(info.get("props"), dict) else {}
            name = props.get("node.name")
            if item_id is not None and isinstance(name, str):
                node_ids.setdefault(name, set()).add(item_id)
        sources = node_ids.get(node_name, set())
        targets = node_ids.get(target_node, set())
        states: list[str] = []
        for item in document:
            if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Link":
                continue
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            props = info.get("props") if isinstance(info.get("props"), dict) else {}
            if (
                identifier(props.get("link.output.node")) in sources
                and identifier(props.get("link.input.node")) in targets
            ):
                states.append(str(info.get("state", "unknown")).lower())
        return {
            "linked": bool(states),
            "active": any(state == "active" for state in states),
            "linkStates": sorted(states),
            "sourceNodePresent": bool(sources),
            "targetNodePresent": bool(targets),
        }

    def playback_status(self, handle: object) -> Mapping[str, Any]:
        if not isinstance(handle, str):
            raise BenchmarkError("benchmark playback handle is invalid")
        process = self._playback_processes.get(handle)
        if process is None:
            return {
                "handleId": handle,
                "feederAlive": False,
                "playerAlive": False,
                "linked": False,
                "active": False,
                "reason": "unknown-playback-handle",
            }
        link = self.playback_link_status_from_dump(
            self.pipewire_document(),
            node_name=str(process.evidence["nodeName"]),
            target_node=str(process.evidence["targetNode"]),
        )
        return {
            "handleId": handle,
            "feederAlive": process.feeder.poll() is None,
            "feederReturncode": process.feeder.returncode,
            "playerAlive": process.player.poll() is None,
            "playerReturncode": process.player.returncode,
            **link,
        }

    def stop_file_playback(self, handle: object) -> Mapping[str, Any]:
        if not isinstance(handle, str):
            raise BenchmarkError("benchmark playback handle is invalid")
        process = self._playback_processes.pop(handle, None)
        if process is None:
            return {"handleId": handle, "alreadyStopped": True}
        feeder_before_stop = process.feeder.poll()
        player_before_stop = process.player.poll()
        feeder_returncode = self._stop_process(process.feeder)
        player_returncode = self._stop_process(process.player)
        for stream in process.logs:
            stream.close()
        return {
            "handleId": handle,
            "alreadyStopped": False,
            "feederReturncode": feeder_returncode,
            "playerReturncode": player_returncode,
            "feederAliveBeforeStop": feeder_before_stop is None,
            "playerAliveBeforeStop": player_before_stop is None,
            "ok": feeder_before_stop is None and player_before_stop is None,
        }

    @staticmethod
    def _process_group_has_benchmark_marker(process_group: int, handle_id: str) -> bool:
        marker = f"OPEN_CINEMA_BENCHMARK_HANDLE={handle_id}".encode()
        for process_path in Path("/proc").glob("[0-9]*"):
            try:
                process_id = int(process_path.name)
                if os.getpgid(process_id) != process_group:
                    continue
                environment = (process_path / "environ").read_bytes().split(b"\0")
            except (OSError, ProcessLookupError, ValueError):
                continue
            if marker in environment:
                return True
        return False

    @classmethod
    def _stop_persisted_playback(cls, record: Mapping[str, Any]) -> dict[str, Any]:
        handle_id = record.get("handleId")
        if not isinstance(handle_id, str) or not re.fullmatch(r"[a-f0-9]{32}", handle_id):
            raise RestorationError("persisted playback handle is invalid")
        groups = []
        for key in ("feederProcessGroup", "playerProcessGroup"):
            value = record.get(key)
            if isinstance(value, int) and value > 1 and value not in groups:
                groups.append(value)
        actions = []
        for process_group in groups:
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                actions.append({"processGroup": process_group, "action": "already-stopped"})
                continue
            except PermissionError as error:
                raise RestorationError(
                    f"cannot inspect persisted playback process group: {process_group}"
                ) from error
            if not cls._process_group_has_benchmark_marker(process_group, handle_id):
                actions.append(
                    {
                        "processGroup": process_group,
                        "action": "not-owned-or-already-stopped",
                    }
                )
                continue
            os.killpg(process_group, signal.SIGTERM)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    os.killpg(process_group, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                os.killpg(process_group, signal.SIGKILL)
            actions.append({"processGroup": process_group, "action": "stopped"})
        return {"handleId": handle_id, "processGroups": actions}

    def restore_workload_journals(self, run_dir: Path) -> dict[str, Any]:
        """Clean only journal-identified benchmark mutations from a prior process."""

        resolved_run = run_dir.resolve()
        journals = sorted((resolved_run / "cases").glob("*/*/workload-restore.json"))
        active: list[tuple[Path, dict[str, Any]]] = []
        for path in journals:
            try:
                path.resolve().relative_to(resolved_run)
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise RestorationError(f"invalid workload restoration journal: {path}") from error
            if document.get("schemaVersion") != 1:
                raise RestorationError(f"unsupported workload restoration journal: {path}")
            if document.get("active") is True:
                active.append((path, document))

        configuration_digests = {
            document.get("camilladspOriginalConfigurationSha256")
            for _path, document in active
            if document.get("camilladspOriginalConfiguration") is not None
        }
        if len(configuration_digests) > 1:
            raise RestorationError(
                "active workload journals disagree about the original CamillaDSP configuration"
            )

        playback_actions = []
        for _path, document in active:
            playback = document.get("playback")
            if isinstance(playback, Mapping):
                playback_actions.append(self._stop_persisted_playback(playback))

        camilladsp_action: dict[str, Any] | None = None
        if configuration_digests:
            configuration = next(
                document["camilladspOriginalConfiguration"]
                for _path, document in active
                if document.get("camilladspOriginalConfiguration") is not None
            )
            if not isinstance(configuration, dict):
                raise RestorationError("persisted CamillaDSP configuration is invalid")
            expected_digest = next(iter(configuration_digests))
            if expected_digest != digest_document(configuration):
                raise RestorationError("persisted CamillaDSP configuration digest differs")
            camilla_unit = "camilladsp@camilladsp-0.service"
            if not self.service_state(camilla_unit)["active"]:
                started = self._service_command(camilla_unit, "start")
                if started["returncode"]:
                    raise RestorationError("failed to start CamillaDSP for workload restoration")
            applied = self.apply_camilladsp_configuration(configuration)
            observed = dict(self.camilladsp_active_configuration())
            if digest_document(observed) != expected_digest:
                raise RestorationError("CamillaDSP workload restoration digest mismatch")
            camilladsp_action = {
                "configurationSha256": expected_digest,
                "backend": applied,
            }

        for path, document in active:
            document["active"] = False
            document["playback"] = None
            document["camilladspOriginalConfiguration"] = None
            document["camilladspOriginalConfigurationSha256"] = None
            document["restoredUtc"] = self.utc_now()
            atomic_write(
                path,
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                mode=0o600,
            )
        return {
            "activeJournalCount": len(active),
            "playbackActions": playback_actions,
            "camilladspAction": camilladsp_action,
        }

    def _camilladsp_control(self, script: str, *, document: object | None = None) -> dict[str, Any]:
        result = self.command(
            [str(self.venv_python), "-c", script],
            audio_session=True,
            timeout=20,
            input_text=(json.dumps(document, sort_keys=True) if document is not None else None),
        )
        output = result["stdout"].strip() or result["stderr"].strip()
        try:
            response = json.loads(output)
        except json.JSONDecodeError as error:
            raise BenchmarkError("CamillaDSP workload control returned invalid JSON") from error
        if not isinstance(response, dict):
            raise BenchmarkError("CamillaDSP workload control returned an invalid response")
        if result["returncode"]:
            if response.get("phase") == "validate":
                raise CamillaDSPConfigurationRejected(str(response.get("error")))
            raise BenchmarkError(
                f"CamillaDSP workload control failed during {response.get('phase', 'unknown')}"
            )
        return response

    def camilladsp_active_configuration(self) -> Mapping[str, Any]:
        script = """
import json
import camilladsp
client = camilladsp.CamillaClient(%r, %d)
phase = 'connect'
try:
    client.connect()
    phase = 'active'
    config = client.config.active()
    if not isinstance(config, dict):
        raise RuntimeError('CamillaDSP has no active configuration')
    print(json.dumps({'phase': 'complete', 'configuration': config}, sort_keys=True))
except Exception as error:
    print(json.dumps({'phase': phase, 'error': str(error)}, sort_keys=True))
    raise SystemExit(1)
finally:
    try:
        client.disconnect()
    except Exception:
        pass
""" % (self.camilladsp_host, self.camilladsp_port)
        response = self._camilladsp_control(script)
        configuration = response.get("configuration")
        if not isinstance(configuration, dict):
            raise BenchmarkError("CamillaDSP returned no active workload configuration")
        return configuration

    def apply_camilladsp_configuration(self, configuration: Mapping[str, Any]) -> Mapping[str, Any]:
        script = """
import json
import sys
import time
import camilladsp
document = json.load(sys.stdin)
client = camilladsp.CamillaClient(%r, %d)
phase = 'connect'
try:
    client.connect()
    phase = 'validate'
    client.config.validate(document)
    phase = 'apply'
    client.config.set_active(document)
    phase = 'readiness'
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.general.state()
        name = getattr(state, 'name', str(state)).rsplit('.', 1)[-1].lower()
        if name in {'running', 'paused'}:
            print(json.dumps({'phase': 'complete', 'state': name}, sort_keys=True))
            break
        time.sleep(0.05)
    else:
        raise RuntimeError('CamillaDSP did not become ready after configuration')
except Exception as error:
    print(json.dumps({'phase': phase, 'error': str(error)}, sort_keys=True))
    raise SystemExit(1)
finally:
    try:
        client.disconnect()
    except Exception:
        pass
""" % (self.camilladsp_host, self.camilladsp_port)
        return self._camilladsp_control(script, document=dict(configuration))

    def journal_marker(self, run_id: str) -> dict[str, str | None]:
        marker = f"open-cinema-benchmark-start:{run_id}"
        self.command(
            ["systemd-cat", "-t", "open-cinema-benchmark", "--priority=info"],
            input_text=marker + "\n",
            check=True,
        )
        cursor_result = self.command(["journalctl", "-n", "0", "--show-cursor"], check=True)
        match = re.search(r"-- cursor: (\S+)", cursor_result["stdout"])
        return {"marker": marker, "cursor": match.group(1) if match else None}

    def journal_since(self, marker: Mapping[str, Any], units: Sequence[str]) -> str:
        command = ["journalctl", "--no-pager", "--output=short-iso-precise"]
        if marker.get("cursor"):
            command.append(f"--after-cursor={marker['cursor']}")
        for unit in units:
            command.extend(("--unit", unit))
        return self.command(command, timeout=30)["stdout"]

    def _service_command(self, unit: str, action: str) -> dict[str, Any]:
        if unit not in RUNTIME_SERVICES:
            raise BenchmarkError(f"service is outside the benchmark boundary: {unit}")
        command = ["systemctl"]
        if unit in USER_SERVICES:
            command.append("--user")
        command.extend((action, unit))
        return self.command(command, audio_session=unit in USER_SERVICES, timeout=30)

    def service_state(self, unit: str) -> dict[str, Any]:
        result = self._service_command(unit, "is-active")
        return {
            "active": result["returncode"] == 0 and result["stdout"].strip() == "active",
            "state": result["stdout"].strip() or "unknown",
            "returncode": result["returncode"],
        }

    def inject_services(self, services: Sequence[str]) -> list[dict[str, Any]]:
        results = []
        for service in services:
            result = self._service_command(service, "restart")
            if result["returncode"]:
                raise BenchmarkError(f"bounded restart failed: {service}")
            results.append(
                {"service": service, "action": "restart", "durationNs": result["durationNs"]}
            )
        return results

    def restore_services(self, states: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for service in RUNTIME_SERVICES:
            expected_active = bool(states.get(service, {}).get("active"))
            current = self.service_state(service)
            if expected_active and not current["active"]:
                result = self._service_command(service, "start")
                results.append(
                    {"service": service, "action": "start", "returncode": result["returncode"]}
                )
                if result["returncode"]:
                    raise RestorationError(f"failed to start restored service: {service}")
            elif not expected_active and current["active"]:
                result = self._service_command(service, "stop")
                results.append(
                    {"service": service, "action": "stop", "returncode": result["returncode"]}
                )
                if result["returncode"]:
                    raise RestorationError(f"failed to stop restored service: {service}")
        mismatches = [
            service
            for service in RUNTIME_SERVICES
            if self.service_state(service)["active"] != bool(states.get(service, {}).get("active"))
        ]
        if mismatches:
            raise RestorationError(f"service-state restoration mismatch: {mismatches}")
        return results

    def _database(
        self, *, writable: bool = False, timeout_seconds: float = 5.0
    ) -> sqlite3.Connection | None:
        if not self.database_path.is_file():
            return None
        if writable:
            connection = sqlite3.connect(self.database_path, timeout=timeout_seconds)
        else:
            connection = sqlite3.connect(
                f"file:{self.database_path}?mode=ro",
                uri=True,
                timeout=timeout_seconds,
            )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={max(0, int(timeout_seconds * 1000))}")
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, bytes):
            return {"bytesHex": value.hex()}
        return value

    def table_snapshot(self, table: str) -> dict[str, Any]:
        connection = self._database()
        if connection is None:
            return {"present": False, "columns": [], "rows": []}
        try:
            if not self._table_exists(connection, table):
                return {"present": False, "columns": [], "rows": []}
            columns = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            order = columns[0] if columns else "rowid"
            rows = [
                [self._json_value(value) for value in row]
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY "{order}"')
            ]
            return {"present": True, "columns": columns, "rows": rows}
        finally:
            connection.close()

    def database_digest(self, tables: Sequence[str]) -> str:
        return digest_document({table: self.table_snapshot(table) for table in tables})

    def intent_snapshot(self) -> dict[str, Any]:
        result = self.command(
            (
                str(self.venv_python),
                str(self.intent_adapter),
                "--database-path",
                str(self.database_path),
                "snapshot",
            ),
            audio_session=True,
            cwd=self.app_path,
            timeout=30,
            check=True,
        )
        try:
            document = json.loads(result["stdout"])
        except json.JSONDecodeError as error:
            raise BenchmarkError("active-intent adapter returned invalid JSON") from error
        if not isinstance(document, dict) or not isinstance(document.get("semanticDigest"), str):
            raise BenchmarkError("active-intent adapter returned an invalid snapshot")
        return document

    def _intent_adapter_json(
        self,
        arguments: Sequence[str],
        *,
        timeout: float = 30,
        input_document: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.command(
            (
                str(self.venv_python),
                str(self.intent_adapter),
                "--database-path",
                str(self.database_path),
                *arguments,
            ),
            audio_session=True,
            cwd=self.app_path,
            timeout=timeout,
            input_text=(
                json.dumps(input_document, sort_keys=True)
                if input_document is not None
                else None
            ),
            check=True,
        )
        try:
            document = json.loads(result["stdout"])
        except json.JSONDecodeError as error:
            raise BenchmarkError("active-intent adapter returned invalid JSON") from error
        if not isinstance(document, dict):
            raise BenchmarkError("active-intent adapter returned an invalid document")
        return document

    def ensure_camilladsp_benchmark_fixtures(self) -> dict[str, Any]:
        document = self._intent_adapter_json(
            (
                "ensure-camilladsp-fixtures",
                "--profiles-root",
                str(self.benchmark_contracts_root / "media" / "camilladsp"),
            ),
            timeout=45,
        )
        if not isinstance(document.get("fixtures"), dict):
            raise BenchmarkError("managed CamillaDSP fixture preparation returned no fixtures")
        return document

    def _managed_revision_converged(self, definition_id: str, revision_id: str) -> bool:
        connection = self._database()
        if connection is None:
            return False
        try:
            row = connection.execute(
                "SELECT state.status, plan.graph_revision_id "
                "FROM api_appliedplanstate state "
                "LEFT JOIN api_resolvedplan plan ON plan.id = state.current_plan_id "
                "WHERE state.graph_definition_id = ?",
                (definition_id.replace("-", ""),),
            ).fetchone()
            return bool(
                row is not None
                and row["status"] == "converged"
                and str(row["graph_revision_id"]) == revision_id.replace("-", "")
            )
        finally:
            connection.close()

    def _enabled_revisions_converged(self) -> bool:
        connection = self._database()
        if connection is None:
            return False
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS enabled_count, "
                "SUM(CASE WHEN state.status = 'converged' "
                "AND plan.graph_revision_id = activation.revision_id THEN 1 ELSE 0 END) "
                "AS converged_count "
                "FROM api_graphactivation activation "
                "LEFT JOIN api_appliedplanstate state "
                "ON state.graph_definition_id = activation.definition_id "
                "LEFT JOIN api_resolvedplan plan ON plan.id = state.current_plan_id "
                "WHERE activation.enabled = 1"
            ).fetchone()
            return bool(
                row is not None
                and int(row["enabled_count"] or 0) > 0
                and int(row["enabled_count"] or 0) == int(row["converged_count"] or 0)
            )
        finally:
            connection.close()

    def wait_camilladsp_configuration(
        self,
        configuration: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        expected_digest = digest_document(dict(configuration))
        started = self.monotonic_ns()
        deadline = started + int(timeout_seconds * 1_000_000_000)
        observed_digest = None
        while self.monotonic_ns() < deadline:
            try:
                observed = dict(self.camilladsp_active_configuration())
                observed_digest = digest_document(observed)
            except BenchmarkError:
                observed_digest = None
            if observed_digest == expected_digest and self._enabled_revisions_converged():
                return {
                    "ready": True,
                    "configurationSha256": observed_digest,
                    "durationNs": self.monotonic_ns() - started,
                }
            self.sleep(0.1)
        raise BenchmarkError(
            "managed CamillaDSP configuration did not converge before the readiness deadline"
        )

    def activate_camilladsp_fixture(self, fixture_id: str) -> dict[str, Any]:
        started = self.monotonic_ns()
        document = self._intent_adapter_json(
            (
                "activate-camilladsp-fixture",
                "--profiles-root",
                str(self.benchmark_contracts_root / "media" / "camilladsp"),
                "--fixture-id",
                fixture_id,
            ),
            timeout=45,
        )
        definition_id = document.get("definitionId")
        revision_id = document.get("revisionId")
        profile_title = document.get("profileTitle")
        if not all(isinstance(value, str) for value in (definition_id, revision_id, profile_title)):
            raise BenchmarkError("managed CamillaDSP activation returned incomplete identity")
        deadline = started + 60_000_000_000
        observed_title = None
        while self.monotonic_ns() < deadline:
            try:
                observed_title = self.camilladsp_active_configuration().get("title")
            except BenchmarkError:
                observed_title = None
            if (
                observed_title == profile_title
                and self._managed_revision_converged(definition_id, revision_id)
            ):
                return {
                    "fixtureId": fixture_id,
                    "profileDigest": document.get("profileDigest"),
                    "configurationTitle": observed_title,
                    "activationDurationNs": self.monotonic_ns() - started,
                    "desiredStateVersion": document.get("desiredStateVersion"),
                }
            self.sleep(0.1)
        raise BenchmarkError("managed CamillaDSP fixture did not converge before its deadline")

    def restore_activations(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        result = self.command(
            (
                str(self.venv_python),
                str(self.intent_adapter),
                "--database-path",
                str(self.database_path),
                "restore",
                "--snapshot-stdin",
            ),
            audio_session=True,
            cwd=self.app_path,
            timeout=30,
            input_text=json.dumps(snapshot, sort_keys=True),
            check=True,
        )
        try:
            document = json.loads(result["stdout"])
        except json.JSONDecodeError as error:
            raise RestorationError("active-intent adapter returned invalid JSON") from error
        if not isinstance(document, dict) or not isinstance(document.get("snapshot"), dict):
            raise RestorationError("active-intent adapter returned an invalid restore result")
        return document

    def static_digest(self) -> str:
        digest = hashlib.sha256()
        for root in sorted(self.static_paths):
            digest.update(str(root).encode())
            digest.update(b"\0")
            if not root.exists():
                digest.update(b"missing\0")
                continue
            candidates = [root] if root.is_file() or root.is_symlink() else sorted(root.rglob("*"))
            for candidate in candidates:
                relative = candidate.relative_to(root) if candidate != root else Path(".")
                digest.update(relative.as_posix().encode())
                digest.update(b"\0")
                if candidate.is_symlink():
                    digest.update(b"link\0" + os.readlink(candidate).encode())
                elif candidate.is_file():
                    digest.update(b"file\0")
                    with candidate.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                digest.update(b"\0")
        return digest.hexdigest()

    def static_file_manifest(self) -> list[dict[str, Any]]:
        files = []
        for root in sorted(self.static_paths):
            candidates = (
                [root]
                if root.is_file()
                else (
                    sorted(path for path in root.rglob("*") if path.is_file())
                    if root.is_dir()
                    else []
                )
            )
            for path in candidates:
                files.append(
                    {
                        "path": str(path),
                        "sizeBytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
        return files

    @staticmethod
    def topology_from_dump(document: object) -> dict[str, Any]:
        def object_id(value: object) -> int | object:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value

        if not isinstance(document, list):
            return {"ownedLinkCount": 0, "links": [], "digest": digest_document([])}
        objects = {
            object_id(item.get("id")): item
            for item in document
            if isinstance(item, dict) and isinstance(object_id(item.get("id")), int)
        }
        node_names: dict[int, str] = {}
        port_names: dict[int, tuple[str, str]] = {}
        for identifier, item in objects.items():
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            props = info.get("props") if isinstance(info.get("props"), dict) else {}
            if item.get("type") == "PipeWire:Interface:Node":
                node_names[identifier] = str(props.get("node.name", f"node:{identifier}"))
        for identifier, item in objects.items():
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            props = info.get("props") if isinstance(info.get("props"), dict) else {}
            if item.get("type") == "PipeWire:Interface:Port":
                node_id = object_id(props.get("node.id"))
                port_names[identifier] = (
                    node_names.get(node_id, f"node:{node_id}"),
                    str(props.get("port.name", props.get("object.path", f"port:{identifier}"))),
                )
        links = []
        for item in document:
            if not isinstance(item, dict) or item.get("type") != "PipeWire:Interface:Link":
                continue
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            props = info.get("props") if isinstance(info.get("props"), dict) else {}
            if props.get("open-cinema.owner") != "open-cinema.orchestrator":
                continue
            output_port = object_id(props.get("link.output.port"))
            input_port = object_id(props.get("link.input.port"))
            output = port_names.get(
                output_port,
                (
                    node_names.get(
                        object_id(props.get("link.output.node")),
                        str(props.get("link.output.node")),
                    ),
                    str(output_port),
                ),
            )
            input_value = port_names.get(
                input_port,
                (
                    node_names.get(
                        object_id(props.get("link.input.node")),
                        str(props.get("link.input.node")),
                    ),
                    str(input_port),
                ),
            )
            links.append({"output": list(output), "input": list(input_value)})
        links.sort(key=lambda item: canonical_json(item))
        return {
            "ownedLinkCount": len(links),
            "links": links,
            "digest": digest_document(links),
        }

    def pipewire_document(self, *, timeout_seconds: float = 10.0) -> object:
        result = self._audio_command(["pw-dump"], timeout=timeout_seconds)
        if result["returncode"]:
            return {"error": result["stderr"].strip(), "objects": []}
        try:
            return json.loads(result["stdout"])
        except json.JSONDecodeError:
            return {"error": "invalid-pw-dump", "objects": []}

    def topology(self, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        return self.topology_from_dump(
            self.pipewire_document(timeout_seconds=timeout_seconds)
        )

    def runtime_snapshot(self) -> dict[str, Any]:
        result = self.command(
            ["redis-cli", "-h", "127.0.0.1", "--raw", "GET", self.runtime_redis_key]
        )
        if result["returncode"] or not result["stdout"].strip():
            return {"available": False, "error": result["stderr"].strip()}
        try:
            value = json.loads(result["stdout"])
        except json.JSONDecodeError:
            return {"available": False, "error": "invalid-runtime-json"}
        return {"available": True, "value": value}

    def decoder_status(self) -> dict[str, Any]:
        sockets = sorted(Path("/run/open-cinema/decoder").glob("*.sock"))
        if not sockets:
            return {"available": False, "error": "status-socket-unavailable"}
        result = self.command(
            ["nc", "-N", "-U", str(sockets[0])],
            input_text='{"protocolVersion":2,"messageType":"getStatus"}\n',
            timeout=2,
        )
        try:
            value = json.loads(result["stdout"])
        except json.JSONDecodeError:
            return {"available": False, "error": "invalid-decoder-status"}
        return {"available": result["returncode"] == 0, "value": value}

    def camilladsp_status(self, *, blocking: bool = True) -> dict[str, Any]:
        # This probe runs at transition cadence and from the sustained worker.
        # Reusing one synchronized websocket avoids a Python subprocess and a
        # fresh connection for every sample. A processor restart invalidates
        # the client; the next sample reconnects without retaining stale state.
        # The transition collector must not wait behind the sustained probe: a
        # reconnect during a service restart can otherwise consume multiple
        # 200 ms transition slots. Native health keeps the blocking observation;
        # the transition stream records an explicit busy observation instead.
        acquired = self._camilladsp_lock.acquire(blocking=blocking)
        if not acquired:
            return {
                "available": False,
                "error": "camilladsp-status-query-in-progress",
            }
        try:
            client = self._camilladsp_client
            try:
                if client is None:
                    import camilladsp

                    client = camilladsp.CamillaClient(self.camilladsp_host, self.camilladsp_port)
                    client.connect()
                    self._camilladsp_client = client
                state = client.general.state()
                return {
                    "available": True,
                    "value": {
                        "state": getattr(state, "name", str(state)).lower(),
                        "bufferLevelFrames": client.status.buffer_level(),
                        "clippedSamples": client.status.clipped_samples(),
                        "processingLoadPercent": client.status.processing_load(),
                        "resamplerLoadPercent": client.status.resampler_load(),
                        "captureRateRaw": client.rate.capture_raw(),
                    },
                }
            except BaseException as error:
                if client is not None:
                    try:
                        client.disconnect()
                    except BaseException:
                        pass
                self._camilladsp_client = None
                return {
                    "available": False,
                    "error": f"camilladsp-status-query-failed:{type(error).__name__}",
                }
        finally:
            self._camilladsp_lock.release()

    def _os_release(self) -> dict[str, str]:
        values = {}
        path = Path("/etc/os-release")
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value.strip().strip('"')
        return values

    @staticmethod
    def _read(path: Path, default: str = "") -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip("\0\n ")
        except OSError:
            return default

    def fixture_facts(self, fixture: Mapping[str, Any]) -> dict[str, Any]:
        cpuinfo = self._read(Path("/proc/cpuinfo"))
        revision_match = re.search(r"^Revision\s*:\s*(\S+)", cpuinfo, re.MULTILINE)
        memory_match = re.search(
            r"^MemTotal:\s*(\d+)\s+kB", self._read(Path("/proc/meminfo")), re.MULTILINE
        )
        interfaces = []
        for interface in sorted(Path("/sys/class/net").glob("*")):
            interfaces.append(
                {
                    "name": interface.name,
                    "operstate": self._read(interface / "operstate", "unknown"),
                    "speedMbps": self._read(interface / "speed") or None,
                    "address": redact_string(self._read(interface / "address")),
                }
            )
        bluetooth = self.command(["bluetoothctl", "devices"])
        bluetooth_records = []
        for line in bluetooth["stdout"].splitlines():
            match = HARDWARE_ADDRESS_PATTERN.search(line)
            if match:
                info = self.command(["bluetoothctl", "info", match.group(0)])
                bluetooth_records.append(redact_string(info["stdout"] or line))
        versions: dict[str, Any] = {}
        for name, command in {
            "pipewire": ["pipewire", "--version"],
            "wireplumber": ["wireplumber", "--version"],
            "camilladsp": ["camilladsp", "--version"],
            "pcm-auto-decoder": ["pcm-auto-decoder", "--version"],
            "python": ["python3", "--version"],
            "ffmpeg": ["ffmpeg", "-version"],
            "pidstat": ["pidstat", "-V"],
        }.items():
            result = self.command(command)
            versions[name] = {
                "returncode": result["returncode"],
                "version": (
                    (result["stdout"] or result["stderr"]).splitlines()[0]
                    if (result["stdout"] or result["stderr"])
                    else "unavailable"
                ),
            }
        topology = self.topology()
        facts = {
            "capturedUtc": self.utc_now(),
            "capturedMonotonicNs": self.monotonic_ns(),
            "hardware": {
                "model": self._read(Path("/proc/device-tree/model"), python_platform.machine()),
                "revision": revision_match.group(1) if revision_match else "unknown",
                "memoryKb": int(memory_match.group(1)) if memory_match else None,
                "architecture": python_platform.machine(),
                "powerDeclaration": fixture["device_under_test"]["power"],
                "coolingDeclaration": fixture["device_under_test"]["cooling"],
            },
            "operatingSystem": self._os_release(),
            "kernel": python_platform.uname()._asdict(),
            "storage": {
                "root": shutil.disk_usage("/")._asdict(),
                "results": shutil.disk_usage(self.result_root)._asdict(),
            },
            "network": interfaces,
            "audioInterfaces": {
                "alsaCards": self._read(Path("/proc/asound/cards"), "unavailable"),
                "pipewireTopology": topology,
            },
            "bluetooth": {
                "declaration": fixture["bluetooth_fixtures"],
                "devices": bluetooth_records or [redact_string(bluetooth["stdout"])],
            },
            "graph": {
                "expectedOwnedLinks": fixture["audio_chain"]["graph"]["expected_owned_links"],
                "observed": topology,
                "activeIntent": self.intent_snapshot(),
                "intentDigest": self.database_digest(INTENT_TABLES),
            },
            "processorConfigs": {
                "staticDigest": self.static_digest(),
                "paths": [str(path) for path in self.static_paths],
                "files": self.static_file_manifest(),
            },
            "versions": versions,
            "initialThrottling": self.throttling(),
        }
        return redact_document(facts)  # type: ignore[return-value]

    def throttling(self) -> str:
        result = self.command(["vcgencmd", "get_throttled"])
        if result["returncode"]:
            return "unavailable"
        return result["stdout"].strip().partition("=")[2] or result["stdout"].strip()

    def temperature(self) -> float | None:
        thermal = self._read(Path("/sys/class/thermal/thermal_zone0/temp"))
        if thermal.isdigit():
            return int(thermal) / 1000
        result = self.command(["vcgencmd", "measure_temp"])
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", result["stdout"])
        return float(match.group(1)) if match else None

    def _cpu_percent(self) -> float | None:
        line = self._read(Path("/proc/stat")).splitlines()[0].split()
        if not line or line[0] != "cpu":
            return None
        values = [int(value) for value in line[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        previous = self._last_cpu
        self._last_cpu = (idle, total)
        if previous is None or total == previous[1]:
            return None
        return 100 * (1 - (idle - previous[0]) / (total - previous[1]))

    def _processes(self) -> list[dict[str, Any]]:
        result = self.command(
            ["ps", "-u", str(self.audio_uid), "-o", "pid=,comm=,%cpu=,rss=,etimes="]
        )
        rows = []
        for line in result["stdout"].splitlines():
            fields = line.split()
            if len(fields) != 5:
                continue
            try:
                rows.append(
                    {
                        "pid": int(fields[0]),
                        "command": fields[1],
                        "cpuPercent": float(fields[2]),
                        "rssKb": int(fields[3]),
                        "elapsedSeconds": int(fields[4]),
                    }
                )
            except ValueError:
                continue
        return rows

    def sustained_sample(self) -> dict[str, Any]:
        meminfo = self._read(Path("/proc/meminfo"))
        available = re.search(r"^MemAvailable:\s*(\d+)\s+kB", meminfo, re.MULTILINE)
        clock_results = {}
        for clock in ("arm", "core"):
            result = self.command(["vcgencmd", "measure_clock", clock])
            clock_results[clock] = result["stdout"].strip() or "unavailable"
        stat = os.statvfs(self.result_root)
        return {
            "applianceCpuPercent": self._cpu_percent(),
            "loadAverage": list(os.getloadavg()),
            "processes": self._processes(),
            "availableMemoryKb": int(available.group(1)) if available else None,
            "temperatureCelsius": self.temperature(),
            "clocks": clock_results,
            "throttling": self.throttling(),
            "services": {service: self.service_state(service) for service in RUNTIME_SERVICES},
            "diskCounters": self._read(Path("/proc/diskstats")),
            "filesystem": {
                "freeBytes": stat.f_bavail * stat.f_frsize,
                "totalBytes": stat.f_blocks * stat.f_frsize,
            },
        }

    def _applied_plan_state(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        connection = self._database(timeout_seconds=timeout_seconds)
        if connection is None:
            return {"available": False}
        try:
            if not self._table_exists(connection, "api_appliedplanstate"):
                return {"available": False}
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT graph_definition_id, current_plan_id, previous_plan_id, "
                    "transition_generation, status, last_error, updated_at "
                    "FROM api_appliedplanstate ORDER BY graph_definition_id"
                )
            ]
            return {"available": True, "states": rows}
        except sqlite3.OperationalError as error:
            return {
                "available": False,
                "error": (
                    "database-busy"
                    if "locked" in str(error).lower() or "busy" in str(error).lower()
                    else "database-query-failed"
                ),
            }
        finally:
            connection.close()

    def _processor_projection(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        connection = self._database(timeout_seconds=timeout_seconds)
        if connection is None:
            return {"available": False}
        try:
            if not self._table_exists(connection, "api_runtimeprojection"):
                return {"available": False}
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT projection_type, subject_key, world_generation, world_sequence, payload, observed_at "
                    "FROM api_runtimeprojection WHERE is_current = 1 AND projection_type IN "
                    "('managed-resource', 'processor-health') ORDER BY projection_type, subject_key"
                )
            ]
            for row in rows:
                try:
                    row["payload"] = json.loads(row["payload"])
                except (TypeError, json.JSONDecodeError):
                    pass
            return {"available": True, "rows": rows}
        except sqlite3.OperationalError as error:
            return {
                "available": False,
                "error": (
                    "database-busy"
                    if "locked" in str(error).lower() or "busy" in str(error).lower()
                    else "database-query-failed"
                ),
            }
        finally:
            connection.close()

    def _transition_database_snapshot(self) -> dict[str, Any]:
        """Return the last database observation and refresh it off the cadence path."""

        def refresh() -> None:
            projections = self._processor_projection(timeout_seconds=0.01)
            reconciliation = self._applied_plan_state(timeout_seconds=0.01)
            observed_ns = self.monotonic_ns()
            with self._transition_database_lock:
                self._transition_database_cache = {
                    "observedMonotonicNs": observed_ns,
                    "processorProjections": projections,
                    "reconciliation": reconciliation,
                }

        with self._transition_database_lock:
            worker = self._transition_database_worker
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=refresh,
                    name="open-cinema-transition-database",
                    daemon=True,
                )
                self._transition_database_worker = worker
                worker.start()
            cache = dict(self._transition_database_cache)
            refresh_in_progress = worker.is_alive()
        observed_ns = cache.get("observedMonotonicNs")
        return {
            **cache,
            "ageNs": (
                max(0, self.monotonic_ns() - int(observed_ns))
                if isinstance(observed_ns, int)
                else None
            ),
            "refreshInProgress": refresh_in_progress,
        }

    def transition_sample(self) -> dict[str, Any]:
        component_overheads: dict[str, int] = {}
        component_started = self.monotonic_ns()
        runtime = self.runtime_snapshot()
        component_overheads["runtime"] = self.monotonic_ns() - component_started
        value = runtime.get("value", {}) if runtime.get("available") else {}
        component_started = self.monotonic_ns()
        try:
            topology = self.topology(timeout_seconds=0.1)
        except CaseTimeout:
            topology = {
                "available": False,
                "error": "pw-dump-timeout",
                "ownedLinkCount": None,
                "links": [],
                "digest": None,
            }
        component_overheads["pipewireTopology"] = self.monotonic_ns() - component_started
        component_started = self.monotonic_ns()
        database_snapshot = self._transition_database_snapshot()
        component_overheads["databaseSnapshotCache"] = (
            self.monotonic_ns() - component_started
        )
        projections = database_snapshot["processorProjections"]
        rows = projections.get("rows", []) if projections.get("available") else []
        processor_ready = bool(projections.get("available")) and all(
            (
                not isinstance(row.get("payload"), dict)
                or (
                    row["payload"].get("ready", True) is True
                    and row["payload"].get("health", "healthy") == "healthy"
                    and row["payload"].get("error") is None
                )
            )
            for row in rows
        )
        component_started = self.monotonic_ns()
        decoder = self.decoder_status()
        component_overheads["decoderStatus"] = self.monotonic_ns() - component_started
        component_started = self.monotonic_ns()
        camilladsp = self.camilladsp_status(blocking=False)
        component_overheads["camilladspStatus"] = self.monotonic_ns() - component_started
        return {
            "pipewire": topology,
            "runtime": runtime,
            "runtimeGeneration": value.get("runtimeGeneration"),
            "runtimeSequence": value.get("runtimeSequence"),
            "worldVersion": value.get("worldVersion"),
            "connectionState": (
                value.get("connection", {}).get("state")
                if isinstance(value.get("connection"), dict)
                else None
            ),
            "retryState": value.get("retryState", value.get("retry")),
            "processorReadiness": {"ready": processor_ready, "projections": projections},
            "decoder": decoder,
            "camilladsp": camilladsp,
            "reconciliation": database_snapshot["reconciliation"],
            "databaseObservation": {
                "observedMonotonicNs": database_snapshot["observedMonotonicNs"],
                "ageNs": database_snapshot["ageNs"],
                "refreshInProgress": database_snapshot["refreshInProgress"],
            },
            "componentProbeOverheadsNs": component_overheads,
            "audioRestorationMarker": None,
        }

    def native_health(self) -> dict[str, Any]:
        component_overheads: dict[str, int] = {}
        component_started = self.monotonic_ns()
        try:
            pw_top = self._audio_command(["pw-top", "-b", "-n", "1"], timeout=0.75)
            pw_top_observation = {
                "available": pw_top["returncode"] == 0,
                "returncode": pw_top["returncode"],
                "error": pw_top["stderr"].strip() or None,
            }
        except CaseTimeout:
            pw_top = {"stdout": ""}
            pw_top_observation = {
                "available": False,
                "returncode": None,
                "error": "pw-top-timeout",
            }
        component_overheads["pipewireTop"] = self.monotonic_ns() - component_started
        errors = []
        for line in pw_top["stdout"].splitlines():
            fields = line.split()
            if len(fields) < 9 or fields[0] not in {"R", "I", "S", "E"}:
                continue
            try:
                errors.append(
                    {"nodeId": int(fields[1]), "errors": int(fields[8]), "name": fields[-1]}
                )
            except ValueError:
                continue
        component_started = self.monotonic_ns()
        decoder = self.decoder_status()
        component_overheads["decoderStatus"] = self.monotonic_ns() - component_started
        component_started = self.monotonic_ns()
        camilladsp = self.camilladsp_status()
        component_overheads["camilladspStatus"] = self.monotonic_ns() - component_started
        component_started = self.monotonic_ns()
        processor_projections = self._processor_projection(timeout_seconds=0.1)
        component_overheads["processorProjections"] = (
            self.monotonic_ns() - component_started
        )
        return {
            "pipewireObjects": errors,
            "pipewireMaximumErrors": max((item["errors"] for item in errors), default=None),
            "pipewireTopObservation": pw_top_observation,
            "decoder": decoder,
            "camilladsp": camilladsp,
            "processorProjections": processor_projections,
            "componentProbeOverheadsNs": component_overheads,
        }

    def begin_sustained_collection(self) -> dict[str, Any]:
        """Anchor event accounting before the timed one-second collection window."""

        last_sequence = 0
        connection = self._database(timeout_seconds=0.1)
        if connection is not None:
            try:
                if self._table_exists(connection, "api_orchestrationevent"):
                    row = connection.execute(
                        "SELECT COALESCE(MAX(sequence), 0) FROM api_orchestrationevent"
                    ).fetchone()
                    last_sequence = int(row[0]) if row is not None else 0
            except sqlite3.OperationalError:
                last_sequence = 0
            finally:
                connection.close()
        with self._event_storage_lock:
            self._event_storage_last_sequence = last_sequence
            self._event_storage_counts = {
                "offered": 0,
                "processed": 0,
                "coalesced": 0,
                "retried": 0,
                "dropped": 0,
            }
        return {"orchestrationEventBaselineSequence": last_sequence}

    def event_storage_sample(self) -> dict[str, Any]:
        started = self.monotonic_ns()
        connection = self._database(timeout_seconds=0.1)
        counts: dict[str, int] = {}
        busy = False
        quick_check = "database-unavailable"
        with self._event_storage_lock:
            event_sequence = self._event_storage_last_sequence
            events = dict(self._event_storage_counts)
        if connection is not None:
            try:
                for table in COUNT_TABLES:
                    if self._table_exists(connection, table):
                        counts[table] = int(
                            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        )
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                if self._table_exists(connection, "api_orchestrationevent"):
                    for row in connection.execute(
                        "SELECT sequence, event_type, payload FROM api_orchestrationevent "
                        "WHERE sequence > ? ORDER BY sequence",
                        (event_sequence,),
                    ):
                        event_sequence = max(event_sequence, int(row[0]))
                        name = str(row[1]).lower()
                        for category in events:
                            if category in name:
                                events[category] += 1
                        try:
                            payload = json.loads(row[2]) if isinstance(row[2], str) else row[2]
                        except json.JSONDecodeError:
                            payload = {}
                        if isinstance(payload, dict):
                            for category in events:
                                value = payload.get(category, payload.get(f"{category}Events"))
                                if isinstance(value, int):
                                    events[category] += value
            except sqlite3.OperationalError as error:
                busy = "locked" in str(error).lower() or "busy" in str(error).lower()
                quick_check = f"error:{error}"
            finally:
                connection.close()
        with self._event_storage_lock:
            if event_sequence >= self._event_storage_last_sequence:
                self._event_storage_last_sequence = event_sequence
                self._event_storage_counts = dict(events)
        redis = self.command(["redis-cli", "-h", "127.0.0.1", "INFO", "memory"])
        stat = self.database_path.stat() if self.database_path.exists() else None
        return {
            "sqliteLatencyNs": self.monotonic_ns() - started,
            "sqliteBusy": busy,
            "sqliteQuickCheck": quick_check,
            "retainedRecordCounts": counts,
            "orchestrationEvents": events,
            "redis": {"returncode": redis["returncode"], "info": redis["stdout"]},
            "database": {
                "sizeBytes": stat.st_size if stat else 0,
                "blocks": stat.st_blocks if stat else 0,
            },
            "diskCounters": self._read(Path("/proc/diskstats")),
        }

    def state_snapshot(self) -> dict[str, Any]:
        active_intent = self.intent_snapshot()
        return {
            "capturedUtc": self.utc_now(),
            "capturedMonotonicNs": self.monotonic_ns(),
            "services": {service: self.service_state(service) for service in RUNTIME_SERVICES},
            "activeIntent": active_intent,
            "intentDigest": active_intent["semanticDigest"],
            "observedIntentDatabaseDigest": self.database_digest(INTENT_TABLES),
            "staticDigest": self.static_digest(),
            "topology": self.topology(),
        }

    def restore(self, snapshot: Mapping[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        started = self.monotonic_ns()
        activation_restored = self.restore_activations(snapshot["activeIntent"])
        service_actions = self.restore_services(snapshot["services"])
        deadline = self.monotonic_ns() + int(timeout_seconds * 1_000_000_000)
        expected_topology = snapshot["topology"]
        observed_topology = self.topology()
        intent_converged = self._enabled_revisions_converged()
        while (
            (
                observed_topology.get("digest") != expected_topology.get("digest")
                or not intent_converged
            )
            and self.monotonic_ns() < deadline
        ):
            self.sleep(0.25)
            observed_topology = self.topology()
            intent_converged = self._enabled_revisions_converged()
        static_digest = self.static_digest()
        active_intent = self.intent_snapshot()
        intent_digest = active_intent["semanticDigest"]
        result = {
            "completedUtc": self.utc_now(),
            "durationNs": self.monotonic_ns() - started,
            "activeIntentRestoration": activation_restored,
            "serviceActions": service_actions,
            "topologyVerified": observed_topology.get("digest") == expected_topology.get("digest"),
            "expectedTopology": expected_topology,
            "observedTopology": observed_topology,
            "staticDigest": static_digest,
            "staticDigestVerified": static_digest == snapshot["staticDigest"],
            "dynamicDigest": intent_digest,
            "dynamicDigestVerified": intent_digest == snapshot["intentDigest"],
            "activeIntentConverged": intent_converged,
        }
        if not all(
            (
                result["topologyVerified"],
                result["staticDigestVerified"],
                result["dynamicDigestVerified"],
                result["activeIntentConverged"],
            )
        ):
            raise RestorationError(f"restoration verification failed: {result}")
        return result


@dataclass
class Deadline:
    platform: Any
    timeout_seconds: float

    def __post_init__(self) -> None:
        self.started_ns = self.platform.monotonic_ns()
        self.deadline_ns = self.started_ns + int(self.timeout_seconds * 1_000_000_000)

    def remaining(self) -> float:
        return max(0.0, (self.deadline_ns - self.platform.monotonic_ns()) / 1_000_000_000)

    def check(self) -> None:
        if self.platform.monotonic_ns() >= self.deadline_ns:
            raise CaseTimeout(f"case exceeded {self.timeout_seconds:g} seconds")


class BenchmarkRunner:
    def __init__(
        self,
        *,
        contracts: Contracts,
        result_root: Path,
        platform: Any,
        sustained_interval_seconds: float | None = None,
        transition_interval_seconds: float | None = None,
        workload_driver_factory: Any | None = None,
        implementation_paths: Mapping[str, Path] | None = None,
    ) -> None:
        self.contracts = contracts
        self.result_root = result_root
        self.platform = platform
        measurement = contracts.fixture["measurement"]
        self.sustained_interval = sustained_interval_seconds or float(
            measurement["sustained_interval_seconds"]
        )
        self.transition_interval = transition_interval_seconds or (
            float(measurement["transition_interval_milliseconds"]) / 1000
        )
        self.workload_driver_factory = workload_driver_factory
        default_intent_adapter = getattr(
            self.platform,
            "intent_adapter",
            _BENCHMARK_MODULE_ROOT / "benchmark_intent_adapter.py",
        )
        selected_implementation_paths = implementation_paths or {
            "benchmarkRunner": Path(__file__),
            "intentAdapter": Path(default_intent_adapter),
            "workloadDriver": _BENCHMARK_MODULE_ROOT / "benchmark_workload_driver.py",
        }
        if set(selected_implementation_paths) != set(IMPLEMENTATION_COMPONENTS):
            raise BenchmarkError(
                "benchmark implementation paths must identify runner, intent adapter, "
                "and workload driver"
            )
        self.implementation_paths = {
            name: Path(selected_implementation_paths[name]).resolve()
            for name in IMPLEMENTATION_COMPONENTS
        }

    @property
    def runs_root(self) -> Path:
        return self.result_root / "runs"

    def run_dir(self, run_id: str) -> Path:
        checked_identifier(run_id)
        path = self.runs_root / run_id
        if path.parent != self.runs_root:
            raise BenchmarkError("run path escaped the result root")
        return path

    def _new_run_id(self) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        return f"{stamp}-{uuid.uuid4().hex[:12]}"

    def _state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run-state.json"

    def _load_state(self, run_id: str) -> dict[str, Any]:
        path = self._state_path(run_id)
        if not path.is_file():
            raise BenchmarkError(f"unknown prepared run: {run_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("runId") != run_id:
            raise BenchmarkError("run-state identifier mismatch")
        return value

    def _save_state(self, state: Mapping[str, Any]) -> None:
        write_json(self._state_path(str(state["runId"])), state)

    def _implementation_identity(self) -> dict[str, Any]:
        components: dict[str, dict[str, str]] = {}
        for name in IMPLEMENTATION_COMPONENTS:
            path = self.implementation_paths[name]
            if not path.is_file():
                raise BenchmarkError(f"benchmark implementation component is missing: {name}")
            components[name] = {
                "fileName": path.name,
                "sha256": sha256_file(path),
            }
        return {"schemaVersion": 1, "components": components}

    @staticmethod
    def _safe_benchmark_input(root: Path, relative: object, *, label: str) -> Path:
        if not isinstance(relative, str) or not relative:
            raise ContractError(f"{label} path must be non-empty")
        candidate_relative = Path(relative)
        if candidate_relative.is_absolute():
            raise ContractError(f"{label} path must be relative: {relative}")
        resolved_root = root.resolve()
        candidate = (resolved_root / candidate_relative).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as error:
            raise ContractError(f"{label} path escapes the benchmark root: {relative}") from error
        if not candidate.is_file():
            raise ContractError(f"{label} file is missing: {relative}")
        return candidate

    def _workload_input_files(self) -> tuple[Path, ...]:
        root = self.contracts.root.resolve()
        media_registry_path = self._safe_benchmark_input(
            root, WORKLOAD_REGISTRY_FILES[0], label="media registry"
        )
        profile_registry_path = self._safe_benchmark_input(
            root, WORKLOAD_REGISTRY_FILES[1], label="CamillaDSP profile registry"
        )
        physical_path = self._safe_benchmark_input(
            root, WORKLOAD_REGISTRY_FILES[2], label="physical timing declaration"
        )
        try:
            media_registry = json.loads(media_registry_path.read_text(encoding="utf-8"))
            profile_registry = json.loads(profile_registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ContractError(f"invalid workload registry JSON: {error}") from error
        if not isinstance(media_registry, Mapping) or not isinstance(profile_registry, Mapping):
            raise ContractError("workload registries must contain objects")

        paths = {media_registry_path, profile_registry_path, physical_path}

        def add_assets(
            records: object,
            *,
            asset_root: Path,
            label: str,
        ) -> None:
            if not isinstance(records, list):
                raise ContractError(f"{label} registry must contain an array")
            for record in records:
                if not isinstance(record, Mapping):
                    raise ContractError(f"{label} registry contains an invalid entry")
                asset = self._safe_benchmark_input(
                    root,
                    str((asset_root / str(record.get("path", ""))).as_posix()),
                    label=label,
                )
                expected_size = record.get("sizeBytes")
                expected_digest = record.get("sha256")
                if not isinstance(expected_size, int) or asset.stat().st_size != expected_size:
                    raise ContractError(f"{label} size differs from registry: {asset.name}")
                if not isinstance(expected_digest, str) or sha256_file(asset) != expected_digest:
                    raise ContractError(f"{label} digest differs from registry: {asset.name}")
                paths.add(asset)

        add_assets(
            media_registry.get("fixtures"),
            asset_root=Path("media/generated"),
            label="media asset",
        )
        add_assets(
            profile_registry.get("profiles"),
            asset_root=Path("media/camilladsp"),
            label="CamillaDSP profile",
        )
        add_assets(
            profile_registry.get("assets"),
            asset_root=Path("media/camilladsp"),
            label="CamillaDSP profile asset",
        )
        return tuple(sorted(path.relative_to(root) for path in paths))

    def _assert_implementation_identity(self, state: Mapping[str, Any]) -> None:
        expected = state.get("implementationIdentity")
        if not isinstance(expected, Mapping):
            raise BenchmarkError(
                "prepared run has no benchmark implementation identity; prepare a new run"
            )
        observed = self._implementation_identity()
        if observed != expected:
            expected_components = expected.get("components", {})
            observed_components = observed["components"]
            changed = sorted(
                name
                for name in IMPLEMENTATION_COMPONENTS
                if not isinstance(expected_components, Mapping)
                or expected_components.get(name) != observed_components[name]
            )
            raise BenchmarkError(
                "benchmark implementation changed after prepare "
                f"({', '.join(changed)}); prepare a new run"
            )
        frozen_path = self.run_dir(str(state["runId"])) / "manifests/implementation-identity.json"
        manifest_digests = state.get("manifestDigests")
        expected_digest = (
            manifest_digests.get(frozen_path.name)
            if isinstance(manifest_digests, Mapping)
            else None
        )
        try:
            frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BenchmarkError("frozen implementation identity is unavailable") from error
        if (
            frozen != expected
            or not isinstance(expected_digest, str)
            or sha256_file(frozen_path) != expected_digest
        ):
            raise BenchmarkError("frozen implementation identity changed after prepare")

    def _assert_contract_identity(self, state: Mapping[str, Any]) -> None:
        expected = state.get("manifestDigests")
        if not isinstance(expected, Mapping):
            raise BenchmarkError("prepared run has no benchmark contract identity")
        run_manifests = self.run_dir(str(state["runId"])) / "manifests"
        changed: list[str] = []
        required = {*CONTRACT_FILES, *WORKLOAD_REGISTRY_FILES}
        changed.extend(sorted(required - set(expected)))
        for name, expected_digest in expected.items():
            if name == "implementation-identity.json":
                continue
            if not isinstance(name, str):
                changed.append(str(name))
                continue
            try:
                live_path = self._safe_benchmark_input(
                    self.contracts.root, name, label="prepared benchmark input"
                )
                frozen_path = self._safe_benchmark_input(
                    run_manifests, name, label="frozen benchmark input"
                )
            except ContractError:
                changed.append(name)
                continue
            if (
                not isinstance(expected_digest, str)
                or sha256_file(live_path) != expected_digest
                or sha256_file(frozen_path) != expected_digest
            ):
                changed.append(name)
        if changed:
            raise BenchmarkError(
                "benchmark contracts changed after prepare "
                f"({', '.join(sorted(set(changed)))}); restore the run if needed, "
                "then prepare a new run"
            )

    def _assert_prepared_identity(self, state: Mapping[str, Any]) -> None:
        self._assert_implementation_identity(state)
        self._assert_contract_identity(state)

    def _criteria(self, case: Mapping[str, Any]) -> dict[str, Any]:
        criteria_id = case["criteria_set"]
        try:
            return self.contracts.criteria["criteria_sets"][criteria_id]
        except KeyError as error:
            raise ContractError(f"unknown criteria set: {criteria_id}") from error

    def _fixture_comparison(self, facts: Mapping[str, Any]) -> dict[str, Any]:
        expected = self.contracts.fixture
        reasons = []
        hardware = facts.get("hardware", {})
        model = str(hardware.get("model", ""))
        if expected["device_under_test"]["model"] not in model:
            reasons.append("hardware-model-mismatch")
        architecture = str(hardware.get("architecture", ""))
        if architecture != expected["device_under_test"]["architecture"]:
            reasons.append("architecture-mismatch")
        memory_kb = hardware.get("memoryKb")
        expected_memory_kb = int(expected["device_under_test"]["memory_mb"]) * 1024
        if not isinstance(memory_kb, int) or memory_kb < int(expected_memory_kb * 0.9):
            reasons.append("memory-tier-mismatch")
        operating_system = facts.get("operatingSystem", {})
        expected_os = expected["device_under_test"]["operating_system"]
        if str(operating_system.get("ID", "")).lower() != expected_os["family"].lower():
            reasons.append("operating-system-family-mismatch")
        if operating_system.get("VERSION_CODENAME") != expected_os["codename"]:
            reasons.append("operating-system-codename-mismatch")
        topology = facts.get("graph", {}).get("observed", {})
        if (
            topology.get("ownedLinkCount")
            != expected["audio_chain"]["graph"]["expected_owned_links"]
        ):
            reasons.append("owned-topology-mismatch")
        if (
            facts.get("initialThrottling")
            != expected["power_and_thermal_preconditions"]["current_throttled_value"]
        ):
            reasons.append("initial-throttling-mismatch")
        expected_interface = expected["device_under_test"]["network"].get("primary_interface")
        if isinstance(expected_interface, str):
            matched_interface = next(
                (
                    interface
                    for interface in facts.get("network", [])
                    if interface.get("name") == expected_interface
                ),
                None,
            )
            if not matched_interface or matched_interface.get("operstate") != "up":
                reasons.append("primary-network-mismatch")
        return {
            "matchesSupportedFixture": not reasons,
            "classification": "supported-fixture" if not reasons else "exploratory",
            "reasons": reasons,
        }

    def prepare(
        self,
        *,
        case_ids: Sequence[str] = (),
        campaign: str | None = None,
        run_id: str | None = None,
    ) -> str:
        selected = self.contracts.selected_cases(case_ids, campaign)
        workload_inputs = self._workload_input_files()
        run_id = checked_identifier(run_id) if run_id else self._new_run_id()
        run_dir = self.run_dir(run_id)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        try:
            run_dir.mkdir(mode=0o750)
        except FileExistsError as error:
            raise BenchmarkError(f"run already exists: {run_id}") from error
        (run_dir / "cases").mkdir(mode=0o750)
        manifests_dir = run_dir / "manifests"
        manifests_dir.mkdir(mode=0o750)
        manifest_digests = {}
        prepared_inputs = tuple(Path(name) for name in CONTRACT_FILES) + workload_inputs
        for relative in prepared_inputs:
            source = self.contracts.root / relative
            destination = manifests_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o640)
            manifest_digests[relative.as_posix()] = sha256_file(destination)
        implementation_identity = self._implementation_identity()
        identity_path = manifests_dir / "implementation-identity.json"
        write_json(identity_path, implementation_identity)
        manifest_digests[identity_path.name] = sha256_file(identity_path)
        criteria_modes = {self._criteria(case)["campaign_mode"] for case in selected}
        if len(criteria_modes) != 1:
            raise ContractError("one run cannot mix characterization and acceptance cases")
        campaign_mode = next(iter(criteria_modes))
        if campaign_mode == "acceptance":
            for case in selected:
                criteria = self._criteria(case)
                if (
                    criteria.get("state") != "frozen"
                    or criteria.get("platform_acceptance_allowed") is not True
                ):
                    raise ContractError("acceptance is disabled until reviewed criteria are frozen")
        managed_camilladsp_required = any(
            (
                self.contracts.fixture["processor_fixtures"][fixture_name]
                .get("automation", {})
                .get("driver")
                == "managed-camilladsp-profile"
            )
            for case in selected
            for fixture_name in (
                case.get("processor_fixture_matrix") or [case["processor_fixture"]]
            )
        )
        camilladsp_fixtures = None
        if managed_camilladsp_required:
            ensure = getattr(self.platform, "ensure_camilladsp_benchmark_fixtures", None)
            if not callable(ensure):
                raise BenchmarkError(
                    "selected CamillaDSP cases require managed desired-graph fixtures"
                )
            camilladsp_fixtures = ensure()
            write_json(run_dir / "camilladsp-managed-fixtures.json", camilladsp_fixtures)
        journal = self.platform.journal_marker(run_id)
        facts = redact_document(self.platform.fixture_facts(self.contracts.fixture))
        fixture_comparison = self._fixture_comparison(facts)
        if campaign_mode == "acceptance" and not fixture_comparison["matchesSupportedFixture"]:
            raise ContractError(f"acceptance fixture mismatch: {fixture_comparison['reasons']}")
        snapshot = self.platform.state_snapshot()
        write_json(run_dir / "fixture-facts.json", facts)
        write_json(run_dir / "fixture-comparison.json", fixture_comparison)
        write_json(run_dir / "restore-snapshot.json", snapshot)
        write_json(run_dir / "journal-marker.json", journal)
        boot_id = (
            self.platform.boot_id()
            if hasattr(self.platform, "boot_id")
            else LinuxPlatform._read(Path("/proc/sys/kernel/random/boot_id"), "unknown")
        )
        calibration = {
            "clock": "CLOCK_BOOTTIME",
            "bootId": boot_id,
            "targetUtc": self.platform.utc_now(),
            "targetMonotonicNs": self.platform.monotonic_ns(),
            "controllerSubtractionAllowed": False,
            "controllerUncertaintyNs": None,
        }
        write_json(run_dir / "clock-calibration.json", calibration)
        cases = {}
        for case in selected:
            available, unavailable_reasons = self.contracts.fixture_available(case)
            cases[case["id"]] = {
                "status": "pending" if available else "fixture-unavailable",
                "nextUnit": 0,
                "sampleIds": [],
                "attemptsByUnit": {},
                "notMeasured": False,
                "unavailableReasons": unavailable_reasons,
                "restorationStatus": "not-required",
            }
        state = {
            "schemaVersion": 1,
            "suiteId": self.contracts.fixture["suite_id"],
            "runId": run_id,
            "campaignMode": campaign_mode,
            "fixtureContractId": self.contracts.fixture["fixture_contract_id"],
            "fixtureClassification": fixture_comparison["classification"],
            "createdUtc": self.platform.utc_now(),
            "createdMonotonicNs": self.platform.monotonic_ns(),
            "clockCalibration": calibration,
            "journalMarker": journal,
            "manifestDigests": manifest_digests,
            "implementationIdentity": implementation_identity,
            "camillaDSPManagedFixtures": camilladsp_fixtures,
            "selectedCaseIds": sorted(cases),
            "cases": cases,
            "status": "prepared",
            "finalized": False,
        }
        self._save_state(state)
        return run_id

    @staticmethod
    def _service_variants(case: Mapping[str, Any]) -> list[list[str]]:
        if case.get("service_matrix"):
            return [list(variant) for variant in case["service_matrix"]]
        if case.get("disruptive_services"):
            return [list(case["disruptive_services"])]
        return [[]]

    def _execution_units(self, case: Mapping[str, Any]) -> list[dict[str, Any]]:
        units = []
        processor_fixtures = list(
            case.get("processor_fixture_matrix") or [case["processor_fixture"]]
        )
        variant_index = 0
        for processor_fixture in processor_fixtures:
            for services in self._service_variants(case):
                total = int(case["warm_up_repetitions"]) + int(case["measured_repetitions"])
                for repetition in range(total):
                    units.append(
                        {
                            "variantIndex": variant_index,
                            "processorFixture": processor_fixture,
                            "services": services,
                            "repetition": repetition,
                            "warmUp": repetition < int(case["warm_up_repetitions"]),
                        }
                    )
                variant_index += 1
        return units

    def _workload_driver(
        self,
        *,
        state: Mapping[str, Any],
        case: Mapping[str, Any],
        unit: Mapping[str, Any],
        sample_dir: Path,
    ) -> Any:
        arguments = {
            "case": case,
            "unit": unit,
            "sample_dir": sample_dir,
        }
        if self.workload_driver_factory is not None:
            return self.workload_driver_factory(**arguments)
        return BenchmarkWorkloadDriver(
            contracts_root=self.run_dir(str(state["runId"])) / "manifests",
            fixture=self.contracts.fixture,
            backend=self.platform,
            **arguments,
        )

    def _sample_id(self, case_id: str, unit_index: int) -> str:
        return f"{case_id}-sample-{unit_index + 1:04d}"

    @staticmethod
    def _attempt_sample_id(case_id: str, unit_index: int, attempt: int) -> str:
        base = f"{case_id}-sample-{unit_index + 1:04d}"
        return base if attempt == 1 else f"{base}-attempt-{attempt:04d}"

    @staticmethod
    def _normalized_workload_artifacts(
        sample_dir: Path, artifacts: object
    ) -> dict[str, list[dict[str, Any]]]:
        normalized: dict[str, list[dict[str, Any]]] = {"logs": [], "captures": []}
        if not isinstance(artifacts, Mapping):
            return normalized
        for kind in normalized:
            entries = artifacts.get(kind, [])
            if not isinstance(entries, list):
                raise BenchmarkError(f"workload {kind} artifacts must be an array")
            for entry in entries:
                if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
                    raise BenchmarkError(f"workload {kind} artifact is invalid")
                relative = Path(str(entry["path"]))
                if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
                    raise BenchmarkError(f"workload {kind} artifact path escapes its sample")
                destination = (sample_dir / relative).resolve()
                try:
                    destination.relative_to(sample_dir.resolve())
                except ValueError as error:
                    raise BenchmarkError(
                        f"workload {kind} artifact path escapes its sample"
                    ) from error
                normalized[kind].append({"path": relative.as_posix(), "sha256": None})
        return normalized

    def _metric_coverage(
        self,
        *,
        run_dir: Path,
        sample_dir: Path,
        case: Mapping[str, Any],
        artifacts: Mapping[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        def present(relative: str, *, root: Path = sample_dir) -> bool:
            path = root / relative
            return path.is_file() and path.stat().st_size > 0

        coverage_paths: dict[str, list[str]] = {
            "fixture-facts": ["fixture-facts.json", "fixture-comparison.json"],
            "sustained-health": [
                "system.jsonl",
                "collector-batches.jsonl",
                "transition-batches.jsonl",
            ],
            "native-audio-health": ["native-health.jsonl"],
            "topology-and-readiness": ["transition.jsonl"],
            "transition-timing": ["transition.jsonl", "case-events.jsonl"],
            "event-accounting": ["event-storage.jsonl"],
            "persistence-storage": ["event-storage.jsonl"],
            "boot-readiness": [],
        }
        result: dict[str, dict[str, Any]] = {}
        for metric_set in case["required_metric_sets"]:
            if metric_set == "physical-audio":
                captures = [str(item["path"]) for item in artifacts.get("captures", [])]
                physical = self.contracts.fixture["measurement"]["physical_timing"]
                calibrated = (
                    physical.get("state") == "calibrated"
                    and physical.get("acceptance_metrics_available") is True
                )
                collected = (
                    calibrated and bool(captures) and all(present(path) for path in captures)
                )
                result[metric_set] = {
                    "status": "collected" if collected else "not-measured",
                    "artifacts": captures,
                    "reason": (
                        None
                        if collected
                        else "physical-capture-path-is-not-calibrated-or-capture-is-missing"
                    ),
                }
                continue
            paths = coverage_paths.get(metric_set)
            if paths is None:
                result[metric_set] = {
                    "status": "missing",
                    "artifacts": [],
                    "reason": "required-metric-set-has-no-runner-binding",
                }
                continue
            root = run_dir if metric_set == "fixture-facts" else sample_dir
            collected = bool(paths) and all(present(path, root=root) for path in paths)
            result[metric_set] = {
                "status": "collected" if collected else "missing",
                "artifacts": paths,
                "reason": None if collected else "required-metric-artifact-is-missing",
            }
        return result

    def _envelope(
        self,
        *,
        state: Mapping[str, Any],
        case: Mapping[str, Any],
        sample_id: str,
        unit: Mapping[str, Any],
        status: str,
        invalid: bool,
        reasons: Sequence[str],
        restoration: Mapping[str, Any],
        workload_artifacts: Mapping[str, list[dict[str, Any]]],
        metric_coverage: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        run_dir = self.run_dir(str(state["runId"]))
        criteria_path = run_dir / "manifests" / "criteria-policy.yml"
        sample_rel = Path("cases") / case["id"] / sample_id
        return {
            "schemaVersion": 1,
            "suiteId": state["suiteId"],
            "runId": state["runId"],
            "campaignId": case["campaign"],
            "caseId": case["id"],
            "sampleId": sample_id,
            "campaignMode": state["campaignMode"],
            "fixtureContractId": state["fixtureContractId"],
            "criteria": {
                "id": case["criteria_set"],
                "state": self._criteria(case)["state"],
                "sha256": sha256_file(criteria_path),
            },
            "timestamps": {
                "startedUtc": unit["startedUtc"],
                "completedUtc": unit.get("completedUtc"),
                "startedMonotonicNs": unit["startedMonotonicNs"],
                "completedMonotonicNs": unit.get("completedMonotonicNs"),
                "clockCalibration": state["clockCalibration"],
            },
            "workload": {
                "state": case["workload_state"],
                "carrierState": case["carrier_state"],
                "declarationSource": "versioned-case-manifest",
            },
            "manifests": {
                f"manifests/{name}": digest for name, digest in state["manifestDigests"].items()
            },
            "timeSeries": [
                {"path": str(sample_rel / "system.jsonl"), "sha256": None},
                {"path": str(sample_rel / "collector-batches.jsonl"), "sha256": None},
                {"path": str(sample_rel / "transition-batches.jsonl"), "sha256": None},
                {"path": str(sample_rel / "transition.jsonl"), "sha256": None},
                {"path": str(sample_rel / "native-health.jsonl"), "sha256": None},
                {"path": str(sample_rel / "event-storage.jsonl"), "sha256": None},
            ],
            "logs": [
                {"path": str(sample_rel / "case-events.jsonl"), "sha256": None},
                *(
                    {
                        "path": str(sample_rel / item["path"]),
                        "sha256": item.get("sha256"),
                    }
                    for item in workload_artifacts.get("logs", [])
                ),
            ],
            "captures": [
                {
                    "path": str(sample_rel / item["path"]),
                    "sha256": item.get("sha256"),
                }
                for item in workload_artifacts.get("captures", [])
            ],
            "metricCoverage": dict(metric_coverage),
            "invalidation": {"invalid": invalid, "reasons": list(reasons)},
            "restoration": {
                "action": case["restoration_action"],
                "required": bool(
                    restoration.get(
                        "required",
                        self.contracts.cases["restoration_actions"][case["restoration_action"]][
                            "disruptive"
                        ],
                    )
                ),
                "status": restoration.get("status", "not-required"),
                "topologyVerified": restoration.get("topologyVerified"),
                "staticDigest": restoration.get("staticDigest"),
                "dynamicDigest": restoration.get("dynamicDigest"),
            },
            "checksums": {
                "algorithm": "sha256",
                "manifestPath": str(sample_rel / "SHA256SUMS"),
                "manifestSha256": None,
            },
            "status": status,
        }

    def _emit_event(self, sample_dir: Path, event: str, **fields: Any) -> dict[str, Any]:
        document = {
            "event": event,
            "timestampUtc": self.platform.utc_now(),
            "monotonicNs": self.platform.monotonic_ns(),
            **fields,
        }
        append_jsonl(sample_dir / "case-events.jsonl", document)
        return document

    def _collect(
        self,
        *,
        case: Mapping[str, Any],
        sample_id: str,
        sample_dir: Path,
        services: Sequence[str],
        expected_topology: Mapping[str, Any],
        deadline: Deadline,
        workload: Any,
    ) -> dict[str, Any]:
        duration_ns = int(float(case["duration_seconds"]) * 1_000_000_000)
        sustained_ns = max(1, int(self.sustained_interval * 1_000_000_000))
        transition_ns = max(1, int(self.transition_interval * 1_000_000_000))
        sustained_sequence = 0
        transition_sequence = 0
        sustained_completed = 0
        transition_completed = 0
        sustained_missed = 0
        transition_missed = 0
        sustained_intervals: list[dict[str, Any]] = []
        transition_intervals: list[dict[str, Any]] = []
        injection_started = not services
        injection_done = not services
        scheduled_index = 0
        final_topology_converged = False
        final_processors_ready = False
        initial_workload_health = workload.health()
        self._emit_event(
            sample_dir,
            "workload-health-verified",
            result=redact_document(initial_workload_health),
        )
        if hasattr(self.platform, "begin_sustained_collection"):
            sustained_preflight = self.platform.begin_sustained_collection()
            self._emit_event(
                sample_dir,
                "sustained-collection-prepared",
                result=redact_document(sustained_preflight),
            )
        sustained_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="open-cinema-sustained-collector",
        )
        sustained_probe_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="open-cinema-sustained-probe",
        )
        sustained_persistence_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="open-cinema-sustained-persistence",
        )
        transition_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="open-cinema-transition-persistence",
        )
        fault_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="open-cinema-fault-injection",
        )
        scheduled_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="open-cinema-scheduled-transition",
        )
        last_audio_marker = self._emit_event(
            sample_dir, "measurement-start", sampleId=sample_id
        )
        started_ns = self.platform.monotonic_ns()
        end_ns = started_ns + duration_ns
        next_sustained = started_ns
        next_transition = started_ns
        injection_at = started_ns + min(duration_ns // 2, 1_000_000_000)
        scheduled = [
            started_ns + int(second * 1_000_000_000)
            for second in case.get("transition_schedule_seconds", [])
        ]
        sustained_future: Future[dict[str, Any]] | None = None
        sustained_persistence_futures: deque[Future[dict[str, Any]]] = deque()
        transition_futures: deque[Future[dict[str, Any]]] = deque()
        case_event_futures: deque[Future[dict[str, Any]]] = deque()
        fault_future: Future[dict[str, Any]] | None = None
        scheduled_future: Future[dict[str, Any]] | None = None
        fault_events: SimpleQueue[dict[str, Any]] = SimpleQueue()
        sustained_cancelled = threading.Event()
        sustained_wait_exhausted = False

        def collect_sustained_batch(
            started: threading.Event,
            sequence: int,
            scheduled_ns: int,
            fault_injection_in_progress: bool,
        ) -> dict[str, Any]:
            def timed_probe(probe: Callable[[], Any]) -> tuple[str, int, int, Any]:
                timestamp = self.platform.utc_now()
                probe_started = self.platform.monotonic_ns()
                value = probe()
                probe_completed = self.platform.monotonic_ns()
                return timestamp, probe_started, probe_completed, value

            def workload_health_probe() -> dict[str, Any]:
                if fault_injection_in_progress:
                    return {
                        "required": case["workload_state"] == "programme-audio",
                        "healthy": None,
                        "state": "fault-injection-in-progress",
                    }
                return workload.health()

            started.set()
            if sustained_cancelled.is_set():
                raise BenchmarkError("sustained collector was cancelled")
            deadline.check()
            batch_started = self.platform.monotonic_ns()
            batch_timestamp = self.platform.utc_now()
            probe_futures = (
                sustained_probe_executor.submit(timed_probe, workload_health_probe),
                sustained_probe_executor.submit(timed_probe, self.platform.sustained_sample),
                sustained_probe_executor.submit(timed_probe, self.platform.native_health),
                sustained_probe_executor.submit(
                    timed_probe, self.platform.event_storage_sample
                ),
            )
            (
                (_health_timestamp, health_started, health_completed, workload_health),
                (system_timestamp, system_started, system_completed, system),
                (native_timestamp, native_started, native_completed, native_health),
                (storage_timestamp, storage_started, storage_completed, event_storage),
            ) = tuple(future.result() for future in probe_futures)
            if sustained_cancelled.is_set():
                raise BenchmarkError("sustained collector was cancelled")
            deadline.check()
            system_document = {
                    "sampleId": f"{sample_id}-system-{sequence:06d}",
                    "sequence": sequence,
                    "timestampUtc": system_timestamp,
                    "monotonicNs": system_started,
                    "scheduledMonotonicNs": scheduled_ns,
                    "latenessNs": max(0, system_started - scheduled_ns),
                    "probeOverheadNs": system_completed - system_started,
                    "workloadHealth": redact_document(workload_health),
                    **system,
                }
            if sustained_cancelled.is_set():
                raise BenchmarkError("sustained collector was cancelled")
            deadline.check()
            native_document = {
                    "sampleId": f"{sample_id}-native-{sequence:06d}",
                    "sequence": sequence,
                    "timestampUtc": native_timestamp,
                    "monotonicNs": native_started,
                    "probeOverheadNs": native_completed - native_started,
                    **native_health,
                }
            if sustained_cancelled.is_set():
                raise BenchmarkError("sustained collector was cancelled")
            deadline.check()
            storage_document = {
                    "sampleId": f"{sample_id}-storage-{sequence:06d}",
                    "sequence": sequence,
                    "timestampUtc": storage_timestamp,
                    "monotonicNs": storage_started,
                    "probeOverheadNs": storage_completed - storage_started,
                    **event_storage,
                }
            deadline.check()
            return {
                "batchStartedNs": batch_started,
                "probeCompletedNs": self.platform.monotonic_ns(),
                "documents": (
                    ("system.jsonl", system_document),
                    ("native-health.jsonl", native_document),
                    ("event-storage.jsonl", storage_document),
                ),
                "interval": {
                    "sampleId": f"{sample_id}-collector-{sequence:06d}",
                    "sequence": sequence,
                    "timestampUtc": batch_timestamp,
                    "monotonicNs": batch_started,
                    "scheduledMonotonicNs": scheduled_ns,
                    "latenessNs": max(0, batch_started - scheduled_ns),
                    "componentProbeOverheadsNs": {
                        "workloadHealth": health_completed - health_started,
                        "system": system_completed - system_started,
                        "nativeHealth": native_completed - native_started,
                        "eventStorage": storage_completed - storage_started,
                    },
                },
            }

        def persist_sustained_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
            persistence_started = self.platform.monotonic_ns()
            for name, document in batch["documents"]:
                append_jsonl(sample_dir / str(name), document)
            persistence_completed = self.platform.monotonic_ns()
            interval = dict(batch["interval"])
            interval.update(
                {
                    "probeOverheadNs": int(batch["probeCompletedNs"])
                    - int(batch["batchStartedNs"]),
                    "persistenceOverheadNs": persistence_completed - persistence_started,
                    "collectorOverheadNs": persistence_completed
                    - int(batch["batchStartedNs"]),
                }
            )
            return interval

        def consume_sustained_batch(*, timeout: float | None = None) -> None:
            nonlocal sustained_future, sustained_wait_exhausted
            if sustained_future is None or (timeout is None and not sustained_future.done()):
                return
            future = sustained_future
            try:
                batch = future.result(timeout=timeout)
                sustained_persistence_futures.append(
                    sustained_persistence_executor.submit(persist_sustained_batch, batch)
                )
            except FutureTimeout as error:
                sustained_wait_exhausted = True
                raise CaseTimeout("sustained collector exceeded the case deadline") from error
            finally:
                if future.done():
                    sustained_future = None

        def consume_sustained_persistence(*, block: bool = False) -> None:
            nonlocal sustained_completed
            while sustained_persistence_futures and (
                block or sustained_persistence_futures[0].done()
            ):
                future = sustained_persistence_futures.popleft()
                timeout = deadline.remaining() if block else None
                try:
                    sustained_intervals.append(future.result(timeout=timeout))
                    sustained_completed += 1
                except FutureTimeout as error:
                    raise CaseTimeout(
                        "sustained persistence exceeded the case deadline"
                    ) from error

        def persist_transition(
            payload: Mapping[str, Any],
            *,
            sequence: int,
            scheduled_ns: int,
            collection_started: int,
            probe_completed: int,
        ) -> dict[str, Any]:
            append_jsonl(sample_dir / "transition.jsonl", payload)
            persistence_completed = self.platform.monotonic_ns()
            return {
                "sampleId": f"{sample_id}-transition-collector-{sequence:06d}",
                "sequence": sequence,
                "timestampUtc": self.platform.utc_now(),
                "monotonicNs": collection_started,
                "scheduledMonotonicNs": scheduled_ns,
                "latenessNs": max(0, collection_started - scheduled_ns),
                "probeOverheadNs": probe_completed - collection_started,
                "collectorOverheadNs": persistence_completed - collection_started,
            }

        def consume_transition_persistence(*, block: bool = False) -> None:
            while transition_futures and (block or transition_futures[0].done()):
                future = transition_futures.popleft()
                timeout = deadline.remaining() if block else None
                try:
                    transition_intervals.append(future.result(timeout=timeout))
                except FutureTimeout as error:
                    raise CaseTimeout(
                        "transition persistence exceeded the case deadline"
                    ) from error

        def persist_case_event(event: Mapping[str, Any]) -> dict[str, Any]:
            append_jsonl(sample_dir / "case-events.jsonl", event)
            return dict(event)

        def queue_case_event(event: Mapping[str, Any]) -> dict[str, Any]:
            document = dict(event)
            case_event_futures.append(
                transition_executor.submit(persist_case_event, document)
            )
            return document

        def consume_case_event_persistence(*, block: bool = False) -> None:
            while case_event_futures and (block or case_event_futures[0].done()):
                future = case_event_futures.popleft()
                timeout = deadline.remaining() if block else None
                try:
                    future.result(timeout=timeout)
                except FutureTimeout as error:
                    raise CaseTimeout(
                        "case-event persistence exceeded the case deadline"
                    ) from error

        def fault_event(event: str, **fields: Any) -> dict[str, Any]:
            return {
                "event": event,
                "timestampUtc": self.platform.utc_now(),
                "monotonicNs": self.platform.monotonic_ns(),
                **fields,
            }

        def inject_and_restore_workload() -> dict[str, Any]:
            results = self.platform.inject_services(services)
            fault_events.put(
                fault_event(
                    "fault-injection-complete",
                    results=redact_document(results),
                )
            )
            recovery = workload.after_fault_injection(list(services))
            health = workload.health()
            fault_events.put(
                fault_event(
                    "workload-restored-after-fault",
                    result=redact_document(recovery),
                )
            )
            return {"results": results, "recovery": recovery, "health": health}

        def execute_scheduled_transition(
            schedule_kind: str,
            schedule_index: int,
            scheduled_ns: int,
        ) -> dict[str, Any]:
            action = workload.transition(schedule_kind, schedule_index)
            health = workload.health()
            fault_events.put(
                fault_event(
                    "scheduled-transition-executed",
                    scheduleKind=schedule_kind,
                    scheduleIndex=schedule_index,
                    scheduledMonotonicNs=scheduled_ns,
                    result=redact_document(action),
                )
            )
            return {"action": action, "health": health}

        def drain_fault_events() -> None:
            nonlocal last_audio_marker
            while True:
                try:
                    event = fault_events.get_nowait()
                except Empty:
                    return
                last_audio_marker = queue_case_event(event)

        def consume_fault_injection(*, block: bool = False) -> None:
            nonlocal fault_future, injection_done
            drain_fault_events()
            if fault_future is None or (not block and not fault_future.done()):
                return
            timeout = deadline.remaining() if block else None
            try:
                fault_future.result(timeout=timeout)
            except FutureTimeout as error:
                raise CaseTimeout("fault injection exceeded the case deadline") from error
            fault_future = None
            injection_done = True
            drain_fault_events()

        def consume_scheduled_transition(*, block: bool = False) -> None:
            nonlocal scheduled_future
            drain_fault_events()
            if scheduled_future is None or (not block and not scheduled_future.done()):
                return
            timeout = deadline.remaining() if block else None
            try:
                scheduled_future.result(timeout=timeout)
            except FutureTimeout as error:
                raise CaseTimeout("scheduled transition exceeded the case deadline") from error
            scheduled_future = None
            drain_fault_events()

        collection_error: BaseException | None = None
        try:
            while self.platform.monotonic_ns() < end_ns:
                deadline.check()
                consume_sustained_batch()
                consume_sustained_persistence()
                consume_transition_persistence()
                consume_case_event_persistence()
                consume_fault_injection()
                consume_scheduled_transition()
                now = self.platform.monotonic_ns()
                if not injection_started and now >= injection_at:
                    last_audio_marker = queue_case_event(
                        fault_event("fault-injection-start", services=list(services))
                    )
                    fault_future = fault_executor.submit(inject_and_restore_workload)
                    injection_started = True
                    now = self.platform.monotonic_ns()
                while scheduled_index < len(scheduled) and now >= scheduled[scheduled_index]:
                    if scheduled_future is not None:
                        break
                    schedule_kind = case.get("transition_schedule_kind")
                    last_audio_marker = queue_case_event(
                        fault_event(
                            "scheduled-transition-start",
                            scheduleKind=schedule_kind,
                            scheduleIndex=scheduled_index,
                            scheduledMonotonicNs=scheduled[scheduled_index],
                        )
                    )
                    scheduled_future = scheduled_executor.submit(
                        execute_scheduled_transition,
                        str(schedule_kind),
                        scheduled_index,
                        scheduled[scheduled_index],
                    )
                    scheduled_index += 1
                    now = self.platform.monotonic_ns()
                if now >= end_ns:
                    break
                if now >= next_transition:
                    lateness = max(0, now - next_transition)
                    missed = lateness // transition_ns
                    transition_missed += missed
                    transition_sequence += int(missed)
                    collection_started = self.platform.monotonic_ns()
                    sample = self.platform.transition_sample()
                    sample["audioRestorationMarker"] = last_audio_marker
                    observed_topology = sample.get("pipewire", {})
                    final_topology_converged = observed_topology.get(
                        "digest"
                    ) == expected_topology.get("digest")
                    final_processors_ready = bool(sample.get("processorReadiness", {}).get("ready"))
                    sample["expectedOwnedTopology"] = expected_topology
                    sample["exactOwnedTopologyConverged"] = final_topology_converged
                    probe_completed = self.platform.monotonic_ns()
                    sequence = transition_sequence + 1
                    scheduled_ns = next_transition + missed * transition_ns
                    payload = {
                        "sampleId": f"{sample_id}-transition-{sequence:06d}",
                        "sequence": sequence,
                        "timestampUtc": self.platform.utc_now(),
                        "monotonicNs": collection_started,
                        "scheduledMonotonicNs": scheduled_ns,
                        "latenessNs": lateness,
                        "probeOverheadNs": probe_completed - collection_started,
                        **sample,
                    }
                    transition_futures.append(
                        transition_executor.submit(
                            persist_transition,
                            payload,
                            sequence=sequence,
                            scheduled_ns=scheduled_ns,
                            collection_started=collection_started,
                            probe_completed=probe_completed,
                        )
                    )
                    transition_sequence += 1
                    transition_completed += 1
                    next_transition += (missed + 1) * transition_ns
                    deadline.check()
                    now = self.platform.monotonic_ns()
                if now >= end_ns:
                    break
                consume_sustained_batch()
                now = self.platform.monotonic_ns()
                if now >= next_sustained:
                    # Recheck at the scheduling decision boundary. The worker may
                    # have completed after the earlier poll in this loop.
                    consume_sustained_batch()
                    now = self.platform.monotonic_ns()
                if now >= next_sustained:
                    due = ((now - next_sustained) // sustained_ns) + 1
                    if sustained_future is not None:
                        sustained_missed += due
                        sustained_sequence += int(due)
                        next_sustained += due * sustained_ns
                    else:
                        missed = due - 1
                        sustained_missed += missed
                        sustained_sequence += int(missed) + 1
                        scheduled_ns = next_sustained + missed * sustained_ns
                        next_sustained += due * sustained_ns
                        deadline.check()
                        worker_started = threading.Event()
                        sustained_future = sustained_executor.submit(
                            collect_sustained_batch,
                            worker_started,
                            sustained_sequence,
                            scheduled_ns,
                            fault_future is not None or scheduled_future is not None,
                        )
                        start_timeout = min(1.0, deadline.remaining())
                        if not worker_started.wait(timeout=start_timeout):
                            raise CaseTimeout("sustained collector did not start before deadline")
                next_due = min(next_sustained, next_transition, end_ns)
                sleep_seconds = (next_due - self.platform.monotonic_ns()) / 1_000_000_000
                if sleep_seconds > 0:
                    self.platform.sleep(min(sleep_seconds, deadline.remaining()))
            consume_sustained_batch(timeout=deadline.remaining())
            consume_sustained_persistence(block=True)
            consume_transition_persistence(block=True)
            consume_fault_injection(block=True)
            consume_scheduled_transition(block=True)
            consume_case_event_persistence(block=True)
        except BaseException as error:
            collection_error = error
            raise
        finally:
            sustained_cancelled.set()
            worker_error: BaseException | None = None
            sustained_persistence_worker_error: BaseException | None = None
            transition_worker_error: BaseException | None = None
            case_event_worker_error: BaseException | None = None
            fault_worker_error: BaseException | None = None
            scheduled_worker_error: BaseException | None = None
            drain_remaining = deadline.remaining()
            drain_deadline_exhausted = sustained_wait_exhausted or (
                drain_remaining == 0
                and (
                    sustained_future is not None
                    or bool(sustained_persistence_futures)
                )
            )
            try:
                future = sustained_future
                if future is not None:
                    try:
                        # A running thread cannot be cancelled safely. Join it even
                        # after the case deadline so cleanup/restoration never races
                        # a collector or a durability write.
                        batch = future.result()
                        sustained_persistence_futures.append(
                            sustained_persistence_executor.submit(
                                persist_sustained_batch, batch
                            )
                        )
                    except BaseException as error:
                        worker_error = error
                    sustained_future = None
            finally:
                sustained_executor.shutdown(wait=True, cancel_futures=True)
                sustained_probe_executor.shutdown(wait=True, cancel_futures=True)
                sustained_persistence_executor.shutdown(
                    wait=True, cancel_futures=False
                )
                while sustained_persistence_futures:
                    future = sustained_persistence_futures.popleft()
                    try:
                        sustained_intervals.append(future.result())
                        sustained_completed += 1
                    except BaseException as error:
                        if sustained_persistence_worker_error is None:
                            sustained_persistence_worker_error = error
                fault_executor.shutdown(wait=True, cancel_futures=False)
                if fault_future is not None:
                    try:
                        fault_future.result()
                    except BaseException as error:
                        fault_worker_error = error
                    fault_future = None
                scheduled_executor.shutdown(wait=True, cancel_futures=False)
                if scheduled_future is not None:
                    try:
                        scheduled_future.result()
                    except BaseException as error:
                        scheduled_worker_error = error
                    scheduled_future = None
                drain_fault_events()
                transition_executor.shutdown(wait=True, cancel_futures=False)
                while transition_futures:
                    future = transition_futures.popleft()
                    try:
                        transition_intervals.append(future.result())
                    except BaseException as error:
                        if transition_worker_error is None:
                            transition_worker_error = error
                while case_event_futures:
                    future = case_event_futures.popleft()
                    try:
                        future.result()
                    except BaseException as error:
                        if case_event_worker_error is None:
                            case_event_worker_error = error
            drain_deadline_exhausted = drain_deadline_exhausted or (
                drain_remaining > 0 and deadline.remaining() == 0
            )
            if drain_deadline_exhausted:
                self._emit_event(
                    sample_dir,
                    "sustained-collector-drain-timeout",
                    remainingDeadlineSeconds=drain_remaining,
                    workerJoined=True,
                )
            if worker_error is not None:
                if collection_error is None:
                    raise worker_error
                collection_error.add_note(
                    f"sustained collector also failed while draining: {worker_error}"
                )
            if sustained_persistence_worker_error is not None:
                if collection_error is None:
                    raise sustained_persistence_worker_error
                collection_error.add_note(
                    "sustained persistence also failed while draining: "
                    f"{sustained_persistence_worker_error}"
                )
            if transition_worker_error is not None:
                if collection_error is None:
                    raise transition_worker_error
                collection_error.add_note(
                    "transition persistence also failed while draining: "
                    f"{transition_worker_error}"
                )
            if case_event_worker_error is not None:
                if collection_error is None:
                    raise case_event_worker_error
                collection_error.add_note(
                    "case-event persistence also failed while draining: "
                    f"{case_event_worker_error}"
                )
            if fault_worker_error is not None:
                if collection_error is None:
                    raise fault_worker_error
                collection_error.add_note(
                    f"fault injection also failed while draining: {fault_worker_error}"
                )
            if scheduled_worker_error is not None:
                if collection_error is None:
                    raise scheduled_worker_error
                collection_error.add_note(
                    "scheduled transition also failed while draining: "
                    f"{scheduled_worker_error}"
                )
        for interval in sustained_intervals:
            append_jsonl(sample_dir / "collector-batches.jsonl", interval)
        for interval in transition_intervals:
            append_jsonl(sample_dir / "transition-batches.jsonl", interval)
        if not injection_done:
            raise BenchmarkError("case ended before its bounded fault injection")
        self._emit_event(sample_dir, "measurement-complete", sampleId=sample_id)
        deadline.check()
        return {
            "sustainedSamples": sustained_completed,
            "transitionSamples": transition_completed,
            "sustainedMissed": sustained_missed,
            "transitionMissed": transition_missed,
            "scheduledTransitionsObserved": scheduled_index,
            "scheduledTransitionsExpected": len(scheduled),
            "finalTopologyConverged": final_topology_converged,
            "finalProcessorsReady": final_processors_ready,
        }

    @staticmethod
    def _status_for_exception(error: BaseException) -> tuple[str, str]:
        if isinstance(error, CaseTimeout):
            return "invalid", "timeout"
        if isinstance(error, (InterruptedCase, KeyboardInterrupt)):
            return "interrupted", "interrupted"
        if isinstance(error, RestorationError):
            return "failed", "restoration-failed"
        return "failed", type(error).__name__

    @contextmanager
    def _signal_guard(self) -> Iterator[None]:
        previous: dict[int, Any] = {}

        def interrupted(signum: int, _frame: object) -> None:
            raise InterruptedCase(signal.Signals(signum).name)

        if hasattr(signal, "SIGTERM") and threading_is_main():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupted)
        try:
            yield
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def run_case(self, run_id: str, case_id: str, *, resume: bool = False) -> str:
        state = self._load_state(run_id)
        if state["finalized"]:
            raise BenchmarkError("a finalized run is immutable")
        if case_id not in state["cases"]:
            raise BenchmarkError(f"case was not selected at prepare: {case_id}")
        snapshot = json.loads(
            (self.run_dir(run_id) / "restore-snapshot.json").read_text(encoding="utf-8")
        )
        if resume and hasattr(self.platform, "restore_workload_journals"):
            recovered = self.platform.restore_workload_journals(self.run_dir(run_id))
            if recovered.get("activeJournalCount"):
                self.platform.restore(snapshot, timeout_seconds=60)
                write_json(self.run_dir(run_id) / "resume-workload-restoration.json", recovered)
        self._assert_prepared_identity(state)
        case = self.contracts.case(case_id)
        case_state = state["cases"][case_id]
        if case_state["status"] == "fixture-unavailable":
            return "fixture-unavailable"
        if case_state["status"] in {"characterized", "passed", "not-measured"}:
            if resume:
                return case_state["status"]
            raise BenchmarkError("case already completed; use --resume to make this idempotent")
        if case_state["status"] not in {"pending", "failed", "invalid", "interrupted", "running"}:
            raise BenchmarkError(f"case cannot be resumed from {case_state['status']}")
        if case_state["status"] != "pending" and not resume:
            raise BenchmarkError("failed or interrupted cases require --resume")
        units = self._execution_units(case)
        case_dir = self.run_dir(run_id) / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        state["status"] = "running"
        case_state["status"] = "running"
        self._save_state(state)
        try:
            with self._signal_guard():
                for unit_index in range(int(case_state["nextUnit"]), len(units)):
                    unit = units[unit_index]
                    attempts = case_state.setdefault("attemptsByUnit", {})
                    attempt_key = str(unit_index)
                    attempt = int(attempts.get(attempt_key, 0)) + 1
                    attempts[attempt_key] = attempt
                    # Persist the allocation before creating the immutable attempt
                    # directory. A crash between those operations must resume with
                    # a new attempt ID rather than collide with or overwrite evidence.
                    self._save_state(state)
                    sample_id = self._attempt_sample_id(case_id, unit_index, attempt)
                    sample_dir = case_dir / sample_id
                    if sample_dir.exists():
                        raise BenchmarkError(
                            f"immutable sample attempt already exists: {sample_id}"
                        )
                    sample_dir.mkdir(parents=True, mode=0o750)
                    started = {
                        **unit,
                        "unitIndex": unit_index,
                        "attempt": attempt,
                        "implementationIdentity": state["implementationIdentity"],
                        "startedUtc": self.platform.utc_now(),
                        "startedMonotonicNs": self.platform.monotonic_ns(),
                    }
                    write_json(sample_dir / "sample-manifest.json", started)
                    deadline = Deadline(self.platform, float(case["timeout_seconds"]))
                    restoration: dict[str, Any] = {"status": "not-required"}
                    invalid_reasons: list[str] = []
                    status = "running"
                    workload_stop_failed = False
                    workload = self._workload_driver(
                        state=state,
                        case=case,
                        unit=unit,
                        sample_dir=sample_dir,
                    )
                    try:
                        workload_result = workload.start()
                        self._emit_event(
                            sample_dir,
                            "workload-started",
                            result=redact_document(workload_result),
                        )
                        deadline.check()
                        collection = self._collect(
                            case=case,
                            sample_id=sample_id,
                            sample_dir=sample_dir,
                            services=unit["services"],
                            expected_topology=snapshot["topology"],
                            deadline=deadline,
                            workload=workload,
                        )
                        write_json(sample_dir / "collection-result.json", collection)
                        maximum_loss = int(
                            self._criteria(case)
                            .get("thresholds", {})
                            .get("collector_sample_loss_maximum", 0)
                        )
                        if (
                            collection["sustainedMissed"] > maximum_loss
                            or collection["transitionMissed"] > maximum_loss
                        ):
                            invalid_reasons.append("collector-sample-loss")
                        if (
                            collection["scheduledTransitionsObserved"]
                            != collection["scheduledTransitionsExpected"]
                        ):
                            invalid_reasons.append("scheduled-transition-missing")
                        if not collection["finalTopologyConverged"]:
                            invalid_reasons.append("final-topology-not-converged")
                        if not collection["finalProcessorsReady"]:
                            invalid_reasons.append("final-processors-not-ready")
                        status = (
                            "invalid"
                            if invalid_reasons
                            else (
                                "passed"
                                if state["campaignMode"] == "acceptance"
                                else "characterized"
                            )
                        )
                    except BaseException as error:
                        status, reason = self._status_for_exception(error)
                        invalid_reasons.append(reason)
                        write_json(
                            sample_dir / "failure.json",
                            {
                                "type": type(error).__name__,
                                "message": str(error),
                                "traceback": traceback.format_exc(),
                                "timestampUtc": self.platform.utc_now(),
                                "monotonicNs": self.platform.monotonic_ns(),
                            },
                        )
                    finally:
                        workload_mutated = bool(workload.requires_restoration)
                        try:
                            stopped_workload = workload.stop()
                            self._emit_event(
                                sample_dir,
                                "workload-stopped",
                                result=redact_document(stopped_workload),
                            )
                        except BaseException as workload_stop_error:
                            workload_stop_failed = True
                            invalid_reasons.append("workload-restoration-failed")
                            status = "failed"
                            write_json(
                                sample_dir / "workload-restoration-failure.json",
                                {
                                    "type": type(workload_stop_error).__name__,
                                    "message": str(workload_stop_error),
                                    "traceback": traceback.format_exc(),
                                },
                            )
                        disruptive = bool(
                            self.contracts.cases["restoration_actions"][case["restoration_action"]][
                                "disruptive"
                            ]
                            or unit["services"]
                            or workload_mutated
                            or workload_stop_failed
                        )
                        restoration["required"] = disruptive
                        if disruptive:
                            try:
                                workload_restoration = None
                                if hasattr(self.platform, "restore_workload_journals"):
                                    workload_restoration = self.platform.restore_workload_journals(
                                        self.run_dir(run_id)
                                    )
                                restored = self.platform.restore(
                                    snapshot,
                                    timeout_seconds=min(60, float(case["timeout_seconds"])),
                                )
                                if workload_restoration is not None:
                                    restored = {
                                        **restored,
                                        "workloadRestoration": workload_restoration,
                                    }
                                restoration = {"status": "restored", **restored}
                                case_state["restorationStatus"] = "restored"
                            except BaseException as restore_error:
                                restoration = {
                                    "status": "failed",
                                    "error": str(restore_error),
                                    "topologyVerified": False,
                                }
                                case_state["restorationStatus"] = "failed"
                                invalid_reasons.append("restoration-failed")
                                status = "failed"
                                write_json(
                                    sample_dir / "restoration-failure.json",
                                    {
                                        "type": type(restore_error).__name__,
                                        "message": str(restore_error),
                                        "traceback": traceback.format_exc(),
                                    },
                                )
                        try:
                            workload_artifacts = self._normalized_workload_artifacts(
                                sample_dir, workload.artifacts()
                            )
                        except BaseException as artifact_error:
                            workload_artifacts = {"logs": [], "captures": []}
                            invalid_reasons.append("workload-artifact-contract-failed")
                            status = "failed"
                            write_json(
                                sample_dir / "workload-artifact-failure.json",
                                {
                                    "type": type(artifact_error).__name__,
                                    "message": str(artifact_error),
                                    "traceback": traceback.format_exc(),
                                },
                            )
                        metric_coverage = self._metric_coverage(
                            run_dir=self.run_dir(run_id),
                            sample_dir=sample_dir,
                            case=case,
                            artifacts=workload_artifacts,
                        )
                        missing_metrics = sorted(
                            metric_set
                            for metric_set, coverage in metric_coverage.items()
                            if coverage["status"] == "missing"
                        )
                        not_measured_metrics = sorted(
                            metric_set
                            for metric_set, coverage in metric_coverage.items()
                            if coverage["status"] == "not-measured"
                        )
                        invalid_reasons.extend(
                            f"required-metric-missing:{metric_set}"
                            for metric_set in missing_metrics
                        )
                        invalid_reasons.extend(
                            f"required-metric-not-measured:{metric_set}"
                            for metric_set in not_measured_metrics
                        )
                        if status in {"characterized", "passed"}:
                            if missing_metrics:
                                status = "invalid"
                            elif not_measured_metrics:
                                status = "not-measured"
                                case_state["notMeasured"] = True
                        completed = {
                            **started,
                            "completedUtc": self.platform.utc_now(),
                            "completedMonotonicNs": self.platform.monotonic_ns(),
                        }
                        envelope = self._envelope(
                            state=state,
                            case=case,
                            sample_id=sample_id,
                            unit=completed,
                            status=status,
                            invalid=status == "invalid",
                            reasons=invalid_reasons,
                            restoration=restoration,
                            workload_artifacts=workload_artifacts,
                            metric_coverage=metric_coverage,
                        )
                        write_json(sample_dir / "evidence-envelope.json", envelope)
                        case_state["sampleIds"] = list(
                            dict.fromkeys([*case_state["sampleIds"], sample_id])
                        )
                        if status in {"characterized", "passed", "not-measured"}:
                            case_state["nextUnit"] = unit_index + 1
                        else:
                            case_state["status"] = status
                        self._save_state(state)
                    if status not in {"characterized", "passed", "not-measured"}:
                        message = (
                            f"case {case_id} sample {sample_id} ended with {status}: "
                            f"{', '.join(invalid_reasons)}"
                        )
                        if status == "interrupted":
                            raise InterruptedCase(message)
                        if "timeout" in invalid_reasons:
                            raise CaseTimeout(message)
                        raise BenchmarkError(message)
        except BaseException:
            if case_state["status"] == "running":
                case_state["status"] = "failed"
            state["status"] = "incomplete"
            self._save_state(state)
            raise
        case_state["status"] = (
            "not-measured"
            if case_state.get("notMeasured")
            else ("passed" if state["campaignMode"] == "acceptance" else "characterized")
        )
        state["status"] = "incomplete"
        self._save_state(state)
        return case_state["status"]

    def restore(self, run_id: str) -> dict[str, Any]:
        state = self._load_state(run_id)
        snapshot = json.loads(
            (self.run_dir(run_id) / "restore-snapshot.json").read_text(encoding="utf-8")
        )
        workload_result = (
            self.platform.restore_workload_journals(self.run_dir(run_id))
            if hasattr(self.platform, "restore_workload_journals")
            else {"activeJournalCount": 0}
        )
        result = self.platform.restore(snapshot, timeout_seconds=60)
        result = {**result, "workloadRestoration": workload_result}
        write_json(self.run_dir(run_id) / "manual-restoration.json", result)
        for case_state in state["cases"].values():
            if case_state["status"] in {"running", "interrupted", "failed", "invalid"}:
                case_state["restorationStatus"] = "restored"
        self._save_state(state)
        return result

    @staticmethod
    def _artifact_paths(envelope: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        yield from envelope["timeSeries"]
        yield from envelope["logs"]
        yield from envelope["captures"]

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows = []
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def _evaluate_sample_criteria(
        self, run_dir: Path, envelope: Mapping[str, Any]
    ) -> dict[str, Any]:
        case = self.contracts.case(str(envelope["caseId"]))
        thresholds = self._criteria(case).get("thresholds", {})
        sample_dir = run_dir / "cases" / envelope["caseId"] / envelope["sampleId"]
        system_rows = self._read_jsonl(sample_dir / "system.jsonl")
        native_rows = self._read_jsonl(sample_dir / "native-health.jsonl")
        reasons = []
        expected_throttling = thresholds.get("current_throttling")
        observed_throttling = sorted(
            {str(row.get("throttling")) for row in system_rows if row.get("throttling")}
        )
        if expected_throttling and any(
            value != expected_throttling for value in observed_throttling
        ):
            reasons.append("throttling-precondition-failed")
        temperatures = [
            float(row["temperatureCelsius"])
            for row in system_rows
            if isinstance(row.get("temperatureCelsius"), (int, float))
        ]
        maximum_temperature = max(temperatures, default=None)
        temperature_limit = thresholds.get("maximum_temperature_celsius")
        if (
            maximum_temperature is not None
            and isinstance(temperature_limit, (int, float))
            and maximum_temperature > float(temperature_limit)
        ):
            reasons.append("maximum-temperature-exceeded")
        counter_state: dict[tuple[int, str], tuple[int, int]] = {}
        observed_increment = 0
        for row in native_rows:
            for node in row.get("pipewireObjects", []):
                key = (int(node["nodeId"]), str(node["name"]))
                value = int(node["errors"])
                if key not in counter_state:
                    counter_state[key] = (value, value)
                    continue
                first, previous = counter_state[key]
                observed_increment += value - previous if value >= previous else value
                counter_state[key] = (first, value)
        error_limit = thresholds.get("programme_audio_pipewire_error_increment_maximum")
        if (
            case["workload_state"] == "programme-audio"
            and isinstance(error_limit, int)
            and observed_increment > error_limit
        ):
            reasons.append("programme-audio-pipewire-errors-increased")
        result = {
            "criteriaSet": case["criteria_set"],
            "campaignMode": self._criteria(case)["campaign_mode"],
            "evaluated": {
                "expectedThrottling": expected_throttling,
                "observedThrottling": observed_throttling,
                "maximumTemperatureCelsius": maximum_temperature,
                "maximumTemperatureLimitCelsius": temperature_limit,
                "pipewireObservedIncrementErrors": observed_increment,
                "pipewireIncrementLimit": error_limit,
            },
            "valid": not reasons,
            "reasons": reasons,
        }
        write_json(sample_dir / "criteria-result.json", result)
        return result

    def _finalize_sample(self, run_dir: Path, envelope_path: Path) -> dict[str, Any]:
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        sample_dir = envelope_path.parent
        criteria_result = self._evaluate_sample_criteria(run_dir, envelope)
        relative_criteria = str((sample_dir / "criteria-result.json").relative_to(run_dir))
        if not any(item["path"] == relative_criteria for item in envelope["logs"]):
            envelope["logs"].append({"path": relative_criteria, "sha256": None})
        if not criteria_result["valid"]:
            envelope["invalidation"]["invalid"] = True
            envelope["invalidation"]["reasons"].extend(criteria_result["reasons"])
            envelope["status"] = "invalid"
        checksums = []
        for artifact in self._artifact_paths(envelope):
            path = run_dir / artifact["path"]
            if not path.is_file():
                envelope["invalidation"]["invalid"] = True
                envelope["invalidation"]["reasons"].append(f"missing-artifact:{artifact['path']}")
                envelope["status"] = "invalid"
                continue
            artifact["sha256"] = sha256_file(path)
            checksums.append((artifact["sha256"], str(path.relative_to(sample_dir))))
        checksums.sort(key=lambda item: item[1])
        checksum_path = sample_dir / "SHA256SUMS"
        atomic_write(
            checksum_path,
            "".join(f"{digest}  {path}\n" for digest, path in checksums),
        )
        envelope["checksums"]["manifestSha256"] = sha256_file(checksum_path)
        if envelope["restoration"]["required"] and envelope["restoration"]["status"] != "restored":
            envelope["invalidation"]["invalid"] = True
            envelope["invalidation"]["reasons"].append("restoration-incomplete")
            envelope["status"] = "invalid"
        if envelope["invalidation"]["invalid"] and envelope["status"] in {
            "passed",
            "characterized",
        }:
            envelope["status"] = "invalid"
        envelope["invalidation"]["reasons"] = sorted(set(envelope["invalidation"]["reasons"]))
        write_json(envelope_path, envelope)
        validate_json(envelope, self.contracts.evidence_schema_path)
        return envelope

    @staticmethod
    def _metric_values(
        run_dir: Path, envelopes: Sequence[Mapping[str, Any]]
    ) -> dict[str, list[float]]:
        values: dict[str, list[float]] = {
            "temperatureCelsius": [],
            "applianceCpuPercent": [],
            "availableMemoryKb": [],
            "sustainedCollectorOverheadMs": [],
            "transitionCollectorOverheadMs": [],
            "transitionLatenessMs": [],
        }
        for envelope in envelopes:
            if envelope["status"] not in {"characterized", "passed"}:
                continue
            sample_manifest = (
                run_dir
                / "cases"
                / envelope["caseId"]
                / envelope["sampleId"]
                / "sample-manifest.json"
            )
            if sample_manifest.is_file() and json.loads(sample_manifest.read_text())["warmUp"]:
                continue
            for artifact in envelope["timeSeries"]:
                if not artifact["path"].endswith(
                    (
                        "system.jsonl",
                        "collector-batches.jsonl",
                        "transition-batches.jsonl",
                        "transition.jsonl",
                    )
                ):
                    continue
                with (run_dir / artifact["path"]).open(encoding="utf-8") as stream:
                    for line in stream:
                        row = json.loads(line)
                        if artifact["path"].endswith("system.jsonl"):
                            for key in (
                                "temperatureCelsius",
                                "applianceCpuPercent",
                                "availableMemoryKb",
                            ):
                                if isinstance(row.get(key), (int, float)):
                                    values[key].append(float(row[key]))
                        elif artifact["path"].endswith("collector-batches.jsonl"):
                            if isinstance(row.get("collectorOverheadNs"), (int, float)):
                                values["sustainedCollectorOverheadMs"].append(
                                    float(row["collectorOverheadNs"]) / 1_000_000
                                )
                        elif artifact["path"].endswith("transition-batches.jsonl"):
                            if isinstance(row.get("collectorOverheadNs"), (int, float)):
                                values["transitionCollectorOverheadMs"].append(
                                    float(row["collectorOverheadNs"]) / 1_000_000
                                )
                        elif isinstance(row.get("latenessNs"), (int, float)):
                            values["transitionLatenessMs"].append(
                                float(row["latenessNs"]) / 1_000_000
                            )
        return values

    @staticmethod
    def _copy_redacted(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in {".json", ".jsonl"}:
            if source.suffix == ".json":
                value = json.loads(source.read_text(encoding="utf-8"))
                write_json(destination, redact_document(value))
            else:
                lines = []
                for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
                    lines.append(
                        json.dumps(
                            redact_document(json.loads(line)),
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                atomic_write(destination, "\n".join(lines) + ("\n" if lines else ""))
        elif source.suffix in {".yml", ".yaml"}:
            value = yaml.safe_load(source.read_text(encoding="utf-8"))
            atomic_write(destination, yaml.safe_dump(redact_document(value), sort_keys=True))
        else:
            atomic_write(
                destination,
                redact_string(source.read_text(encoding="utf-8", errors="replace")),
            )

    def finalize(self, run_id: str) -> dict[str, Any]:
        state = self._load_state(run_id)
        if state["finalized"]:
            return json.loads((self.run_dir(run_id) / "summary.json").read_text(encoding="utf-8"))
        self._assert_prepared_identity(state)
        run_dir = self.run_dir(run_id)
        envelopes = [
            self._finalize_sample(run_dir, path)
            for path in sorted((run_dir / "cases").glob("*/*/evidence-envelope.json"))
        ]
        effective_envelopes: list[dict[str, Any]] = []
        for case_id, case_state in state["cases"].items():
            case_envelopes = [envelope for envelope in envelopes if envelope["caseId"] == case_id]
            latest_by_unit: dict[int, tuple[int, dict[str, Any]]] = {}
            for envelope in case_envelopes:
                manifest_path = (
                    run_dir / "cases" / case_id / str(envelope["sampleId"]) / "sample-manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                unit_index = int(manifest.get("unitIndex", 0))
                attempt = int(manifest.get("attempt", 1))
                if unit_index not in latest_by_unit or attempt > latest_by_unit[unit_index][0]:
                    latest_by_unit[unit_index] = (attempt, envelope)
            effective_envelopes.extend(envelope for _attempt, envelope in latest_by_unit.values())
            invalid_latest = [
                unit_index
                for unit_index, (_attempt, envelope) in latest_by_unit.items()
                if envelope["status"] in {"invalid", "failed", "interrupted"}
            ]
            if invalid_latest:
                case_state["status"] = "invalid"
                case_state["nextUnit"] = min(invalid_latest)
        incomplete = {
            case_id: case_state["status"]
            for case_id, case_state in state["cases"].items()
            if case_state["status"]
            not in {
                "characterized",
                "passed",
                "not-measured",
                "fixture-unavailable",
            }
        }
        has_not_measured_case = any(
            case_state["status"] == "not-measured" for case_state in state["cases"].values()
        )
        accepted = (
            state["campaignMode"] == "acceptance"
            and not incomplete
            and bool(effective_envelopes)
            and all(case_state["status"] == "passed" for case_state in state["cases"].values())
            and all(envelope["status"] == "passed" for envelope in effective_envelopes)
            and all(
                not envelope["restoration"]["required"]
                or envelope["restoration"]["status"] == "restored"
                for envelope in effective_envelopes
            )
        )
        if incomplete:
            overall = "incomplete"
        elif accepted:
            overall = "accepted"
        elif has_not_measured_case:
            overall = "not-measured"
        elif state["campaignMode"] == "characterization":
            overall = "characterized"
        else:
            overall = "not-accepted"
        metrics = {
            key: summary_statistics(samples) if samples else {"count": 0}
            for key, samples in self._metric_values(run_dir, effective_envelopes).items()
        }
        effective_sample_ids = {envelope["sampleId"] for envelope in effective_envelopes}
        superseded_envelopes = [
            envelope for envelope in envelopes if envelope["sampleId"] not in effective_sample_ids
        ]
        case_statuses = {
            case_id: case_state["status"] for case_id, case_state in sorted(state["cases"].items())
        }
        summary = {
            "schemaVersion": 1,
            "runId": run_id,
            "campaignMode": state["campaignMode"],
            "overallStatus": overall,
            "accepted": accepted,
            "caseStatuses": case_statuses,
            "incompleteCases": incomplete,
            "validSampleCount": sum(
                envelope["status"] in {"characterized", "passed"}
                for envelope in effective_envelopes
            ),
            "invalidSampleCount": sum(
                envelope["status"] == "invalid" for envelope in effective_envelopes
            ),
            "notMeasuredSampleCount": sum(
                envelope["status"] == "not-measured" for envelope in effective_envelopes
            ),
            "totalAttemptCount": len(envelopes),
            "supersededAttemptCount": len(superseded_envelopes),
            "supersededInvalidAttemptCount": sum(
                envelope["status"] in {"invalid", "failed", "interrupted"}
                for envelope in superseded_envelopes
            ),
            "statistics": metrics,
            "completedUtc": self.platform.utc_now(),
            "completedMonotonicNs": self.platform.monotonic_ns(),
        }
        write_json(run_dir / "summary.json", summary)
        lines = [
            f"# Benchmark run {run_id}",
            "",
            f"Overall status: **{overall}**",
            "",
            "| Case | Status |",
            "| --- | --- |",
            *(f"| `{case_id}` | {status} |" for case_id, status in case_statuses.items()),
            "",
            (
                "Characterization is not platform acceptance."
                if state["campaignMode"] == "characterization"
                else ""
            ),
        ]
        atomic_write(run_dir / "summary.md", "\n".join(lines).rstrip() + "\n")
        marker = json.loads((run_dir / "journal-marker.json").read_text(encoding="utf-8"))
        journal = self.platform.journal_since(marker, RUNTIME_SERVICES)
        atomic_write(run_dir / "scoped-journal.txt", journal)
        state["status"] = overall
        state["finalized"] = not incomplete
        if not incomplete:
            state["finalizedUtc"] = summary["completedUtc"]
        self._save_state(state)
        export = run_dir / "export"
        if export.exists():
            shutil.rmtree(export)
        for source in sorted(run_dir.rglob("*")):
            if not source.is_file() or export in source.parents:
                continue
            relative = source.relative_to(run_dir)
            if (
                source.suffix in {".json", ".jsonl", ".yml", ".yaml", ".txt", ".md", ".csv", ".log"}
                or source.name == "SHA256SUMS"
            ):
                self._copy_redacted(source, export / relative)
        covered_files = [path for path in sorted(export.rglob("*")) if path.is_file()]
        write_json(
            export / "export-manifest.json",
            {
                "algorithm": "sha256",
                "filesCoveredBySha256Sums": len(covered_files) + 1,
                "manifestPath": "SHA256SUMS",
                "manifestDigestPath": "SHA256SUMS.sha256",
                "excludedFromSha256Sums": ["SHA256SUMS", "SHA256SUMS.sha256"],
            },
        )
        checksum_entries = []
        checksum_manifest = export / "SHA256SUMS"
        checksum_manifest_digest = export / "SHA256SUMS.sha256"
        for path in sorted(export.rglob("*")):
            if path.is_file() and path not in {
                checksum_manifest,
                checksum_manifest_digest,
            }:
                checksum_entries.append((sha256_file(path), path.relative_to(export).as_posix()))
        atomic_write(
            checksum_manifest,
            "".join(f"{digest}  {path}\n" for digest, path in checksum_entries),
        )
        atomic_write(
            checksum_manifest_digest,
            f"{sha256_file(checksum_manifest)}  SHA256SUMS\n",
        )
        if incomplete:
            raise BenchmarkError(f"run has incomplete cases: {incomplete}")
        return summary


def threading_is_main() -> bool:
    return threading.current_thread() is threading.main_thread()


def build_runner(arguments: argparse.Namespace) -> BenchmarkRunner:
    contracts = Contracts.load(arguments.contracts.resolve())
    result_root = arguments.result_root.resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    platform = LinuxPlatform(
        audio_user=arguments.audio_user,
        database_path=arguments.database.resolve(),
        result_root=result_root,
        runtime_redis_key=arguments.runtime_redis_key,
        static_paths=[Path(path) for path in arguments.static_path],
        venv_python=arguments.venv_python,
        app_path=arguments.app_path,
        intent_adapter=arguments.intent_adapter,
        benchmark_contracts_root=arguments.contracts.resolve(),
        camilladsp_host=arguments.camilladsp_host,
        camilladsp_port=arguments.camilladsp_port,
    )
    return BenchmarkRunner(contracts=contracts, result_root=result_root, platform=platform)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--contracts",
        type=Path,
        default=Path(
            os.environ.get(
                "OPEN_CINEMA_BENCHMARK_CONTRACTS", "/usr/local/share/open-cinema/benchmarks"
            )
        ),
    )
    result.add_argument(
        "--result-root",
        type=Path,
        default=Path(
            os.environ.get("OPEN_CINEMA_BENCHMARK_ROOT", "/var/lib/open-cinema/benchmark-results")
        ),
    )
    result.add_argument(
        "--database",
        type=Path,
        default=Path(
            os.environ.get("OPEN_CINEMA_DATABASE_PATH", "/opt/home-cinema/open-cinema/db.sqlite3")
        ),
    )
    result.add_argument(
        "--audio-user", default=os.environ.get("OPEN_CINEMA_AUDIO_USER", "opencinema")
    )
    result.add_argument(
        "--venv-python",
        type=Path,
        default=Path(
            os.environ.get(
                "OPEN_CINEMA_VENV_PYTHON",
                "/opt/home-cinema/open-cinema/venv/bin/python",
            )
        ),
    )
    result.add_argument(
        "--app-path",
        type=Path,
        default=Path(os.environ.get("OPEN_CINEMA_APP_PATH", "/opt/home-cinema/open-cinema")),
    )
    result.add_argument(
        "--intent-adapter",
        type=Path,
        default=Path(
            os.environ.get(
                "OPEN_CINEMA_INTENT_ADAPTER",
                "/usr/local/libexec/open-cinema-benchmark-intent-adapter",
            )
        ),
    )
    result.add_argument(
        "--camilladsp-host",
        default=os.environ.get("OPEN_CINEMA_CAMILLADSP_HOST", "127.0.0.1"),
    )
    result.add_argument(
        "--camilladsp-port",
        type=int,
        default=int(os.environ.get("OPEN_CINEMA_CAMILLADSP_PORT", "1234")),
    )
    result.add_argument(
        "--runtime-redis-key",
        default=os.environ.get(
            "OPEN_CINEMA_RUNTIME_REDIS_KEY", "open-cinema:orchestration:runtime-world:v1"
        ),
    )
    result.add_argument(
        "--static-path",
        action="append",
        default=list(DEFAULT_STATIC_PATHS),
        help="managed static path included in restoration verification",
    )
    commands = result.add_subparsers(dest="phase", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--case-id", action="append", default=[])
    prepare.add_argument("--campaign")
    prepare.add_argument("--run-id")
    run_case = commands.add_parser("run-case")
    run_case.add_argument("run_id")
    run_case.add_argument("case_id")
    run_case.add_argument("--resume", action="store_true")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("run_id")
    restore = commands.add_parser("restore")
    restore.add_argument("run_id")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        runner = build_runner(arguments)
        if arguments.phase == "prepare":
            run_id = runner.prepare(
                case_ids=arguments.case_id,
                campaign=arguments.campaign,
                run_id=arguments.run_id,
            )
            print(f"benchmark_run_id={run_id}")
            print(f"benchmark_evidence_directory={runner.run_dir(run_id)}")
        elif arguments.phase == "run-case":
            status = runner.run_case(arguments.run_id, arguments.case_id, resume=arguments.resume)
            print(f"benchmark_status={status}")
            print(f"benchmark_evidence_directory={runner.run_dir(arguments.run_id)}")
        elif arguments.phase == "finalize":
            summary = runner.finalize(arguments.run_id)
            print(f"benchmark_status={summary['overallStatus']}")
            print(f"benchmark_evidence_directory={runner.run_dir(arguments.run_id)}")
        elif arguments.phase == "restore":
            runner.restore(arguments.run_id)
            print("benchmark_restoration_status=restored")
            print(f"benchmark_evidence_directory={runner.run_dir(arguments.run_id)}")
        return 0
    except InterruptedCase as error:
        print(f"benchmark_error={redact_string(str(error))}", file=sys.stderr)
        return 130
    except (BenchmarkError, ContractError) as error:
        print(f"benchmark_error={redact_string(str(error))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
