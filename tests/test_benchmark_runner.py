from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import threading
import time
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
    media_root = target / "media"
    (media_root / "generated").mkdir(parents=True)
    (media_root / "camilladsp").mkdir()
    (media_root / "manifest.json").write_text(
        json.dumps(
            {
                "fixtureContractId": "pi5-8gb-gab8-native-v1",
                "fixtures": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (media_root / "camilladsp/profiles.json").write_text(
        json.dumps(
            {
                "assets": [],
                "fixtureContractId": "pi5-8gb-gab8-native-v1",
                "profiles": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (media_root / "physical-path.yml").write_text(
        "schema_version: 1\nstate: not-calibrated\n",
        encoding="utf-8",
    )
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
        self.active_workload_journals = 0
        self.transition_capture_ns: list[int] = []
        self.camilladsp_fixture_preparations = 0

    def monotonic_ns(self) -> int:
        return self.now_ns

    def utc_now(self) -> str:
        seconds = self.now_ns / 1_000_000_000
        return f"2026-08-26T00:00:{seconds:09.6f}Z"

    def boot_id(self) -> str:
        return "recorded-boot-id"

    def sleep(self, seconds: float) -> None:
        self.now_ns += int(seconds * 1_000_000_000)
        time.sleep(0)

    def _overhead(self, milliseconds: int = 1) -> None:
        self.now_ns += milliseconds * 1_000_000

    def journal_marker(self, run_id: str) -> dict[str, str]:
        return {"marker": f"marker:{run_id}", "cursor": "recorded-cursor"}

    def ensure_camilladsp_benchmark_fixtures(self) -> dict[str, Any]:
        self.camilladsp_fixture_preparations += 1
        return {
            "definitionId": "benchmark-definition",
            "definitionLabel": "camilladsp-native-v1",
            "fixtures": {
                "camilladsp-passthrough-128": {"revisionId": "revision-passthrough"},
                "camilladsp-stereo-128": {"revisionId": "revision-stereo"},
                "camilladsp-multichannel-128": {"revisionId": "revision-multichannel"},
                "camilladsp-production-fir-iir-128": {"revisionId": "revision-production"},
            },
        }

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
        active = self.active_workload_journals
        self.active_workload_journals = 0
        return {
            "activeJournalCount": active,
            "playbackActions": [],
            "camilladspAction": None,
        }

    def transition_sample(self) -> dict[str, Any]:
        self.transition_capture_ns.append(self.now_ns)
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


def make_runner(
    tmp_path: Path,
    *,
    implementation_paths: dict[str, Path] | None = None,
) -> tuple[Any, FakePlatform]:
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
        implementation_paths=implementation_paths,
    )
    return runner, platform


def bound_case(
    runner: Any,
    case_id: str,
    *,
    duration_seconds: int | float = 1,
    timeout_seconds: int | float = 5,
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


def implementation_source_files(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "benchmark-implementation"
    root.mkdir()
    paths = {name: root / f"{name}.py" for name in runner_module.IMPLEMENTATION_COMPONENTS}
    for name, path in paths.items():
        path.write_text(f"# recorded {name} implementation\n", encoding="utf-8")
    return paths


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


@pytest.mark.parametrize("changed_component", runner_module.IMPLEMENTATION_COMPONENTS)
def test_resume_rejects_implementation_drift_before_allocating_an_attempt(
    tmp_path: Path,
    changed_component: str,
) -> None:
    implementation_paths = implementation_source_files(tmp_path)
    runner, platform = make_runner(tmp_path, implementation_paths=implementation_paths)
    case = bound_case(runner, "decoder-failure-recovery")
    run_id = runner.prepare(case_ids=[case["id"]], run_id=f"drift-{changed_component}")
    platform.failure = "failed"

    with pytest.raises(runner_module.BenchmarkError):
        runner.run_case(run_id, case["id"])

    run_dir = runner.run_dir(run_id)
    state_before_drift = read_json(run_dir / "run-state.json")
    identity = read_json(run_dir / "manifests/implementation-identity.json")
    sample_identity = read_json(
        run_dir / f"cases/{case['id']}/{case['id']}-sample-0001/sample-manifest.json"
    )["implementationIdentity"]
    assert identity == state_before_drift["implementationIdentity"] == sample_identity
    assert set(identity["components"]) == set(runner_module.IMPLEMENTATION_COMPONENTS)
    for name, path in implementation_paths.items():
        assert identity["components"][name] == {
            "fileName": path.name,
            "sha256": runner_module.sha256_file(path),
        }
    identity_path = run_dir / "manifests/implementation-identity.json"
    assert state_before_drift["manifestDigests"][identity_path.name] == (
        runner_module.sha256_file(identity_path)
    )

    implementation_paths[changed_component].write_text(
        f"# changed {changed_component} implementation\n",
        encoding="utf-8",
    )
    platform.failure = None

    with pytest.raises(
        runner_module.BenchmarkError,
        match=rf"implementation changed after prepare.*{changed_component}.*prepare a new run",
    ):
        runner.run_case(run_id, case["id"], resume=True)

    assert read_json(run_dir / "run-state.json") == state_before_drift
    assert [path.name for path in (run_dir / f"cases/{case['id']}").iterdir()] == [
        f"{case['id']}-sample-0001"
    ]


def test_resume_restores_active_workload_before_rejecting_implementation_drift(
    tmp_path: Path,
) -> None:
    implementation_paths = implementation_source_files(tmp_path)
    runner, platform = make_runner(tmp_path, implementation_paths=implementation_paths)
    case = bound_case(runner, "decoder-failure-recovery")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="restore-before-drift")
    platform.failure = "failed"
    with pytest.raises(runner_module.BenchmarkError):
        runner.run_case(run_id, case["id"])

    platform.failure = None
    platform.active_workload_journals = 1
    implementation_paths["benchmarkRunner"].write_text(
        "# changed runner implementation\n",
        encoding="utf-8",
    )

    with pytest.raises(
        runner_module.BenchmarkError,
        match="implementation changed after prepare.*benchmarkRunner",
    ):
        runner.run_case(run_id, case["id"], resume=True)

    assert platform.active_workload_journals == 0
    assert platform.restore_calls == 2
    assert (runner.run_dir(run_id) / "resume-workload-restoration.json").is_file()


def test_run_rejects_a_modified_frozen_implementation_identity(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="frozen-identity-drift")
    identity_path = runner.run_dir(run_id) / "manifests/implementation-identity.json"
    identity_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        runner_module.BenchmarkError,
        match="frozen implementation identity changed after prepare",
    ):
        runner.run_case(run_id, case["id"])

    assert not (runner.run_dir(run_id) / "cases" / case["id"]).exists()


@pytest.mark.parametrize("changed_contract", runner_module.CONTRACT_FILES)
def test_run_rejects_contract_drift_before_allocating_an_attempt(
    tmp_path: Path,
    changed_contract: str,
) -> None:
    runner, _platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id=f"contract-{changed_contract}")
    contract_path = runner.contracts.root / changed_contract
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        runner_module.BenchmarkError,
        match=rf"contracts changed after prepare.*{re.escape(changed_contract)}",
    ):
        runner.run_case(run_id, case["id"])

    case_dir = runner.run_dir(run_id) / "cases" / case["id"]
    assert not case_dir.exists()


def test_prepare_freezes_registry_assets_and_run_rejects_live_asset_drift(
    tmp_path: Path,
) -> None:
    runner, _platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    asset = runner.contracts.root / "media/generated/registered.raw"
    asset.write_bytes(b"frozen-workload-bytes")
    registry_path = runner.contracts.root / "media/manifest.json"
    registry = read_json(registry_path)
    registry["fixtures"].append(
        {
            "id": "registered-test-media",
            "path": asset.name,
            "sha256": runner_module.sha256_file(asset),
            "sizeBytes": asset.stat().st_size,
        }
    )
    registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")

    run_id = runner.prepare(case_ids=[case["id"]], run_id="frozen-workload-input")
    run_dir = runner.run_dir(run_id)
    frozen_asset = run_dir / "manifests/media/generated/registered.raw"
    state = read_json(run_dir / "run-state.json")
    assert frozen_asset.read_bytes() == b"frozen-workload-bytes"
    assert state["manifestDigests"]["media/generated/registered.raw"] == (
        runner_module.sha256_file(frozen_asset)
    )

    asset.write_bytes(b"changed-workload-bytes")
    with pytest.raises(
        runner_module.BenchmarkError,
        match="contracts changed after prepare.*media/generated/registered.raw",
    ):
        runner.run_case(run_id, case["id"])

    assert frozen_asset.read_bytes() == b"frozen-workload-bytes"
    assert not (run_dir / "cases" / case["id"]).exists()


def test_default_workload_driver_reads_only_the_frozen_run_inputs(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    runner.workload_driver_factory = None
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="frozen-driver-input")
    unit = runner._execution_units(case)[0]
    sample_dir = runner.run_dir(run_id) / "sample"
    workload = runner._workload_driver(
        state=read_json(runner.run_dir(run_id) / "run-state.json"),
        case=case,
        unit=unit,
        sample_dir=sample_dir,
    )

    assert workload.contracts_root == runner.run_dir(run_id) / "manifests"
    assert workload.media_root == runner.run_dir(run_id) / "manifests/media"


def test_finalize_rejects_implementation_drift(tmp_path: Path) -> None:
    implementation_paths = implementation_source_files(tmp_path)
    runner, _platform = make_runner(tmp_path, implementation_paths=implementation_paths)
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="finalize-drift")
    assert runner.run_case(run_id, case["id"]) == "characterized"
    implementation_paths["workloadDriver"].write_text(
        "# changed workload driver implementation\n",
        encoding="utf-8",
    )

    with pytest.raises(
        runner_module.BenchmarkError,
        match="implementation changed after prepare.*workloadDriver",
    ):
        runner.finalize(run_id)

    assert read_json(runner.run_dir(run_id) / "run-state.json")["finalized"] is False


def test_finalize_rejects_contract_drift(tmp_path: Path) -> None:
    runner, _platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="finalize-contract-drift")
    assert runner.run_case(run_id, case["id"]) == "characterized"
    contract_path = runner.contracts.root / "criteria-policy.yml"
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        runner_module.BenchmarkError,
        match="contracts changed after prepare.*criteria-policy.yml",
    ):
        runner.finalize(run_id)

    assert read_json(runner.run_dir(run_id) / "run-state.json")["finalized"] is False


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
    sustained = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "collector-batches.jsonl")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition-batches.jsonl")
    assert sustained and transitions
    assert all(row["collectorOverheadNs"] >= 0 for row in sustained + transitions)
    assert summary["statistics"]["sustainedCollectorOverheadMs"]["count"] == len(sustained)
    assert summary["statistics"]["transitionCollectorOverheadMs"]["count"] == len(transitions)


