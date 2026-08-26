from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
BENCHMARKS = ROOT / "deployment" / "benchmarks"
MODULE_PATH = BENCHMARKS / "benchmark_runner.py"
SPEC = importlib.util.spec_from_file_location("open_cinema_benchmark_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner_module
SPEC.loader.exec_module(runner_module)


CONTRACT_FILES = (
    "fixtures.yml",
    "fixture.schema.json",
    "cases.yml",
    "cases.schema.json",
    "criteria-policy.yml",
    "evidence-envelope.schema.json",
)


def contract_copy(tmp_path: Path) -> Path:
    target = tmp_path / "contracts"
    target.mkdir()
    for name in CONTRACT_FILES:
        shutil.copyfile(BENCHMARKS / name, target / name)
    manifest_path = target / "cases.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        if case["id"] in {
            "baseline-fixture-and-topology",
            "decoder-pcm-stereo",
            "decoder-failure-recovery",
        }:
            case["warm_up_repetitions"] = 0
            case["measured_repetitions"] = 1
            case["duration_seconds"] = 1
            case["timeout_seconds"] = 5
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return target


class FakePlatform:
    def __init__(self) -> None:
        self.now_ns = 1_000_000_000
        self.restore_calls = 0
        self.injected: list[list[str]] = []
        self.failure: str | None = None
        self.temperature = 50.0
        self.pipewire_errors = 0
        self.journal = "device=AA:BB:CC:DD:EE:FF token=do-not-export\n"
        self.workloads: list[FakeWorkloadDriver] = []
        self.workload_restore_calls = 0

    def monotonic_ns(self) -> int:
        return self.now_ns

    def utc_now(self) -> str:
        seconds = self.now_ns / 1_000_000_000
        return f"2026-08-26T00:00:{seconds:09.6f}Z"

    def boot_id(self) -> str:
        return "recorded-boot-id"

    def sleep(self, seconds: float) -> None:
        self.now_ns += int(seconds * 1_000_000_000)

    def _overhead(self, milliseconds: int = 1) -> None:
        self.now_ns += milliseconds * 1_000_000

    def journal_marker(self, run_id: str) -> dict[str, str]:
        return {"marker": f"marker:{run_id}", "cursor": "recorded-cursor"}

    def journal_since(self, marker: dict[str, Any], units: tuple[str, ...]) -> str:
        assert marker["cursor"] == "recorded-cursor"
        assert "open-cinema-orchestrator.service" in units
        return self.journal

    @staticmethod
    def _topology() -> dict[str, Any]:
        links = [
            {"output": ["source", f"out-{index}"], "input": ["sink", f"in-{index}"]}
            for index in range(18)
        ]
        return {
            "ownedLinkCount": 18,
            "links": links,
            "digest": runner_module.digest_document(links),
        }

    def fixture_facts(self, fixture: dict[str, Any]) -> dict[str, Any]:
        return {
            "hardware": {
                "model": "Raspberry Pi 5 Model B Rev 1.1",
                "revision": "1.1",
                "memoryKb": 8_000_000,
                "architecture": "aarch64",
                "powerDeclaration": fixture["device_under_test"]["power"],
                "coolingDeclaration": fixture["device_under_test"]["cooling"],
            },
            "operatingSystem": {"ID": "debian", "VERSION_CODENAME": "trixie"},
            "kernel": {"release": "recorded"},
            "storage": {"freeBytes": 10_000_000_000},
            "network": [
                {
                    "name": "wlan0",
                    "operstate": "up",
                    "speedMbps": None,
                    "address": "AA:BB:CC:DD:EE:FF",
                }
            ],
            "audioInterfaces": {"alsaCards": "WONDOM GAB8"},
            "bluetooth": {
                "devices": ["Device AA:BB:CC:DD:EE:FF Headset"],
                "password": "do-not-export",
            },
            "graph": {"observed": self._topology(), "activeRevision": "recorded-r1"},
            "processorConfigs": {"staticDigest": "a" * 64},
            "versions": {"pipewire": "1.4.2", "wireplumber": "0.5.8"},
            "initialThrottling": "0x0",
        }

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "services": {
                service: {"active": True, "state": "active"}
                for service in runner_module.RUNTIME_SERVICES
            },
            "activeIntent": {
                "schemaVersion": 1,
                "active": [],
                "semanticDigest": "b" * 64,
                "observedVersions": [],
            },
            "intentDigest": "b" * 64,
            "staticDigest": "a" * 64,
            "topology": self._topology(),
        }

    def inject_services(self, services: list[str]) -> list[dict[str, Any]]:
        self.injected.append(list(services))
        self._overhead()
        return [{"service": service, "action": "restart"} for service in services]

    def restore(self, snapshot: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        self.restore_calls += 1
        self._overhead()
        if self.failure == "restore":
            raise runner_module.RestorationError("recorded restore failure")
        return {
            "topologyVerified": snapshot["topology"] == self._topology(),
            "staticDigest": snapshot["staticDigest"],
            "staticDigestVerified": True,
            "dynamicDigest": snapshot["intentDigest"],
            "dynamicDigestVerified": True,
        }

    def restore_workload_journals(self, run_dir: Path) -> dict[str, Any]:
        assert run_dir.is_dir()
        self.workload_restore_calls += 1
        return {
            "activeJournalCount": 0,
            "playbackActions": [],
            "camilladspAction": None,
        }

    def transition_sample(self) -> dict[str, Any]:
        self._overhead()
        if self.failure == "failed":
            raise RuntimeError("recorded collector failure")
        if self.failure == "interrupted":
            raise runner_module.InterruptedCase("recorded interruption")
        return {
            "pipewire": self._topology(),
            "runtimeGeneration": 1,
            "runtimeSequence": 2,
            "worldVersion": 3,
            "connectionState": "connected",
            "retryState": None,
            "processorReadiness": {"ready": True},
            "decoder": {"available": True, "value": {"sequence": 4, "errors": []}},
            "reconciliation": {"available": True, "states": [{"status": "converged"}]},
        }

    def sustained_sample(self) -> dict[str, Any]:
        self._overhead(10_000 if self.failure == "timeout" else 1)
        return {
            "applianceCpuPercent": 5.0,
            "loadAverage": [0.1, 0.1, 0.1],
            "processes": [{"pid": 1, "command": "camilladsp", "cpuPercent": 2.0, "rssKb": 1024}],
            "availableMemoryKb": 7_000_000,
            "temperatureCelsius": self.temperature,
            "clocks": {"arm": "frequency(48)=2400000000"},
            "throttling": "0x0",
            "services": {"open-cinema-orchestrator.service": {"active": True}},
            "diskCounters": "recorded",
            "filesystem": {"freeBytes": 10_000_000_000},
        }

    def native_health(self) -> dict[str, Any]:
        self._overhead()
        return {
            "pipewireObjects": [
                {"nodeId": 10, "name": "decoder-output", "errors": self.pipewire_errors}
            ],
            "decoder": {"available": True, "value": {"queue": {"drops": 0}}},
            "processorProjections": {"available": True, "rows": []},
        }

    def event_storage_sample(self) -> dict[str, Any]:
        self._overhead()
        return {
            "sqliteLatencyNs": 1000,
            "sqliteBusy": False,
            "sqliteQuickCheck": "ok",
            "retainedRecordCounts": {"api_resolvedplan": 1},
            "orchestrationEvents": {
                "offered": 10,
                "processed": 8,
                "coalesced": 2,
                "retried": 0,
                "dropped": 0,
            },
            "redis": {"usedMemory": 1024},
            "database": {"sizeBytes": 4096, "blocks": 8},
            "diskCounters": "recorded",
        }


class FakeWorkloadDriver:
    def __init__(
        self,
        *,
        platform: FakePlatform,
        case: dict[str, Any],
        unit: dict[str, Any],
        sample_dir: Path,
    ) -> None:
        self.platform = platform
        self.case = case
        self.unit = unit
        self.sample_dir = sample_dir
        self.requires_restoration = False
        self.transitions: list[tuple[str, int]] = []
        self.faults: list[list[str]] = []
        self.started = False
        self.stopped = False
        self.health_calls = 0
        platform.workloads.append(self)

    def start(self) -> dict[str, Any]:
        self.started = True
        (self.sample_dir / "fake-ffmpeg.log").write_text("ffmpeg fixture\n", encoding="utf-8")
        (self.sample_dir / "fake-pw-cat.log").write_text("pw-cat fixture\n", encoding="utf-8")
        if "physical-audio" in self.case["required_metric_sets"]:
            (self.sample_dir / "fake-capture.wav").write_bytes(b"RIFF-recorded-capture")
        return {
            "inputFixture": self.case["input_fixture"],
            "processorFixture": self.unit["processorFixture"],
        }

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        if self.platform.failure == "playback":
            raise RuntimeError("recorded playback became unhealthy")
        return {"required": self.case["workload_state"] == "programme-audio", "healthy": True}

    def artifacts(self) -> dict[str, list[dict[str, str]]]:
        captures = (
            [{"path": "fake-capture.wav"}]
            if "physical-audio" in self.case["required_metric_sets"]
            else []
        )
        return {
            "logs": [{"path": "fake-ffmpeg.log"}, {"path": "fake-pw-cat.log"}],
            "captures": captures,
        }

    def transition(self, kind: str, index: int) -> dict[str, Any]:
        self.transitions.append((kind, index))
        return {"kind": kind, "index": index}

    def after_fault_injection(self, services: list[str]) -> dict[str, Any]:
        self.faults.append(services)
        return {"services": services}

    def stop(self) -> dict[str, Any]:
        self.stopped = True
        return {"stopped": True}


def make_runner(tmp_path: Path) -> tuple[Any, FakePlatform]:
    contracts = runner_module.Contracts.load(contract_copy(tmp_path))
    contracts.fixture["measurement"]["physical_timing"] = {
        "state": "calibrated",
        "acceptance_metrics_available": True,
    }
    platform = FakePlatform()
    runner = runner_module.BenchmarkRunner(
        contracts=contracts,
        result_root=tmp_path / "results",
        platform=platform,
        workload_driver_factory=lambda **arguments: FakeWorkloadDriver(
            platform=platform,
            **arguments,
        ),
    )
    return runner, platform


def bound_case(
    runner: Any,
    case_id: str,
    *,
    duration_seconds: int = 1,
    timeout_seconds: int = 5,
) -> dict[str, Any]:
    """Keep recorded lifecycle tests bounded independently of hardware cases."""

    declared = next(case for case in runner.contracts.cases["cases"] if case["id"] == case_id)
    declared["warm_up_repetitions"] = 0
    declared["measured_repetitions"] = 1
    declared["duration_seconds"] = duration_seconds
    declared["timeout_seconds"] = timeout_seconds
    bounded = runner.contracts.case(case_id)
    runner.contracts.fixture["input_fixtures"][bounded["input_fixture"]][
        "registry_status"
    ] = "registered"
    for processor_name in [
        bounded["processor_fixture"],
        *bounded.get("processor_fixture_matrix", []),
    ]:
        runner.contracts.fixture["processor_fixtures"][processor_name][
            "profile_status"
        ] = "registered"
    return bounded


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_successful_characterization_has_correlated_evidence_and_is_never_acceptance(
    tmp_path: Path,
) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["baseline-fixture-and-topology"], run_id="recorded-run")
    assert runner.run_case(run_id, "baseline-fixture-and-topology") == "characterized"
    summary = runner.finalize(run_id)

    assert summary["overallStatus"] == "characterized"
    assert summary["accepted"] is False
    assert summary["validSampleCount"] == 1
    run_dir = runner.run_dir(run_id)
    envelope = read_json(
        run_dir
        / "cases/baseline-fixture-and-topology/baseline-fixture-and-topology-sample-0001/evidence-envelope.json"
    )
    runner_module.validate_json(envelope, runner.contracts.evidence_schema_path)
    assert envelope["status"] == "characterized"
    assert envelope["timestamps"]["clockCalibration"] == {
        "bootId": "recorded-boot-id",
        "clock": "CLOCK_BOOTTIME",
        "controllerSubtractionAllowed": False,
        "controllerUncertaintyNs": None,
        "targetMonotonicNs": 1_000_000_000,
        "targetUtc": "2026-08-26T00:00:01.000000Z",
    }
    transitions = runner_module.BenchmarkRunner._read_jsonl(
        run_dir
        / "cases/baseline-fixture-and-topology/baseline-fixture-and-topology-sample-0001/transition.jsonl"
    )
    monotonic = [row["monotonicNs"] for row in transitions]
    assert monotonic == sorted(monotonic)
    assert len({row["sampleId"] for row in transitions}) == len(transitions)
    assert all(row["pipewire"]["ownedLinkCount"] == 18 for row in transitions)


