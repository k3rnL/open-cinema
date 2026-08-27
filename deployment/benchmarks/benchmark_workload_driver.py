#!/usr/bin/env python3
"""Bounded target-side workload actions for Raspberry audio benchmarks.

The runner owns timing and restoration.  This module owns only the ephemeral
programme stream and CamillaDSP processing overlay used by one sample.  It
never edits desired graph intent, creates raw managed links, or automates a
physical/Bluetooth switch.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Protocol


class WorkloadError(RuntimeError):
    """A bounded workload action failed."""


class WorkloadContractError(WorkloadError):
    """The checked-in workload binding is unsafe or inconsistent."""


class ManualActionRequired(WorkloadError):
    """The case requires an operator or physical fixture."""


class CamillaDSPConfigurationRejected(WorkloadError):
    """CamillaDSP rejected a candidate before making it active."""


class WorkloadBackend(Protocol):
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
    ) -> tuple[object, Mapping[str, Any]]: ...

    def stop_file_playback(self, handle: object) -> Mapping[str, Any]: ...

    def playback_status(self, handle: object) -> Mapping[str, Any]: ...

    def camilladsp_active_configuration(self) -> Mapping[str, Any]: ...

    def apply_camilladsp_configuration(
        self, configuration: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def intent_snapshot(self) -> Mapping[str, Any]: ...

    def activate_camilladsp_fixture(self, fixture_id: str) -> Mapping[str, Any]: ...

    def restore_activations(self, snapshot: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def wait_camilladsp_configuration(
        self, configuration: Mapping[str, Any], *, timeout_seconds: float
    ) -> Mapping[str, Any]: ...


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _index(items: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise WorkloadContractError(f"{label} registry must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise WorkloadContractError(f"{label} registry contains an invalid entry")
        identifier = item["id"]
        if identifier in result:
            raise WorkloadContractError(f"duplicate {label} identifier: {identifier}")
        result[identifier] = item
    return result


def _safe_asset(root: Path, relative: object, *, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise WorkloadContractError(f"{label} path must be non-empty")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise WorkloadContractError(f"{label} path escapes its registry root") from error
    if not candidate.is_file():
        raise WorkloadContractError(f"{label} asset is missing: {relative}")
    return candidate


class BenchmarkWorkloadDriver:
    """Execute one case/sample workload through a narrow backend boundary."""

    _SUPPORTED_TRANSITIONS = {
        "reconciliation-refresh",
        "encoded-menu-format-edge",
        "profile-reapply-and-restore",
    }

    def __init__(
        self,
        *,
        contracts_root: Path,
        fixture: Mapping[str, Any],
        backend: WorkloadBackend,
        case: Mapping[str, Any],
        unit: Mapping[str, Any],
        sample_dir: Path,
    ) -> None:
        self.contracts_root = contracts_root
        self.fixture = fixture
        self.backend = backend
        self.case = case
        self.unit = unit
        self.sample_dir = sample_dir
        self.media_root = contracts_root / "media"
        self.generated_root = self.media_root / "generated"
        self.profile_root = self.media_root / "camilladsp"
        self._media = self._load_json(self.media_root / "manifest.json", "media")
        self._profiles = self._load_json(self.profile_root / "profiles.json", "CamillaDSP profile")
        expected_contract = fixture["fixture_contract_id"]
        if self._media.get("fixtureContractId") != expected_contract:
            raise WorkloadContractError("media registry fixture contract differs")
        if self._profiles.get("fixtureContractId") != expected_contract:
            raise WorkloadContractError("profile registry fixture contract differs")
        self._media_fixtures = _index(self._media.get("fixtures"), label="media")
        self._profile_fixtures = _index(self._profiles.get("profiles"), label="CamillaDSP profile")
        self._playback_handle: object | None = None
        self._playback_record: dict[str, Any] | None = None
        self._log_paths: list[str] = []
        self._input_fixture_name: str | None = None
        self._original_camilladsp: dict[str, Any] | None = None
        self._original_intent: dict[str, Any] | None = None
        self._managed_profile_fixture: str | None = None
        self._profile_fixture_name: str | None = None
        self._started = False
        self._restore_journal_path = self.sample_dir / "workload-restore.json"

    def _write_restore_journal(self) -> None:
        """Persist enough bounded state for a later ``restore`` process.

        The runner can be terminated between a live CamillaDSP mutation and its
        in-process ``finally`` block.  This private journal is therefore written
        before each mutation and cleared only after the exact prior state has
        been restored.
        """

        self.sample_dir.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1,
            "active": (
                self._playback_record is not None
                or self._original_camilladsp is not None
                or self._original_intent is not None
            ),
            "playback": copy.deepcopy(self._playback_record),
            # Managed profile mutations are restored through the run-level
            # active-intent snapshot, never by writing a raw engine config.
            "camilladspOriginalConfiguration": None,
            "camilladspOriginalConfigurationSha256": None,
            "managedIntentMutation": self._original_intent is not None,
            "managedIntentSemanticDigest": (
                self._original_intent.get("semanticDigest")
                if self._original_intent is not None
                else None
            ),
            "managedCamillaDSPFixture": self._managed_profile_fixture,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".workload-restore.", dir=self.sample_dir
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._restore_journal_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _load_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkloadContractError(f"cannot load {label} registry: {path}") from error
        if not isinstance(value, dict):
            raise WorkloadContractError(f"{label} registry must contain an object")
        return value

    @property
    def requires_restoration(self) -> bool:
        return self._original_intent is not None

    def _verified_media_asset(self, fixture_id: str) -> tuple[Path, dict[str, Any]]:
        try:
            record = self._media_fixtures[fixture_id]
        except KeyError as error:
            raise WorkloadContractError(f"unknown media fixture: {fixture_id}") from error
        path = _safe_asset(self.generated_root, record.get("path"), label="media")
        if path.stat().st_size != record.get("sizeBytes"):
            raise WorkloadContractError(f"media size differs from registry: {fixture_id}")
        if sha256_file(path) != record.get("sha256"):
            raise WorkloadContractError(f"media digest differs from registry: {fixture_id}")
        return path, record

    def _verified_profile_asset(self, profile_id: str) -> tuple[Path, dict[str, Any]]:
        try:
            record = self._profile_fixtures[profile_id]
        except KeyError as error:
            raise WorkloadContractError(f"unknown CamillaDSP fixture: {profile_id}") from error
        path = _safe_asset(self.profile_root, record.get("path"), label="CamillaDSP profile")
        if path.stat().st_size != record.get("sizeBytes"):
            raise WorkloadContractError(f"profile size differs from registry: {profile_id}")
        if sha256_file(path) != record.get("sha256"):
            raise WorkloadContractError(f"profile digest differs from registry: {profile_id}")
        return path, record

    def _input_binding(self, fixture_name: str) -> Mapping[str, Any]:
        try:
            fixture = self.fixture["input_fixtures"][fixture_name]
        except KeyError as error:
            raise WorkloadContractError(f"unknown input fixture: {fixture_name}") from error
        automation = fixture.get("automation")
        if not isinstance(automation, Mapping):
            raise WorkloadContractError(f"input fixture lacks automation: {fixture_name}")
        return automation

    def _start_input(self, fixture_name: str) -> dict[str, Any]:
        binding = self._input_binding(fixture_name)
        driver = binding.get("driver")
        if driver == "none":
            self._input_fixture_name = fixture_name
            return {"driver": "none", "inputFixture": fixture_name}
        if driver == "manual":
            raise ManualActionRequired(str(binding.get("reason") or fixture_name))
        if driver != "pipewire-file-playback":
            raise WorkloadContractError(f"unsupported input driver: {driver!r}")
        media_id = binding.get("media_fixture_id")
        if not isinstance(media_id, str):
            raise WorkloadContractError(f"input fixture lacks media_fixture_id: {fixture_name}")
        asset, registry = self._verified_media_asset(media_id)
        source_kind = "container" if registry.get("transport") == "wav" else "raw-s16le"
        handle, result = self.backend.start_file_playback(
            asset_path=asset,
            source_kind=source_kind,
            sample_format=str(binding.get("sample_format")),
            sample_rate_hz=int(binding.get("sample_rate_hz")),
            channels=int(binding.get("channels")),
            channel_map=str(binding.get("channel_map")),
            target_node=str(binding.get("target_node")),
            evidence_dir=self.sample_dir,
        )
        self._playback_handle = handle
        backend_result = dict(result)
        self._playback_record = {
            "handleId": str(handle),
            "nodeName": backend_result.get("nodeName"),
            "targetNode": binding["target_node"],
            "feederPid": backend_result.get("feederPid"),
            "feederProcessGroup": backend_result.get("feederProcessGroup"),
            "playerPid": backend_result.get("playerPid"),
            "playerProcessGroup": backend_result.get("playerProcessGroup"),
        }
        for key in ("ffmpegLog", "pipewireLog"):
            path = backend_result.get(key)
            if isinstance(path, str) and path and Path(path).name == path:
                if path not in self._log_paths:
                    self._log_paths.append(path)
        self._write_restore_journal()
        self._input_fixture_name = fixture_name
        return {
            "driver": driver,
            "inputFixture": fixture_name,
            "mediaFixture": media_id,
            "mediaSha256": registry["sha256"],
            "targetNode": binding["target_node"],
            "backend": backend_result,
        }

    def _stop_input(self, *, allow_interrupted: bool = False) -> dict[str, Any]:
        if self._playback_handle is None:
            return {"stopped": False, "reason": "no-playback-process"}
        handle = self._playback_handle
        result = dict(self.backend.stop_file_playback(handle))
        interrupted = result.get("ok") is False
        if interrupted and not allow_interrupted:
            raise WorkloadError(f"benchmark playback failed before cleanup: {result}")
        self._playback_handle = None
        self._playback_record = None
        self._write_restore_journal()
        return {
            "stopped": True,
            "interruptedByExpectedFault": interrupted,
            "backend": result,
        }

    def health(self) -> dict[str, Any]:
        """Fail the sample if its synthetic programme stream is not usable."""

        if self._playback_handle is None:
            return {"required": False, "healthy": True}
        status = dict(self.backend.playback_status(self._playback_handle))
        if not (
            status.get("feederAlive") is True
            and status.get("playerAlive") is True
            and status.get("linked") is True
            and status.get("active") is True
        ):
            raise WorkloadError(f"benchmark playback became unhealthy: {status}")
        return {"required": True, "healthy": True, "backend": status}

    def artifacts(self) -> dict[str, list[dict[str, Any]]]:
        logs = [{"path": path} for path in self._log_paths]
        if self._restore_journal_path.is_file():
            logs.append({"path": self._restore_journal_path.name})
        return {
            "logs": logs,
            "captures": [],
        }

    def _apply_profile(self, fixture_name: str) -> dict[str, Any]:
        try:
            fixture = self.fixture["processor_fixtures"][fixture_name]
        except KeyError as error:
            raise WorkloadContractError(f"unknown processor fixture: {fixture_name}") from error
        automation = fixture.get("automation")
        if not isinstance(automation, Mapping):
            raise WorkloadContractError(f"processor fixture lacks automation: {fixture_name}")
        driver = automation.get("driver")
        if driver == "none":
            return {"driver": "none", "processorFixture": fixture_name}
        if driver == "manual":
            raise ManualActionRequired(str(automation.get("reason") or fixture_name))
        if driver != "managed-camilladsp-profile":
            raise WorkloadContractError(f"unsupported processor driver: {driver!r}")
        profile_id = automation.get("profile_fixture_id")
        if not isinstance(profile_id, str):
            raise WorkloadContractError(
                f"processor fixture lacks profile_fixture_id: {fixture_name}"
            )
        profile_path, registry = self._verified_profile_asset(profile_id)
        if self._original_intent is None:
            self._original_intent = copy.deepcopy(dict(self.backend.intent_snapshot()))
            self._original_camilladsp = copy.deepcopy(
                dict(self.backend.camilladsp_active_configuration())
            )
            self._write_restore_journal()
        self._profile_fixture_name = fixture_name
        applied = self.backend.activate_camilladsp_fixture(profile_id)
        self._managed_profile_fixture = profile_id
        self._write_restore_journal()
        return {
            "driver": "managed-desired-graph-profile",
            "processorFixture": fixture_name,
            "profileFixture": profile_id,
            "profileSha256": registry["sha256"],
            "profileAsset": profile_path.name,
            "backend": dict(applied),
        }

    def _reject_invalid_configuration(self) -> dict[str, Any]:
        active = copy.deepcopy(dict(self.backend.camilladsp_active_configuration()))
        devices = active.get("devices")
        if not isinstance(devices, dict):
            raise WorkloadContractError("active CamillaDSP configuration lacks devices")
        # CamillaDSP 4 accepts zero here and resolves it as an automatic/default
        # chunk size.  A negative value is schema-invalid across the supported
        # CamillaDSP 4 releases and therefore exercises rejection without ever
        # applying a candidate configuration.
        devices["chunksize"] = -1
        try:
            self.backend.apply_camilladsp_configuration(active)
        except CamillaDSPConfigurationRejected as error:
            observed = dict(self.backend.camilladsp_active_configuration())
            return {
                "action": "reject-invalid-camilladsp-config",
                "rejected": True,
                "error": str(error),
                "activeConfigurationSha256": canonical_digest(observed),
            }
        raise WorkloadError("CamillaDSP accepted the declared invalid configuration")

    def start(self) -> dict[str, Any]:
        if self._started:
            raise WorkloadError("workload is already started")
        if self.case.get("execution_mode") == "manual":
            raise ManualActionRequired(str(self.case.get("manual_reason") or self.case["id"]))
        self._started = True
        try:
            processor_fixture = str(
                self.unit.get("processorFixture", self.case["processor_fixture"])
            )
            processor_result = self._apply_profile(processor_fixture)
            # A CamillaDSP configuration swap recreates its PipeWire nodes.
            # Attach programme audio only after the selected profile is ready,
            # otherwise pw-cat remains linked to the retired capture node.
            input_result = self._start_input(str(self.case["input_fixture"]))
            action_result = None
            if self.case.get("workload_action_kind") == "reject-invalid-camilladsp-config":
                action_result = self._reject_invalid_configuration()
            return {
                "input": input_result,
                "processor": processor_result,
                "action": action_result,
            }
        except BaseException:
            self.stop()
            raise

    def after_fault_injection(self, services: list[str]) -> dict[str, Any]:
        if not services or self._input_fixture_name is None:
            return {"action": "none"}
        # Restarting PipeWire is expected to terminate the benchmark pw-cat
        # client. Its non-zero exit remains evidence, but it must not prevent
        # the workload from attaching a fresh stream to the restored runtime.
        stopped = self._stop_input(allow_interrupted=True)
        target_readiness = None
        if hasattr(self.backend, "wait_for_audio_node"):
            binding = self._input_binding(self._input_fixture_name)
            target_readiness = self.backend.wait_for_audio_node(
                str(binding["target_node"]),
                timeout_seconds=30,
            )
        started = self._start_input(self._input_fixture_name)
        return {
            "action": "restart-programme-after-service-fault",
            "services": list(services),
            "stopped": stopped,
            "targetReadiness": target_readiness,
            "started": started,
        }

    def transition(self, kind: str, index: int) -> dict[str, Any]:
        if kind not in self._SUPPORTED_TRANSITIONS:
            raise ManualActionRequired(f"transition {kind!r} has no bounded automatic driver")
        if kind == "reconciliation-refresh":
            if self._input_fixture_name is None:
                raise WorkloadError("reconciliation refresh requires an active input workload")
            stopped = self._stop_input()
            started = self._start_input(self._input_fixture_name)
            return {"action": "restart-programme-stream", "stopped": stopped, "started": started}
        if kind == "encoded-menu-format-edge":
            cycle = self.case.get("transition_input_cycle")
            if not isinstance(cycle, list) or not cycle:
                raise WorkloadContractError("encoded transition requires transition_input_cycle")
            fixture_name = cycle[index % len(cycle)]
            if not isinstance(fixture_name, str):
                raise WorkloadContractError("transition input cycle contains an invalid fixture")
            stopped = self._stop_input()
            started = self._start_input(fixture_name)
            return {
                "action": "switch-programme-fixture",
                "inputFixture": fixture_name,
                "stopped": stopped,
                "started": started,
            }
        if (
            self._original_intent is None
            or self._original_camilladsp is None
            or self._managed_profile_fixture is None
        ):
            raise WorkloadError("profile transition requires an applied workload profile")
        if index % 2 == 0:
            result = self.backend.activate_camilladsp_fixture(self._managed_profile_fixture)
            action = "reapply-workload-profile"
        else:
            restored = self.backend.restore_activations(self._original_intent)
            ready = self.backend.wait_camilladsp_configuration(
                self._original_camilladsp,
                timeout_seconds=60,
            )
            result = {"intent": dict(restored), "readiness": dict(ready)}
            action = "restore-active-profile"
        return {
            "action": action,
            "backend": dict(result),
        }

    def stop(self) -> dict[str, Any]:
        results: dict[str, Any] = {"input": self._stop_input(), "processor": None}
        if self._original_intent is not None and self._original_camilladsp is not None:
            original_intent = self._original_intent
            original_configuration = self._original_camilladsp
            restored = self.backend.restore_activations(original_intent)
            ready = self.backend.wait_camilladsp_configuration(
                original_configuration,
                timeout_seconds=60,
            )
            results["processor"] = {
                "restoredConfigurationSha256": canonical_digest(original_configuration),
                "intent": dict(restored),
                "readiness": dict(ready),
            }
            self._original_camilladsp = None
            self._original_intent = None
            self._managed_profile_fixture = None
            self._write_restore_journal()
        self._started = False
        return results