def test_collector_intervals_include_probe_and_payload_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    original_append_jsonl = runner_module.append_jsonl

    def sustained_sample() -> dict[str, Any]:
        platform._overhead(9)
        return FakePlatform.sustained_sample(platform)

    def native_health() -> dict[str, Any]:
        platform._overhead(19)
        return FakePlatform.native_health(platform)

    def event_storage_sample() -> dict[str, Any]:
        platform._overhead(29)
        return FakePlatform.event_storage_sample(platform)

    def timed_append_jsonl(path: Path, value: object) -> None:
        if path.name in {
            "system.jsonl",
            "native-health.jsonl",
            "event-storage.jsonl",
            "transition.jsonl",
        }:
            platform._overhead(5)
        original_append_jsonl(path, value)

    class ImmediateFuture:
        def __init__(self, value: dict[str, Any]) -> None:
            self.value = value

        def done(self) -> bool:
            return True

        def result(self, timeout: float | None = None) -> dict[str, Any]:
            del timeout
            return self.value

    class ImmediateExecutor:
        def __init__(self, **_arguments: object) -> None:
            pass

        def submit(self, function, *arguments, **keyword_arguments):
            return ImmediateFuture(function(*arguments, **keyword_arguments))

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            assert wait is True
            assert isinstance(cancel_futures, bool)

    platform.sustained_sample = sustained_sample  # type: ignore[method-assign]
    platform.native_health = native_health  # type: ignore[method-assign]
    platform.event_storage_sample = event_storage_sample  # type: ignore[method-assign]
    monkeypatch.setattr(runner_module, "append_jsonl", timed_append_jsonl)
    monkeypatch.setattr(runner_module, "ThreadPoolExecutor", ImmediateExecutor)
    case = bound_case(runner, "baseline-fixture-and-topology")
    run_id = runner.prepare(case_ids=[case["id"]], run_id="collector-interval-run")

    assert runner.run_case(run_id, case["id"]) == "characterized"
    summary = runner.finalize(run_id)
    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    sustained = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "collector-batches.jsonl")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition-batches.jsonl")

    assert [row["persistenceOverheadNs"] for row in sustained] == [15_000_000]
    assert sustained[0]["collectorOverheadNs"] >= (
        sustained[0]["probeOverheadNs"] + sustained[0]["persistenceOverheadNs"]
    )
    assert all(row["collectorOverheadNs"] == 6_000_000 for row in transitions)
    sustained_overhead_ms = sustained[0]["collectorOverheadNs"] / 1_000_000
    assert summary["statistics"]["sustainedCollectorOverheadMs"] == {
        "count": 1,
        "median": sustained_overhead_ms,
        "p95NearestRank": sustained_overhead_ms,
        "maximum": sustained_overhead_ms,
    }