@pytest.mark.parametrize(
    ("failure", "exception", "expected_status"),
    (
        ("failed", runner_module.BenchmarkError, "failed"),
        ("timeout", runner_module.CaseTimeout, "invalid"),
        ("interrupted", runner_module.InterruptedCase, "interrupted"),
        ("restore", runner_module.BenchmarkError, "failed"),
    ),
)
def test_disruptive_case_restores_and_retains_failure_diagnostics(
    tmp_path: Path,
    failure: str,
    exception: type[BaseException],
    expected_status: str,
) -> None:
    runner, platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["decoder-failure-recovery"], run_id=f"run-{failure}")
    platform.failure = failure
    with pytest.raises(exception):
        runner.run_case(run_id, "decoder-failure-recovery")

    state = read_json(runner.run_dir(run_id) / "run-state.json")
    assert state["cases"]["decoder-failure-recovery"]["status"] == expected_status
    assert platform.restore_calls == 1
    sample_dir = (
        runner.run_dir(run_id)
        / "cases/decoder-failure-recovery/decoder-failure-recovery-sample-0001"
    )
    assert (sample_dir / "evidence-envelope.json").is_file()
    assert (sample_dir / "failure.json").is_file() or (
        sample_dir / "restoration-failure.json"
    ).is_file()


