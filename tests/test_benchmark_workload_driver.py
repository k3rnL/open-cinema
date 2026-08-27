from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
BENCHMARKS = ROOT / "deployment" / "benchmarks"
MODULE_PATH = BENCHMARKS / "benchmark_workload_driver.py"
SPEC = importlib.util.spec_from_file_location("open_cinema_benchmark_workload_driver", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
driver_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver_module
SPEC.loader.exec_module(driver_module)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.playback_calls: list[dict[str, Any]] = []
        self.stopped: list[object] = []
        self.applied: list[dict[str, Any]] = []
        self.validation_candidates: list[dict[str, Any]] = []
        self.activated_fixtures: list[str] = []
        self.restored_intents: list[dict[str, Any]] = []
        self._intent_configuration: dict[str, Any] | None = None
        self.playback_healthy = True
        self.playback_stop_ok = True
        self.node_readiness_calls: list[tuple[str, float]] = []
        self.active = {
            "title": "Prepared active graph profile",
            "description": "Must be restored exactly",
            "devices": {
                "samplerate": 48_000,
                "chunksize": 256,
                "capture": {
                    "type": "PipeWire",
                    "channels": 8,
                    "node_name": "opencinema.camilladsp.0.capture",
                    "node_description": "Active capture",
                    "node_group_name": "opencinema.camilladsp.0.group",
                    "autoconnect_to": None,
                },
                "playback": {
                    "type": "PipeWire",
                    "channels": 8,
                    "node_name": "opencinema.camilladsp.0.playback",
                    "node_description": "Active playback",
                    "node_group_name": "opencinema.camilladsp.0.group",
                    "autoconnect_to": None,
                },
            },
            "filters": {"prepared": {"type": "Gain", "parameters": {"gain": -3.0}}},
            "pipeline": [{"type": "Filter", "channels": [0], "names": ["prepared"]}],
        }

    def start_file_playback(self, **arguments: Any) -> tuple[object, dict[str, Any]]:
        self.events.append("playback-started")
        self.playback_calls.append(arguments)
        handle = f"playback-{len(self.playback_calls)}"
        (arguments["evidence_dir"] / f"{handle}-ffmpeg.log").write_text(
            "ffmpeg\n", encoding="utf-8"
        )
        (arguments["evidence_dir"] / f"{handle}-pw-cat.log").write_text(
            "pw-cat\n", encoding="utf-8"
        )
        return handle, {
            "handleId": handle,
            "nodeName": f"benchmark.{handle}",
            "ffmpegLog": f"{handle}-ffmpeg.log",
            "pipewireLog": f"{handle}-pw-cat.log",
        }

    def stop_file_playback(self, handle: object) -> dict[str, Any]:
        self.stopped.append(handle)
        return {"handleId": handle, "returncode": 0, "ok": self.playback_stop_ok}

    def playback_status(self, handle: object) -> dict[str, Any]:
        return {
            "handleId": handle,
            "feederAlive": self.playback_healthy,
            "playerAlive": self.playback_healthy,
            "linked": self.playback_healthy,
            "active": self.playback_healthy,
        }

    def wait_for_audio_node(self, node_name: str, *, timeout_seconds: float) -> dict[str, Any]:
        self.node_readiness_calls.append((node_name, timeout_seconds))
        return {"ready": True, "nodeName": node_name, "durationNs": 10}

    def camilladsp_active_configuration(self) -> dict[str, Any]:
        return copy.deepcopy(self.active)

    def apply_camilladsp_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
        self.validation_candidates.append(copy.deepcopy(configuration))
        if configuration["devices"]["chunksize"] < 1:
            raise driver_module.CamillaDSPConfigurationRejected("chunksize must be positive")
        candidate = copy.deepcopy(configuration)
        self.events.append("camilladsp-applied")
        self.applied.append(candidate)
        self.active = candidate
        return {"state": "running"}

    def intent_snapshot(self) -> dict[str, Any]:
        self._intent_configuration = copy.deepcopy(self.active)
        return {
            "schemaVersion": 1,
            "active": [{"definitionId": "prepared", "revisionId": "revision-1"}],
            "semanticDigest": "a" * 64,
            "observedVersions": [],
        }

    def activate_camilladsp_fixture(self, fixture_id: str) -> dict[str, Any]:
        self.events.append("managed-profile-activated")
        self.activated_fixtures.append(fixture_id)
        self.active = {**copy.deepcopy(self.active), "title": f"Open Cinema benchmark: {fixture_id}"}
        return {"fixtureId": fixture_id, "profileDigest": "b" * 64}

    def restore_activations(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self.restored_intents.append(copy.deepcopy(snapshot))
        if self._intent_configuration is not None:
            self.active = copy.deepcopy(self._intent_configuration)
        return {"changed": True, "snapshot": copy.deepcopy(snapshot)}

    def wait_camilladsp_configuration(
        self, configuration: dict[str, Any], *, timeout_seconds: float
    ) -> dict[str, Any]:
        assert timeout_seconds == 60
        assert self.active == configuration
        return {"ready": True, "configurationSha256": driver_module.canonical_digest(configuration)}


def case(case_id: str) -> dict[str, Any]:
    manifest = load_yaml(BENCHMARKS / "cases.yml")
    declared = next(item for item in manifest["cases"] if item["id"] == case_id)
    return {**manifest["defaults"], **declared}


def session(
    tmp_path: Path,
    case_id: str,
    backend: FakeBackend,
    *,
    processor_fixture: str | None = None,
) -> Any:
    selected = case(case_id)
    return driver_module.BenchmarkWorkloadDriver(
        contracts_root=BENCHMARKS,
        fixture=load_yaml(BENCHMARKS / "fixtures.yml"),
        backend=backend,
        case=selected,
        unit={
            "processorFixture": processor_fixture or selected["processor_fixture"],
            "services": [],
        },
        sample_dir=tmp_path,
    )


def test_pcm_and_iec61937_bindings_start_real_time_pipewire_playback(tmp_path: Path) -> None:
    backend = FakeBackend()
    pcm = session(tmp_path, "decoder-pcm-stereo", backend)

    started = pcm.start()

    call = backend.playback_calls[-1]
    assert call["asset_path"].name == "pcm-stereo-channel-id.s16le"
    assert call["source_kind"] == "raw-s16le"
    assert call["sample_rate_hz"] == 48_000
    assert call["channels"] == 2
    assert call["target_node"] == "open-cinema.decoder.decoder-0.capture"
    assert started["input"]["mediaSha256"] == driver_module.sha256_file(call["asset_path"])
    pcm.stop()

    encoded = session(tmp_path, "decoder-ac3-51", backend)
    encoded.start()
    assert backend.playback_calls[-1]["asset_path"].name == "ac3-5.1.spdif"
    assert backend.playback_calls[-1]["source_kind"] == "raw-s16le"
    encoded.stop()


def test_media_digest_mismatch_is_rejected_before_playback(tmp_path: Path) -> None:
    backend = FakeBackend()
    workload = session(tmp_path, "decoder-pcm-stereo", backend)
    workload._media_fixtures["pcm-stereo-raw-carrier"]["sha256"] = "0" * 64

    with pytest.raises(driver_module.WorkloadContractError, match="digest"):
        workload.start()

    assert backend.playback_calls == []


def test_service_recovery_and_scheduled_edges_restart_or_switch_programme(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    recovery = session(tmp_path, "recovery-service-matrix", backend)
    recovery.start()

    restored = recovery.after_fault_injection(["pipewire.service"])

    assert restored["action"] == "restart-programme-after-service-fault"
    assert len(backend.playback_calls) == 2
    assert backend.stopped == ["playback-1"]
    assert backend.node_readiness_calls == [
        ("open-cinema.decoder.decoder-0.capture", 30)
    ]
    recovery.stop()

    soak = session(tmp_path, "soak-encoded-multichannel", backend)
    soak.start()
    first = soak.transition("encoded-menu-format-edge", 0)
    second = soak.transition("encoded-menu-format-edge", 1)

    assert first["inputFixture"] == "pcm-stereo"
    assert backend.playback_calls[-2]["asset_path"].name == "pcm-stereo-channel-id.s16le"
    assert second["inputFixture"] == "ac3-5.1"
    assert backend.playback_calls[-1]["asset_path"].name == "ac3-5.1.spdif"
    soak.stop()


def test_service_recovery_restarts_a_stream_terminated_by_the_expected_fault(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    recovery = session(tmp_path, "recovery-service-matrix", backend)
    recovery.start()
    backend.playback_stop_ok = False

    restored = recovery.after_fault_injection(["pipewire.service"])

    assert restored["stopped"]["interruptedByExpectedFault"] is True
    assert len(backend.playback_calls) == 2
    assert backend.stopped == ["playback-1"]
    backend.playback_stop_ok = True
    recovery.stop()


def test_camilladsp_profile_uses_managed_intent_and_restores_exact_config(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    original = copy.deepcopy(backend.active)
    workload = session(
        tmp_path,
        "camilladsp-profiles-128",
        backend,
        processor_fixture="camilladsp-production-fir-iir-128",
    )

    started = workload.start()

    assert workload.requires_restoration is True
    assert started["processor"]["profileFixture"] == ("camilladsp-production-fir-iir-128")
    assert started["processor"]["driver"] == "managed-desired-graph-profile"
    assert backend.activated_fixtures == ["camilladsp-production-fir-iir-128"]
    assert backend.applied == []
    assert backend.events[:2] == ["managed-profile-activated", "playback-started"]

    workload.stop()

    assert backend.active == original
    assert workload.requires_restoration is False


def test_stereo_profile_is_selected_through_managed_intent(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    workload = session(
        tmp_path,
        "camilladsp-profile-replacement",
        backend,
        processor_fixture="camilladsp-stereo-128",
    )

    workload.start()

    assert backend.activated_fixtures == ["camilladsp-stereo-128"]
    assert backend.applied == []
    workload.stop()


def test_invalid_camilladsp_candidate_must_be_rejected_without_changing_active_config(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    original = copy.deepcopy(backend.active)
    workload = session(tmp_path, "camilladsp-invalid-configuration", backend)

    result = workload.start()

    assert result["action"]["rejected"] is True
    assert backend.validation_candidates[0]["devices"]["chunksize"] == -1
    assert backend.active == original
    assert backend.applied == []
    workload.stop()


def test_physical_and_bluetooth_fixture_actions_remain_manual(tmp_path: Path) -> None:
    backend = FakeBackend()
    workload = session(tmp_path, "routing-headset-takeover", backend)

    with pytest.raises(driver_module.ManualActionRequired, match="Bluetooth"):
        workload.start()

    assert backend.playback_calls == []


def test_playback_health_and_failed_cleanup_are_propagated(tmp_path: Path) -> None:
    backend = FakeBackend()
    workload = session(tmp_path, "decoder-pcm-stereo", backend)
    workload.start()
    backend.playback_healthy = False

    with pytest.raises(driver_module.WorkloadError, match="became unhealthy"):
        workload.health()

    backend.playback_healthy = True
    backend.playback_stop_ok = False
    with pytest.raises(driver_module.WorkloadError, match="failed before cleanup"):
        workload.stop()
    journal = json.loads((tmp_path / "workload-restore.json").read_text(encoding="utf-8"))
    assert journal["active"] is True
    assert {item["path"] for item in workload.artifacts()["logs"]} == {
        "playback-1-ffmpeg.log",
        "playback-1-pw-cat.log",
        "workload-restore.json",
    }


def test_camilladsp_restore_journal_records_managed_intent_and_clears_after(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    original = copy.deepcopy(backend.active)
    workload = session(
        tmp_path,
        "camilladsp-profiles-128",
        backend,
        processor_fixture="camilladsp-production-fir-iir-128",
    )

    workload.start()
    active = json.loads((tmp_path / "workload-restore.json").read_text(encoding="utf-8"))
    assert active["active"] is True
    assert active["camilladspOriginalConfiguration"] is None
    assert active["camilladspOriginalConfigurationSha256"] is None
    assert active["managedIntentMutation"] is True
    assert active["managedIntentSemanticDigest"] == "a" * 64
    assert active["managedCamillaDSPFixture"] == "camilladsp-production-fir-iir-128"

    workload.stop()
    cleared = json.loads((tmp_path / "workload-restore.json").read_text(encoding="utf-8"))
    assert cleared["active"] is False
    assert cleared["camilladspOriginalConfiguration"] is None
    assert cleared["managedIntentMutation"] is False
    assert backend.active == original