def test_transition_cadence_is_independent_of_a_slow_sustained_batch(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    sustained_started = threading.Event()
    release_sustained = threading.Event()
    original_sustained_sample = platform.sustained_sample
    original_transition_sample = platform.transition_sample

    def delayed_sustained_sample() -> dict[str, Any]:
        sustained_started.set()
        if not release_sustained.wait(timeout=2):
            raise RuntimeError("test sustained collector was not released")
        return original_sustained_sample()

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 3:
            release_sustained.set()
        return sample

    platform.sustained_sample = delayed_sustained_sample  # type: ignore[method-assign]
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="independent-cadence-run")

    try:
        assert runner.run_case(run_id, case["id"]) == "characterized"
    finally:
        release_sustained.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition.jsonl")
    assert sustained_started.is_set()
    assert collection["transitionSamples"] == 5
    assert collection["transitionMissed"] == 0
    assert collection["sustainedMissed"] == 0
    assert [row["sequence"] for row in transitions] == [1, 2, 3, 4, 5]
    first_scheduled = transitions[0]["scheduledMonotonicNs"]
    assert [row["scheduledMonotonicNs"] for row in transitions] == [
        first_scheduled + index * 200_000_000 for index in range(5)
    ]


def test_sustained_probe_components_run_concurrently(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    probe_barrier = threading.Barrier(4)
    probe_threads: list[str] = []

    def rendezvous() -> None:
        probe_threads.append(threading.current_thread().name)
        probe_barrier.wait(timeout=2)

    original_sustained_sample = platform.sustained_sample
    original_native_health = platform.native_health
    original_event_storage_sample = platform.event_storage_sample

    def sustained_sample() -> dict[str, Any]:
        rendezvous()
        return original_sustained_sample()

    def native_health() -> dict[str, Any]:
        rendezvous()
        return original_native_health()

    def event_storage_sample() -> dict[str, Any]:
        rendezvous()
        return original_event_storage_sample()

    class ConcurrentProbeWorkload(FakeWorkloadDriver):
        def health(self) -> dict[str, Any]:
            if self.health_calls == 1:
                rendezvous()
            return super().health()

    platform.sustained_sample = sustained_sample  # type: ignore[method-assign]
    platform.native_health = native_health  # type: ignore[method-assign]
    platform.event_storage_sample = event_storage_sample  # type: ignore[method-assign]
    runner.workload_driver_factory = lambda **arguments: ConcurrentProbeWorkload(
        platform=platform,
        **arguments,
    )
    run_id = runner.prepare(case_ids=[case["id"]], run_id="parallel-sustained-probes-run")

    assert runner.run_case(run_id, case["id"]) == "characterized"
    assert sorted(probe_threads) == [
        "open-cinema-sustained-probe_0",
        "open-cinema-sustained-probe_1",
        "open-cinema-sustained-probe_2",
        "open-cinema-sustained-probe_3",
    ]


def test_preflight_workload_health_is_outside_the_measurement_cadence(
    tmp_path: Path,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")

    class SlowInitialHealthWorkload(FakeWorkloadDriver):
        def health(self) -> dict[str, Any]:
            if self.health_calls == 0:
                self.platform._overhead(250)
            return super().health()

    runner.workload_driver_factory = lambda **arguments: SlowInitialHealthWorkload(
        platform=platform,
        **arguments,
    )
    run_id = runner.prepare(case_ids=[case["id"]], run_id="preflight-health-run")

    assert runner.run_case(run_id, case["id"]) == "characterized"
    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition.jsonl")
    assert collection["transitionMissed"] == 0
    assert collection["transitionSamples"] == 5
    assert [row["sequence"] for row in transitions] == [1, 2, 3, 4, 5]


def test_transition_cadence_is_independent_of_slow_sustained_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    persistence_started = threading.Event()
    release_persistence = threading.Event()
    persistence_threads: list[str] = []
    original_append_jsonl = runner_module.append_jsonl
    original_transition_sample = platform.transition_sample

    def delayed_append_jsonl(path: Path, value: object) -> None:
        if path.name == "system.jsonl" and not persistence_started.is_set():
            persistence_threads.append(threading.current_thread().name)
            persistence_started.set()
            if not release_persistence.wait(timeout=2):
                raise RuntimeError("test sustained persistence was not released")
        original_append_jsonl(path, value)

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 3:
            release_persistence.set()
        return sample

    monkeypatch.setattr(runner_module, "append_jsonl", delayed_append_jsonl)
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="independent-persistence-run")

    try:
        assert runner.run_case(run_id, case["id"]) == "characterized"
    finally:
        release_persistence.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition.jsonl")
    assert persistence_threads == ["open-cinema-sustained-persistence_0"]
    assert collection["transitionSamples"] == 5
    assert collection["transitionMissed"] == 0
    assert collection["sustainedMissed"] == 0
    assert [row["sequence"] for row in transitions] == [1, 2, 3, 4, 5]
    assert all(
        len(runner_module.BenchmarkRunner._read_jsonl(sample_dir / name)) == 1
        for name in ("system.jsonl", "native-health.jsonl", "event-storage.jsonl")
    )


def test_transition_cadence_is_independent_of_slow_durable_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    persistence_started = threading.Event()
    release_persistence = threading.Event()
    persistence_threads: list[str] = []
    original_append_jsonl = runner_module.append_jsonl
    original_transition_sample = platform.transition_sample

    def delayed_append_jsonl(path: Path, value: object) -> None:
        if path.name == "transition.jsonl" and not persistence_started.is_set():
            persistence_threads.append(threading.current_thread().name)
            persistence_started.set()
            if not release_persistence.wait(timeout=2):
                raise RuntimeError("test transition persistence was not released")
        original_append_jsonl(path, value)

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 3:
            assert persistence_started.wait(timeout=1)
            release_persistence.set()
        return sample

    monkeypatch.setattr(runner_module, "append_jsonl", delayed_append_jsonl)
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="transition-persistence-run")

    try:
        assert runner.run_case(run_id, case["id"]) == "characterized"
    finally:
        release_persistence.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition.jsonl")
    intervals = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition-batches.jsonl")
    assert persistence_threads == ["open-cinema-transition-persistence_0"]
    assert collection["transitionSamples"] == 5
    assert collection["transitionMissed"] == 0
    assert [row["sequence"] for row in transitions] == [1, 2, 3, 4, 5]
    assert [row["sequence"] for row in intervals] == [1, 2, 3, 4, 5]