def test_failed_case_is_resumable_from_the_same_sample(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["decoder-failure-recovery"], run_id="resume-run")
    platform.failure = "failed"
    with pytest.raises(runner_module.BenchmarkError):
        runner.run_case(run_id, "decoder-failure-recovery")
    platform.failure = None

    assert runner.run_case(run_id, "decoder-failure-recovery", resume=True) == "characterized"
    summary = runner.finalize(run_id)
    assert summary["overallStatus"] == "characterized"
    assert platform.restore_calls == 2
    assert platform.injected == [["pcm-auto-decoder@decoder-0.service"]]


def test_invalid_criteria_sample_is_excluded_and_can_be_rerun(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["decoder-pcm-stereo"], run_id="invalid-run")
    platform.temperature = 90.0
    runner.run_case(run_id, "decoder-pcm-stereo")
    with pytest.raises(runner_module.BenchmarkError, match="incomplete cases"):
        runner.finalize(run_id)

    state = read_json(runner.run_dir(run_id) / "run-state.json")
    assert state["finalized"] is False
    assert state["cases"]["decoder-pcm-stereo"]["status"] == "invalid"
    assert state["cases"]["decoder-pcm-stereo"]["nextUnit"] == 0
    first_summary = read_json(runner.run_dir(run_id) / "summary.json")
    assert first_summary["accepted"] is False
    assert first_summary["invalidSampleCount"] == 1

    platform.temperature = 50.0
    runner.run_case(run_id, "decoder-pcm-stereo", resume=True)
    summary = runner.finalize(run_id)
    assert summary["validSampleCount"] == 1
    assert summary["invalidSampleCount"] == 0
    assert summary["totalAttemptCount"] == 2
    assert summary["supersededAttemptCount"] == 1
    assert summary["supersededInvalidAttemptCount"] == 1
    case_dir = runner.run_dir(run_id) / "cases/decoder-pcm-stereo"
    assert (case_dir / "decoder-pcm-stereo-sample-0001/failure.json").exists() is False
    assert (case_dir / "decoder-pcm-stereo-sample-0001/evidence-envelope.json").is_file()
    assert (
        case_dir / "decoder-pcm-stereo-sample-0001-attempt-0002/evidence-envelope.json"
    ).is_file()