def test_completed_sustained_future_is_rechecked_at_the_due_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(
        runner,
        "baseline-fixture-and-topology",
        duration_seconds=2,
    )
    submitted = 0

    class ControlledFuture:
        def __init__(self, value: dict[str, Any], *, delay_boundary_visibility: bool) -> None:
            self.value = value
            self.delay_boundary_visibility = delay_boundary_visibility
            self.boundary_polls = 0

        def done(self) -> bool:
            if not self.delay_boundary_visibility:
                return True
            if platform.now_ns < 1_000_000_000:
                return False
            self.boundary_polls += 1
            return self.boundary_polls >= 3

        def result(self, timeout: float | None = None) -> dict[str, Any]:
            del timeout
            return self.value

    class ControlledExecutor:
        def __init__(self, **arguments: object) -> None:
            self.prefix = arguments.get("thread_name_prefix")

        def submit(self, function, *arguments, **keyword_arguments):
            nonlocal submitted
            value = function(*arguments, **keyword_arguments)
            if self.prefix == "open-cinema-sustained-collector":
                submitted += 1
                return ControlledFuture(value, delay_boundary_visibility=submitted == 1)
            return ControlledFuture(value, delay_boundary_visibility=False)

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            assert wait is True
            assert isinstance(cancel_futures, bool)

    monkeypatch.setattr(runner_module, "ThreadPoolExecutor", ControlledExecutor)
    run_id = runner.prepare(case_ids=[case["id"]], run_id="boundary-recheck-run")

    assert runner.run_case(run_id, case["id"]) == "characterized"

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    system = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "system.jsonl")
    assert collection["sustainedMissed"] == 0
    assert collection["sustainedSamples"] == 2
    assert [row["sequence"] for row in system] == [1, 2]


def test_collector_overhead_sample_loss_invalidates_evidence(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(
        runner,
        "baseline-fixture-and-topology",
        duration_seconds=3,
        timeout_seconds=10,
    )
    assert case["duration_seconds"] == 3
    sustained_started = threading.Event()
    release_sustained = threading.Event()
    original_sustained_sample = platform.sustained_sample
    original_transition_sample = platform.transition_sample

    def delayed_sustained_sample() -> dict[str, Any]:
        sustained_started.set()
        if not release_sustained.wait(timeout=2):
            raise RuntimeError("test sustained collector was not released")
        return original_sustained_sample()

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 7:
            release_sustained.set()
        return sample

    platform.sustained_sample = delayed_sustained_sample  # type: ignore[method-assign]
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="collector-loss-run")

    try:
        with pytest.raises(runner_module.BenchmarkError, match="collector-sample-loss"):
            runner.run_case(run_id, case["id"])
    finally:
        release_sustained.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    envelope = read_json(sample_dir / "evidence-envelope.json")
    system = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "system.jsonl")
    assert sustained_started.is_set()
    assert collection["sustainedMissed"] > 0
    assert collection["transitionMissed"] == 0
    assert collection["sustainedSamples"] == len(system)
    assert 0 < len(system) < 3
    sequences = [row["sequence"] for row in system]
    assert sequences[0] == 1
    assert 2 not in sequences
    assert envelope["status"] == "invalid"
    assert "collector-sample-loss" in envelope["invalidation"]["reasons"]