def test_successful_acceptance_retry_uses_latest_attempt_for_decision_and_statistics(
    tmp_path: Path,
) -> None:
    runner, platform = make_runner(tmp_path)
    declared = next(
        case for case in runner.contracts.cases["cases"] if case["id"] == "decoder-pcm-stereo"
    )
    declared["criteria_set"] = "acceptance-v1"
    acceptance = runner.contracts.criteria["criteria_sets"]["acceptance-v1"]
    acceptance.update(
        {
            "campaign_mode": "acceptance",
            "state": "frozen",
            "platform_acceptance_allowed": True,
            "thresholds": {
                "current_throttling": "0x0",
                "maximum_temperature_celsius": 80,
                "collector_sample_loss_maximum": 0,
                "programme_audio_pipewire_error_increment_maximum": 0,
            },
        }
    )
    bound_case(runner, "decoder-pcm-stereo")
    run_id = runner.prepare(case_ids=["decoder-pcm-stereo"], run_id="acceptance-retry")
    platform.temperature = 90.0
    runner.run_case(run_id, "decoder-pcm-stereo")
    with pytest.raises(runner_module.BenchmarkError, match="incomplete cases"):
        runner.finalize(run_id)

    platform.temperature = 50.0
    assert runner.run_case(run_id, "decoder-pcm-stereo", resume=True) == "passed"
    summary = runner.finalize(run_id)

    assert summary["overallStatus"] == "accepted"
    assert summary["accepted"] is True
    assert summary["validSampleCount"] == 1
    assert summary["invalidSampleCount"] == 0
    assert summary["totalAttemptCount"] == 2
    assert summary["supersededInvalidAttemptCount"] == 1
    assert summary["statistics"]["temperatureCelsius"] == {
        "count": 1,
        "median": 50.0,
        "p95NearestRank": 50.0,
        "maximum": 50.0,
    }


def test_incomplete_finalization_never_freezes_the_run(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(
        case_ids=["baseline-fixture-and-topology", "decoder-pcm-stereo"],
        run_id="incomplete-run",
    )
    runner.run_case(run_id, "baseline-fixture-and-topology")
    with pytest.raises(runner_module.BenchmarkError, match="decoder-pcm-stereo"):
        runner.finalize(run_id)
    state = read_json(runner.run_dir(run_id) / "run-state.json")
    assert state["finalized"] is False
    assert state["status"] == "incomplete"

    runner.run_case(run_id, "decoder-pcm-stereo")
    assert runner.finalize(run_id)["overallStatus"] == "characterized"


def test_redacted_export_and_checksum_chain_cover_every_exported_payload(
    tmp_path: Path,
) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["baseline-fixture-and-topology"], run_id="redaction-run")
    runner.run_case(run_id, "baseline-fixture-and-topology")
    runner.finalize(run_id)
    export = runner.run_dir(run_id) / "export"

    rendered = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in export.rglob("*")
        if path.is_file()
    )
    assert "AA:BB:CC:DD:EE:FF" not in rendered
    assert "do-not-export" not in rendered
    assert "[redacted]" in rendered
    checksums = {}
    for line in (export / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        checksums[relative] = digest
    expected = {
        path.relative_to(export).as_posix()
        for path in export.rglob("*")
        if path.is_file() and path not in {export / "SHA256SUMS", export / "SHA256SUMS.sha256"}
    }
    assert set(checksums) == expected
    assert all(
        runner_module.sha256_file(export / path) == digest for path, digest in checksums.items()
    )
    detached, name = (export / "SHA256SUMS.sha256").read_text().strip().split("  ", 1)
    assert name == "SHA256SUMS"
    assert detached == runner_module.sha256_file(export / "SHA256SUMS")


def test_recorded_collectors_preserve_event_accounting_and_overhead_statistics(
    tmp_path: Path,
) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["baseline-fixture-and-topology"], run_id="collectors-run")
    runner.run_case(run_id, "baseline-fixture-and-topology")
    summary = runner.finalize(run_id)
    sample_dir = (
        runner.run_dir(run_id)
        / "cases/baseline-fixture-and-topology/baseline-fixture-and-topology-sample-0001"
    )

    storage = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "event-storage.jsonl")
    assert storage
    assert all(
        row["orchestrationEvents"]
        == {"offered": 10, "processed": 8, "coalesced": 2, "retried": 0, "dropped": 0}
        for row in storage
    )
    assert summary["statistics"]["collectorOverheadMs"]["count"] > 0
    assert summary["statistics"]["collectorOverheadMs"]["maximum"] >= 0


def test_collector_overhead_sample_loss_invalidates_evidence(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(
        runner,
        "baseline-fixture-and-topology",
        duration_seconds=3,
        timeout_seconds=10,
    )
    assert case["duration_seconds"] == 3
    original_sustained_sample = platform.sustained_sample

    def delayed_sustained_sample() -> dict[str, Any]:
        sample = original_sustained_sample()
        platform._overhead(1_100)
        return sample

    platform.sustained_sample = delayed_sustained_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="collector-loss-run")

    with pytest.raises(runner_module.BenchmarkError, match="collector-sample-loss"):
        runner.run_case(run_id, case["id"])

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    envelope = read_json(sample_dir / "evidence-envelope.json")
    assert collection["sustainedMissed"] > 0 or collection["transitionMissed"] > 0
    assert envelope["status"] == "invalid"
    assert "collector-sample-loss" in envelope["invalidation"]["reasons"]