def test_collection_result_counts_only_persisted_transition_samples(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "baseline-fixture-and-topology")
    original_transition_sample = platform.transition_sample

    def delayed_transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        platform._overhead(450)
        return sample

    platform.transition_sample = delayed_transition_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="transition-count-run")

    with pytest.raises(runner_module.BenchmarkError, match="collector-sample-loss"):
        runner.run_case(run_id, case["id"])

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    transitions = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "transition.jsonl")
    system = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "system.jsonl")
    events = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "case-events.jsonl")
    measurement_start = next(
        row["monotonicNs"] for row in events if row["event"] == "measurement-start"
    )
    assert collection["transitionMissed"] > 0
    assert collection["transitionSamples"] == len(transitions)
    assert collection["sustainedSamples"] == len(system) == 1
    assert collection["sustainedMissed"] == 0
    assert all(
        row["scheduledMonotonicNs"] < measurement_start + 1_000_000_000
        for row in system + transitions
    )
    assert [row["sequence"] for row in transitions] != list(range(1, len(transitions) + 1))


def test_sustained_collector_failure_propagates_before_restoration(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "decoder-failure-recovery")

    def failed_sustained_sample() -> dict[str, Any]:
        raise RuntimeError("recorded sustained collector failure")

    platform.sustained_sample = failed_sustained_sample  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="sustained-failure-run")

    with pytest.raises(runner_module.BenchmarkError, match="RuntimeError"):
        runner.run_case(run_id, case["id"])

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    failure = read_json(sample_dir / "failure.json")
    assert failure["type"] == "RuntimeError"
    assert platform.restore_calls == 1


def test_sustained_persistence_failure_propagates_before_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "decoder-failure-recovery")
    original_append_jsonl = runner_module.append_jsonl

    def failed_append_jsonl(path: Path, value: object) -> None:
        if path.name == "system.jsonl":
            raise OSError("recorded sustained persistence failure")
        original_append_jsonl(path, value)

    monkeypatch.setattr(runner_module, "append_jsonl", failed_append_jsonl)
    run_id = runner.prepare(case_ids=[case["id"]], run_id="sustained-persistence-failure-run")

    with pytest.raises(runner_module.BenchmarkError, match="OSError"):
        runner.run_case(run_id, case["id"])

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    failure = read_json(sample_dir / "failure.json")
    assert failure["type"] == "OSError"
    assert not (sample_dir / "system.jsonl").exists()
    assert not (sample_dir / "native-health.jsonl").exists()
    assert not (sample_dir / "event-storage.jsonl").exists()
    assert platform.restore_calls == 1


def test_foreground_failure_drains_sustained_worker_before_restoration(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "decoder-failure-recovery")
    sustained_started = threading.Event()
    release_sustained = threading.Event()
    timeline: list[str] = []
    original_sustained_sample = platform.sustained_sample
    original_transition_sample = platform.transition_sample
    original_restore = platform.restore

    def delayed_sustained_sample() -> dict[str, Any]:
        sustained_started.set()
        if not release_sustained.wait(timeout=2):
            raise RuntimeError("test sustained collector was not released")
        result = original_sustained_sample()
        timeline.append("collector-finished")
        return result

    def failed_transition_sample() -> dict[str, Any]:
        result = original_transition_sample()
        if sustained_started.is_set():
            timeline.append("transition-failed")
            release_sustained.set()
            raise RuntimeError("recorded foreground collector failure")
        return result

    def restore(snapshot: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        timeline.append("restore")
        return original_restore(snapshot, timeout_seconds=timeout_seconds)

    platform.sustained_sample = delayed_sustained_sample  # type: ignore[method-assign]
    platform.transition_sample = failed_transition_sample  # type: ignore[method-assign]
    platform.restore = restore  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="drained-before-restore-run")

    try:
        with pytest.raises(runner_module.BenchmarkError, match="RuntimeError"):
            runner.run_case(run_id, case["id"])
    finally:
        release_sustained.set()

    assert timeline.index("transition-failed") < timeline.index("collector-finished")
    assert timeline.index("collector-finished") < timeline.index("restore")
    assert platform.restore_calls == 1