@pytest.mark.parametrize(
    "case_id",
    (
        "decoder-failure-recovery",
        "camilladsp-invalid-configuration",
        "camilladsp-control-interruption",
        "camilladsp-restart-and-rollback",
        "recovery-service-matrix",
    ),
)
@pytest.mark.parametrize("failure", (None, "failed", "timeout", "interrupted"))
def test_every_disruptive_campaign_restores_for_all_lifecycle_outcomes(
    tmp_path: Path,
    case_id: str,
    failure: str | None,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, case_id)
    run_id = runner.prepare(case_ids=[case_id], run_id=f"matrix-{case_id}-{failure or 'success'}")
    platform.failure = failure

    if failure is None:
        assert runner.run_case(run_id, case_id) == "characterized"
        expected_units = len(runner._execution_units(case))
        assert platform.restore_calls == expected_units
        envelopes = sorted(
            (runner.run_dir(run_id) / f"cases/{case_id}").glob("*/evidence-envelope.json")
        )
        assert len(envelopes) == expected_units
        assert all(read_json(path)["restoration"]["status"] == "restored" for path in envelopes)
    else:
        expected_exception = (
            runner_module.CaseTimeout
            if failure == "timeout"
            else (
                runner_module.InterruptedCase
                if failure == "interrupted"
                else runner_module.BenchmarkError
            )
        )
        with pytest.raises(expected_exception):
            runner.run_case(run_id, case_id)
        assert platform.restore_calls == 1
        envelope = read_json(
            runner.run_dir(run_id) / f"cases/{case_id}/{case_id}-sample-0001/evidence-envelope.json"
        )
        assert envelope["restoration"]["status"] == "restored"


def test_topology_signature_uses_stable_node_and_port_names() -> None:
    dump = [
        {
            "id": 10,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "source"}},
        },
        {
            "id": 11,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "sink"}},
        },
        {
            "id": 20,
            "type": "PipeWire:Interface:Port",
            "info": {"props": {"node.id": 10, "port.name": "output_FL"}},
        },
        {
            "id": 21,
            "type": "PipeWire:Interface:Port",
            "info": {"props": {"node.id": 11, "port.name": "input_FL"}},
        },
        {
            "id": 30,
            "type": "PipeWire:Interface:Link",
            "info": {
                "props": {
                    "open-cinema.owner": "open-cinema.orchestrator",
                    "link.output.node": 10,
                    "link.output.port": 20,
                    "link.input.node": 11,
                    "link.input.port": 21,
                }
            },
        },
    ]
    topology = runner_module.LinuxPlatform.topology_from_dump(dump)
    assert topology["ownedLinkCount"] == 1
    assert topology["links"] == [{"output": ["source", "output_FL"], "input": ["sink", "input_FL"]}]
    assert len(topology["digest"]) == 64


def test_contract_loader_rejects_fault_injection_outside_declared_services(
    tmp_path: Path,
) -> None:
    contracts = contract_copy(tmp_path)
    manifest_path = contracts / "cases.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    recovery = next(case for case in manifest["cases"] if case["id"] == "decoder-failure-recovery")
    recovery["disruptive_services"] = ["ssh.service"]
    manifest["restoration_actions"]["restore-processor-and-active-intent"][
        "allowed_services"
    ].append("ssh.service")
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(runner_module.ContractError, match="unknown runtime services"):
        runner_module.Contracts.load(contracts)


def test_workload_lifecycle_wraps_collection_fault_injection_and_cleanup(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    bound_case(runner, "decoder-failure-recovery")
    run_id = runner.prepare(case_ids=["decoder-failure-recovery"], run_id="workload-run")

    assert runner.run_case(run_id, "decoder-failure-recovery") == "characterized"

    assert len(platform.workloads) == 1
    workload = platform.workloads[0]
    assert workload.started is True
    assert workload.stopped is True
    assert workload.faults == [["pcm-auto-decoder@decoder-0.service"]]
    events = runner_module.BenchmarkRunner._read_jsonl(
        runner.run_dir(run_id)
        / "cases/decoder-failure-recovery/decoder-failure-recovery-sample-0001/case-events.jsonl"
    )
    assert "workload-started" in {event["event"] for event in events}
    assert "workload-restored-after-fault" in {event["event"] for event in events}
    assert "workload-stopped" in {event["event"] for event in events}


def test_declared_scheduled_transitions_execute_driver_actions(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    declared = next(case for case in runner.contracts.cases["cases"] if case["id"] == "soak-pcm")
    declared["warm_up_repetitions"] = 0
    declared["measured_repetitions"] = 1
    declared["duration_seconds"] = 3
    declared["timeout_seconds"] = 10
    declared["transition_schedule_seconds"] = [1, 2]
    run_id = runner.prepare(case_ids=["soak-pcm"], run_id="scheduled-actions-run")

    assert runner.run_case(run_id, "soak-pcm") == "characterized"

    assert platform.workloads[0].transitions == [
        ("reconciliation-refresh", 0),
        ("reconciliation-refresh", 1),
    ]
    events = runner_module.BenchmarkRunner._read_jsonl(
        runner.run_dir(run_id) / "cases/soak-pcm/soak-pcm-sample-0001/case-events.jsonl"
    )
    executed = [event for event in events if event["event"] == "scheduled-transition-executed"]
    assert [event["scheduleIndex"] for event in executed] == [0, 1]


def test_physical_and_bluetooth_cases_prepare_as_explicitly_unavailable(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(
        case_ids=["routing-headset-takeover", "boot-persistence-saved-intent"],
        run_id="manual-fixtures-run",
    )

    state = read_json(runner.run_dir(run_id) / "run-state.json")
    for case_id in ("routing-headset-takeover", "boot-persistence-saved-intent"):
        assert state["cases"][case_id]["status"] == "fixture-unavailable"
        assert state["cases"][case_id]["unavailableReasons"]
        assert runner.run_case(run_id, case_id) == "fixture-unavailable"


def test_processor_fixture_matrix_creates_one_repetition_set_per_profile(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    case = runner.contracts.case("camilladsp-profiles-128")

    units = runner._execution_units(case)

    expected_profiles = case["processor_fixture_matrix"]
    assert {unit["processorFixture"] for unit in units} == set(expected_profiles)
    repetitions_per_profile = int(case["warm_up_repetitions"]) + int(case["measured_repetitions"])
    assert len(units) == len(expected_profiles) * repetitions_per_profile


def test_nearest_rank_p95_and_redaction_are_deterministic() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert runner_module.summary_statistics(values) == {
        "count": 5,
        "median": 3.0,
        "p95NearestRank": 100.0,
        "maximum": 100.0,
    }
    redacted = runner_module.redact_document(
        {"device": "AA_BB_CC_DD_EE_FF", "nested": {"apiToken": "secret-value"}}
    )
    assert redacted == {"device": "[redacted]", "nested": {"apiToken": "[redacted]"}}


def test_required_physical_capture_remains_not_measured_without_calibration(
    tmp_path: Path,
) -> None:
    runner, _platform = make_runner(tmp_path)
    bound_case(runner, "camilladsp-invalid-configuration")
    runner.contracts.fixture["measurement"]["physical_timing"] = {
        "state": "uncalibrated",
        "acceptance_metrics_available": False,
    }
    run_id = runner.prepare(
        case_ids=["camilladsp-invalid-configuration"], run_id="physical-not-measured"
    )

    assert runner.run_case(run_id, "camilladsp-invalid-configuration") == "not-measured"
    summary = runner.finalize(run_id)
    assert summary["overallStatus"] == "not-measured"
    envelope = read_json(
        runner.run_dir(run_id) / "cases/camilladsp-invalid-configuration/"
        "camilladsp-invalid-configuration-sample-0001/evidence-envelope.json"
    )
    assert envelope["status"] == "not-measured"
    assert envelope["metricCoverage"]["physical-audio"]["status"] == "not-measured"
    assert "required-metric-not-measured:physical-audio" in envelope["invalidation"]["reasons"]


def test_unhealthy_programme_playback_fails_the_sample(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    run_id = runner.prepare(case_ids=["decoder-pcm-stereo"], run_id="playback-failure")
    platform.failure = "playback"

    with pytest.raises(runner_module.BenchmarkError, match="ended with failed"):
        runner.run_case(run_id, "decoder-pcm-stereo")

    envelope = read_json(
        runner.run_dir(run_id)
        / "cases/decoder-pcm-stereo/decoder-pcm-stereo-sample-0001/evidence-envelope.json"
    )
    assert envelope["status"] == "failed"
    assert platform.workloads[0].health_calls >= 1


def test_playback_logs_are_enveloped_checksummed_and_exported(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    run_id = runner.prepare(
        case_ids=["baseline-fixture-and-topology"], run_id="playback-log-evidence"
    )
    runner.run_case(run_id, "baseline-fixture-and-topology")
    runner.finalize(run_id)
    sample_dir = (
        runner.run_dir(run_id)
        / "cases/baseline-fixture-and-topology/baseline-fixture-and-topology-sample-0001"
    )
    envelope = read_json(sample_dir / "evidence-envelope.json")
    logs = {Path(item["path"]).name: item for item in envelope["logs"]}
    assert logs["fake-ffmpeg.log"]["sha256"] == runner_module.sha256_file(
        sample_dir / "fake-ffmpeg.log"
    )
    assert logs["fake-pw-cat.log"]["sha256"] == runner_module.sha256_file(
        sample_dir / "fake-pw-cat.log"
    )
    assert (
        runner.run_dir(run_id) / "export/cases/baseline-fixture-and-topology/"
        "baseline-fixture-and-topology-sample-0001/fake-ffmpeg.log"
    ).is_file()


def test_pipewire_playback_status_requires_an_active_link_to_exact_target() -> None:
    dump = [
        {
            "id": 10,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "open-cinema.benchmark.playback.token"}},
        },
        {
            "id": 11,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "open-cinema.decoder.decoder-0.capture"}},
        },
        {
            "id": 20,
            "type": "PipeWire:Interface:Link",
            "info": {
                "state": "active",
                "props": {"link.output.node": 10, "link.input.node": 11},
            },
        },
    ]
    status = runner_module.LinuxPlatform.playback_link_status_from_dump(
        dump,
        node_name="open-cinema.benchmark.playback.token",
        target_node="open-cinema.decoder.decoder-0.capture",
    )
    assert status["linked"] is True
    assert status["active"] is True
    status = runner_module.LinuxPlatform.playback_link_status_from_dump(
        dump,
        node_name="open-cinema.benchmark.playback.token",
        target_node="missing.target",
    )
    assert status["linked"] is False
    assert status["active"] is False


def test_persisted_workload_journal_restores_camilladsp_and_clears_it(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    sample_dir = run_dir / "cases/case/sample"
    sample_dir.mkdir(parents=True)
    original = {"devices": {"samplerate": 48_000, "chunksize": 128}}
    journal_path = sample_dir / "workload-restore.json"
    journal_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "active": True,
                "playback": {
                    "handleId": "a" * 32,
                    "feederProcessGroup": 101,
                    "playerProcessGroup": 102,
                },
                "camilladspOriginalConfiguration": original,
                "camilladspOriginalConfigurationSha256": runner_module.digest_document(original),
            }
        ),
        encoding="utf-8",
    )
    platform = object.__new__(runner_module.LinuxPlatform)
    stopped: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    platform._stop_persisted_playback = lambda record: stopped.append(dict(record)) or {
        "handleId": record["handleId"]
    }
    platform.service_state = lambda _unit: {"active": True}
    platform.apply_camilladsp_configuration = lambda configuration: applied.append(
        dict(configuration)
    ) or {"state": "running"}
    platform.camilladsp_active_configuration = lambda: original
    platform.utc_now = lambda: "2026-08-26T00:00:00.000000Z"

    result = platform.restore_workload_journals(run_dir)

    assert result["activeJournalCount"] == 1
    assert stopped[0]["handleId"] == "a" * 32
    assert applied == [original]
    cleared = read_json(journal_path)
    assert cleared["active"] is False
    assert cleared["camilladspOriginalConfiguration"] is None


def test_supported_fixture_uses_observed_wlan_controller_link(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    facts = platform.fixture_facts(runner.contracts.fixture)
    assert runner._fixture_comparison(facts)["matchesSupportedFixture"] is True
    facts["network"][0]["operstate"] = "down"
    comparison = runner._fixture_comparison(facts)
    assert comparison["matchesSupportedFixture"] is False
    assert "primary-network-mismatch" in comparison["reasons"]