def test_expired_deadline_joins_sustained_persistence_before_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(
        runner,
        "decoder-failure-recovery",
        duration_seconds=1,
        timeout_seconds=0.05,
    )
    persistence_started = threading.Event()
    release_persistence = threading.Event()
    observations: list[tuple[str, int]] = []
    timeline: list[str] = []
    original_append_jsonl = runner_module.append_jsonl
    original_restore = platform.restore
    original_sleep = platform.sleep
    persistence_start_deadline = time.monotonic() + 2

    def coordinated_sleep(seconds: float) -> None:
        if not persistence_started.is_set():
            if time.monotonic() >= persistence_start_deadline:
                raise RuntimeError("test sustained persistence did not start")
            time.sleep(0.001)
            return
        original_sleep(seconds)

    def delayed_append_jsonl(path: Path, value: object) -> None:
        if path.name == "system.jsonl":
            timeline.append("persistence-started")
            persistence_started.set()
            if not release_persistence.wait(timeout=2):
                raise RuntimeError("test sustained persistence was not released")
            original_append_jsonl(path, value)
            timeline.append("persistence-finished")
            return
        original_append_jsonl(path, value)

    def restore(snapshot: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        timeline.append("restore")
        return original_restore(snapshot, timeout_seconds=timeout_seconds)

    def release_after_observing_blocked_write() -> None:
        started = persistence_started.wait(timeout=2)
        observations.append(("persistence-started", int(started)))
        observations.append(("restore-calls-while-blocked", platform.restore_calls))
        time.sleep(0.1)
        observations.append(("restore-calls-before-release", platform.restore_calls))
        release_persistence.set()

    monkeypatch.setattr(runner_module, "append_jsonl", delayed_append_jsonl)
    platform.sleep = coordinated_sleep  # type: ignore[method-assign]
    platform.restore = restore  # type: ignore[method-assign]
    run_id = runner.prepare(case_ids=[case["id"]], run_id="stuck-sustained-run")
    releaser = threading.Thread(target=release_after_observing_blocked_write)
    releaser.start()

    try:
        with pytest.raises(runner_module.CaseTimeout):
            runner.run_case(run_id, case["id"])
    finally:
        release_persistence.set()
        releaser.join(timeout=2)

    assert not releaser.is_alive()
    assert observations == [
        ("persistence-started", 1),
        ("restore-calls-while-blocked", 0),
        ("restore-calls-before-release", 0),
    ]
    assert timeline.index("persistence-finished") < timeline.index("restore")
    events = runner_module.BenchmarkRunner._read_jsonl(
        runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001/case-events.jsonl"
    )
    drain = next(event for event in events if event["event"] == "sustained-collector-drain-timeout")
    assert drain["workerJoined"] is True
    assert platform.restore_calls == 1


def test_fault_workload_mutation_runs_in_worker_and_joins_before_stop(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "decoder-failure-recovery")
    timeline: list[str] = []
    workload_threads: list[int] = []
    foreground_thread = threading.get_ident()

    class RaceCheckingWorkload(FakeWorkloadDriver):
        def health(self) -> dict[str, Any]:
            workload_threads.append(threading.get_ident())
            return super().health()

        def after_fault_injection(self, services: list[str]) -> dict[str, Any]:
            timeline.append("workload-mutated")
            return super().after_fault_injection(services)

        def stop(self) -> dict[str, Any]:
            timeline.append("workload-stopped")
            return super().stop()

    runner.workload_driver_factory = lambda **arguments: RaceCheckingWorkload(
        platform=platform,
        **arguments,
    )

    run_id = runner.prepare(case_ids=[case["id"]], run_id="background-workload-run")

    assert runner.run_case(run_id, case["id"]) == "characterized"

    assert workload_threads
    assert foreground_thread in workload_threads
    assert any(thread != foreground_thread for thread in workload_threads)
    assert timeline.index("workload-mutated") < timeline.index("workload-stopped")


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


def test_transition_snapshot_bounds_pipewire_topology_timeout() -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    observed_timeouts: list[float] = []
    platform.monotonic_ns = time.monotonic_ns
    platform.runtime_snapshot = lambda: {"available": False}

    def timed_out_topology(*, timeout_seconds: float) -> dict[str, Any]:
        observed_timeouts.append(timeout_seconds)
        raise runner_module.CaseTimeout("fixture pw-dump timeout")

    platform.topology = timed_out_topology
    platform._transition_database_snapshot = lambda: {
        "observedMonotonicNs": None,
        "ageNs": None,
        "refreshInProgress": True,
        "processorProjections": {"available": False},
        "reconciliation": {"available": False},
    }
    platform.decoder_status = lambda: {"available": False}
    platform.camilladsp_status = lambda **_kwargs: {"available": False}

    sample = runner_module.LinuxPlatform.transition_sample(platform)

    assert observed_timeouts == [0.1]
    assert sample["pipewire"] == {
        "available": False,
        "error": "pw-dump-timeout",
        "ownedLinkCount": None,
        "links": [],
        "digest": None,
    }
    assert set(sample["componentProbeOverheadsNs"]) == {
        "runtime",
        "pipewireTopology",
        "databaseSnapshotCache",
        "decoderStatus",
        "camilladspStatus",
    }


def test_native_health_records_a_bounded_pw_top_timeout() -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    platform.monotonic_ns = time.monotonic_ns

    def timed_out_pw_top(*_arguments: object, **_keyword_arguments: object) -> dict[str, Any]:
        raise runner_module.CaseTimeout("fixture pw-top timeout")

    platform._audio_command = timed_out_pw_top
    platform.decoder_status = lambda: {"available": True}
    platform.camilladsp_status = lambda: {"available": True}
    platform._processor_projection = lambda **_kwargs: {"available": True, "rows": []}

    sample = runner_module.LinuxPlatform.native_health(platform)

    assert sample["pipewireObjects"] == []
    assert sample["pipewireTopObservation"] == {
        "available": False,
        "returncode": None,
        "error": "pw-top-timeout",
    }
    assert set(sample["componentProbeOverheadsNs"]) == {
        "pipewireTop",
        "decoderStatus",
        "camilladspStatus",
        "processorProjections",
    }


def test_event_storage_decodes_only_events_after_the_measurement_baseline(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE api_orchestrationevent ("
            "sequence INTEGER PRIMARY KEY, event_type TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO api_orchestrationevent VALUES (1, 'offered', '{}')"
        )
    platform = object.__new__(runner_module.LinuxPlatform)
    platform.database_path = database
    platform._event_storage_lock = threading.Lock()
    platform._event_storage_last_sequence = 0
    platform._event_storage_counts = {
        "offered": 0,
        "processed": 0,
        "coalesced": 0,
        "retried": 0,
        "dropped": 0,
    }
    platform.monotonic_ns = time.monotonic_ns
    platform.command = lambda *_args, **_kwargs: {
        "returncode": 0,
        "stdout": "used_memory:1\n",
        "stderr": "",
    }
    platform._read = lambda *_args, **_kwargs: "recorded-disk-counters"

    assert runner_module.LinuxPlatform.begin_sustained_collection(platform) == {
        "orchestrationEventBaselineSequence": 1
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO api_orchestrationevent VALUES "
            "(2, 'processed', '{\"retried\": 2}')"
        )
    first = runner_module.LinuxPlatform.event_storage_sample(platform)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO api_orchestrationevent VALUES (3, 'coalesced', '{}')"
        )
    second = runner_module.LinuxPlatform.event_storage_sample(platform)

    assert first["orchestrationEvents"] == {
        "offered": 0,
        "processed": 1,
        "coalesced": 0,
        "retried": 2,
        "dropped": 0,
    }
    assert second["orchestrationEvents"] == {
        "offered": 0,
        "processed": 1,
        "coalesced": 1,
        "retried": 2,
        "dropped": 0,
    }


def test_transition_database_refresh_never_blocks_sampling() -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    platform._transition_database_lock = threading.Lock()
    platform._transition_database_worker = None
    platform._transition_database_cache = {
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
    release = threading.Event()
    platform.monotonic_ns = time.monotonic_ns

    def delayed_projection(**_kwargs: Any) -> dict[str, Any]:
        release.wait(timeout=1)
        return {"available": True, "rows": []}

    platform._processor_projection = delayed_projection
    platform._applied_plan_state = lambda **_kwargs: {"available": True, "states": []}

    started = time.monotonic()
    pending = platform._transition_database_snapshot()
    elapsed = time.monotonic() - started
    assert elapsed < 0.05
    assert pending["processorProjections"]["error"] == "database-snapshot-pending"
    assert pending["refreshInProgress"] is True

    release.set()
    worker = platform._transition_database_worker
    assert worker is not None
    worker.join(timeout=1)
    with platform._transition_database_lock:
        assert platform._transition_database_cache["processorProjections"] == {
            "available": True,
            "rows": [],
        }


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


def test_fault_recovery_does_not_block_transition_collection(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(
        runner,
        "decoder-failure-recovery",
        duration_seconds=3,
        timeout_seconds=10,
    )
    fault_started = threading.Event()
    release_fault = threading.Event()
    fault_threads: list[str] = []
    original_inject_services = platform.inject_services
    original_transition_sample = platform.transition_sample

    def delayed_inject_services(services: list[str]) -> list[dict[str, Any]]:
        fault_threads.append(threading.current_thread().name)
        fault_started.set()
        if not release_fault.wait(timeout=2):
            raise RuntimeError("test fault injection was not released")
        return original_inject_services(services)

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 10:
            assert fault_started.wait(timeout=1)
            release_fault.set()
        return sample

    platform.inject_services = delayed_inject_services  # type: ignore[method-assign]
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    runner.contracts.criteria["criteria_sets"][case["criteria_set"]]["thresholds"][
        "collector_sample_loss_maximum"
    ] = 2
    run_id = runner.prepare(case_ids=[case["id"]], run_id="async-fault-run")

    try:
        assert runner.run_case(run_id, case["id"]) == "characterized"
    finally:
        release_fault.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    events = runner_module.BenchmarkRunner._read_jsonl(sample_dir / "case-events.jsonl")
    assert fault_threads == ["open-cinema-fault-injection_0"]
    assert collection["transitionSamples"] == 15
    assert collection["transitionMissed"] == 0
    assert collection["sustainedMissed"] <= 2
    fault_events = [
        event
        for event in events
        if event["event"]
        in {
            "fault-injection-start",
            "fault-injection-complete",
            "workload-restored-after-fault",
        }
    ]
    assert [event["event"] for event in fault_events] == [
        "fault-injection-start",
        "fault-injection-complete",
        "workload-restored-after-fault",
    ]
    assert [event["monotonicNs"] for event in fault_events] == sorted(
        event["monotonicNs"] for event in fault_events
    )


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


def test_scheduled_transition_does_not_block_transition_collection(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    case = bound_case(runner, "soak-pcm", duration_seconds=3, timeout_seconds=10)
    declared = next(item for item in runner.contracts.cases["cases"] if item["id"] == case["id"])
    declared["transition_schedule_seconds"] = [1]
    transition_started = threading.Event()
    release_transition = threading.Event()
    transition_threads: list[str] = []
    original_transition_sample = platform.transition_sample

    class BlockingTransitionWorkload(FakeWorkloadDriver):
        def transition(self, kind: str, index: int) -> dict[str, Any]:
            transition_threads.append(threading.current_thread().name)
            transition_started.set()
            if not release_transition.wait(timeout=2):
                raise RuntimeError("test scheduled transition was not released")
            return super().transition(kind, index)

    def transition_sample() -> dict[str, Any]:
        sample = original_transition_sample()
        if len(platform.transition_capture_ns) == 10:
            assert transition_started.wait(timeout=1)
            release_transition.set()
        return sample

    runner.workload_driver_factory = lambda **arguments: BlockingTransitionWorkload(
        platform=platform,
        **arguments,
    )
    platform.transition_sample = transition_sample  # type: ignore[method-assign]
    runner.contracts.criteria["criteria_sets"][case["criteria_set"]]["thresholds"][
        "collector_sample_loss_maximum"
    ] = 2
    run_id = runner.prepare(case_ids=[case["id"]], run_id="async-scheduled-run")

    try:
        assert runner.run_case(run_id, case["id"]) == "characterized"
    finally:
        release_transition.set()

    sample_dir = runner.run_dir(run_id) / f"cases/{case['id']}/{case['id']}-sample-0001"
    collection = read_json(sample_dir / "collection-result.json")
    assert transition_threads == ["open-cinema-scheduled-transition_0"]
    assert collection["transitionSamples"] == 15
    assert collection["transitionMissed"] == 0


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


def test_fault_recovery_waits_for_the_exact_playback_target_node() -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    now = [1_000_000_000]
    snapshots: list[object] = [
        [],
        [
            {
                "id": 11,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "open-cinema.decoder.decoder-0.capture"
                    }
                },
            }
        ],
    ]
    platform.monotonic_ns = lambda: now[0]
    platform.sleep = lambda seconds: now.__setitem__(
        0, now[0] + int(seconds * 1_000_000_000)
    )
    platform.pipewire_document = lambda **_kwargs: snapshots.pop(0)

    result = runner_module.LinuxPlatform.wait_for_audio_node(
        platform,
        "open-cinema.decoder.decoder-0.capture",
        timeout_seconds=2,
    )

    assert result == {
        "ready": True,
        "nodeName": "open-cinema.decoder.decoder-0.capture",
        "attempts": 2,
        "durationNs": 100_000_000,
    }


def test_file_playback_keeps_private_input_root_side_and_wav_frames_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    platform.audio_user = "opencinema"
    platform.audio_uid = 999
    platform._playback_processes = {}
    platform.monotonic_ns = lambda: 1_000_000_000
    platform.playback_status = lambda handle: {
        "feederAlive": True,
        "playerAlive": True,
        "linked": True,
        "active": True,
    }
    spawned: list[Any] = []

    class Process:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            self.argv = argv
            self.stdin = kwargs.get("stdin")
            self.stdout = io.BytesIO()
            self.pid = 1000 + len(spawned)
            self.returncode = 0
            spawned.append(self)

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.os, "getpgid", lambda pid: pid)
    asset = tmp_path / "private-fixture.s16le"
    asset.write_bytes(b"\x00" * 16)
    asset.chmod(0o600)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    handle, _ = platform.start_file_playback(
        asset_path=asset,
        source_kind="raw-s16le",
        sample_format="s16",
        sample_rate_hz=48_000,
        channels=2,
        channel_map="FL,FR",
        target_node="open-cinema.decoder.decoder-0.capture",
        evidence_dir=evidence_dir,
    )

    feeder_argv = spawned[0].argv
    player_argv = spawned[1].argv
    assert feeder_argv[:3] == ["env", f"OPEN_CINEMA_BENCHMARK_HANDLE={handle}", "ffmpeg"]
    assert feeder_argv[-3:] == ["-f", "wav", "pipe:1"]
    assert "runuser" not in feeder_argv
    assert player_argv[:4] == ["runuser", "-u", "opencinema", "--"]
    assert "pw-cat" in player_argv
    assert player_argv[-1] == "-"
    assert spawned[1].stdin is spawned[0].stdout
    assert asset.stat().st_mode & 0o777 == 0o600
    platform.stop_file_playback(handle)


def test_camilladsp_status_reuses_connection_and_reconnects_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    platform.camilladsp_host = "127.0.0.1"
    platform.camilladsp_port = 1234
    platform._camilladsp_client = None
    platform._camilladsp_lock = threading.Lock()
    clients: list[Any] = []

    class Client:
        def __init__(self, host: str, port: int) -> None:
            assert (host, port) == ("127.0.0.1", 1234)
            self.general = self
            self.status = self
            self.rate = self
            self.failed = False
            self.connects = 0
            self.disconnects = 0
            clients.append(self)

        def connect(self) -> None:
            self.connects += 1

        def disconnect(self) -> None:
            self.disconnects += 1

        def state(self) -> object:
            if self.failed:
                raise ConnectionError("fixture connection closed")
            return type("State", (), {"name": "RUNNING"})()

        def buffer_level(self) -> int:
            return 64

        def clipped_samples(self) -> int:
            return 0

        def processing_load(self) -> float:
            return 1.25

        def resampler_load(self) -> float:
            return 0.5

        def capture_raw(self) -> int:
            return 48_000

    fake_module = type("CamillaModule", (), {"CamillaClient": Client})()
    monkeypatch.setitem(sys.modules, "camilladsp", fake_module)

    first = platform.camilladsp_status()
    second = platform.camilladsp_status()
    assert first == second
    assert first["value"]["state"] == "running"
    assert len(clients) == 1
    assert clients[0].connects == 1

    clients[0].failed = True
    failed = platform.camilladsp_status()
    recovered = platform.camilladsp_status()
    assert failed == {
        "available": False,
        "error": "camilladsp-status-query-failed:ConnectionError",
    }
    assert clients[0].disconnects == 1
    assert recovered["available"] is True
    assert len(clients) == 2

    platform._camilladsp_lock.acquire()
    try:
        assert platform.camilladsp_status(blocking=False) == {
            "available": False,
            "error": "camilladsp-status-query-in-progress",
        }
    finally:
        platform._camilladsp_lock.release()
    assert len(clients) == 2


def test_transition_database_probe_uses_bounded_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "db.sqlite3"
    writer = runner_module.sqlite3.connect(database_path, isolation_level=None)
    writer.execute(
        "CREATE TABLE api_runtimeprojection ("
        "projection_type TEXT, subject_key TEXT, world_generation INTEGER, "
        "world_sequence INTEGER, payload TEXT, observed_at TEXT, is_current INTEGER)"
    )
    platform = object.__new__(runner_module.LinuxPlatform)
    platform.database_path = database_path

    connection = platform._database(timeout_seconds=0.01)
    assert connection is not None
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10
    connection.close()

    writer.execute("BEGIN EXCLUSIVE")
    try:
        assert platform._processor_projection(timeout_seconds=0.001) == {
            "available": False,
            "error": "database-busy",
        }
    finally:
        writer.execute("ROLLBACK")
        writer.close()


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


def test_platform_restore_waits_for_active_intent_convergence_even_when_topology_matches() -> None:
    platform = object.__new__(runner_module.LinuxPlatform)
    clock = {"now": 0}
    convergence = iter((False, False, True))
    sleeps: list[float] = []
    topology = {"digest": "same", "ownedLinkCount": 18, "links": []}
    platform.monotonic_ns = lambda: clock["now"]
    platform.utc_now = lambda: "2026-08-27T00:00:00Z"
    platform.sleep = lambda seconds: (
        sleeps.append(seconds),
        clock.__setitem__("now", clock["now"] + int(seconds * 1_000_000_000)),
    )[-1]
    platform.restore_activations = lambda snapshot: {"snapshot": snapshot}
    platform.restore_services = lambda states: []
    platform.topology = lambda: topology
    platform._enabled_revisions_converged = lambda: next(convergence)
    platform.static_digest = lambda: "static"
    platform.intent_snapshot = lambda: {"semanticDigest": "intent"}
    snapshot = {
        "activeIntent": {"semanticDigest": "intent"},
        "services": {},
        "topology": topology,
        "staticDigest": "static",
        "intentDigest": "intent",
    }

    result = platform.restore(snapshot, timeout_seconds=5)

    assert sleeps == [0.25, 0.25]
    assert result["topologyVerified"] is True
    assert result["activeIntentConverged"] is True


def test_supported_fixture_uses_observed_wlan_controller_link(tmp_path: Path) -> None:
    runner, platform = make_runner(tmp_path)
    facts = platform.fixture_facts(runner.contracts.fixture)
    assert runner._fixture_comparison(facts)["matchesSupportedFixture"] is True
    facts["network"][0]["operstate"] = "down"
    comparison = runner._fixture_comparison(facts)
    assert comparison["matchesSupportedFixture"] is False
    assert "primary-network-mismatch" in comparison["reasons"]
