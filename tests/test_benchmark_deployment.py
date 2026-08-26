from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator, FormatChecker
import yaml

ROOT = Path(__file__).parents[1]
DEPLOYMENT = ROOT / "deployment"
BENCHMARKS = DEPLOYMENT / "benchmarks"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: Path):
    return yaml.safe_load(read(path))


def validate(instance, schema_path: Path) -> None:
    schema = json.loads(read(schema_path))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def effective_case(manifest: dict, case: dict) -> dict:
    return {**manifest["defaults"], **case}


def test_benchmark_tools_are_explicit_and_separate_from_the_appliance_play() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    benchmark = read(DEPLOYMENT / "playbooks/benchmark.yml")
    tasks = read(DEPLOYMENT / "roles/benchmark-tools/tasks/main.yml")

    assert "role: benchmark-tools" not in site
    assert "role: benchmark-tools" in benchmark
    for package in ("ffmpeg", "linux-perf", "python3", "sqlite3", "sysstat", "time"):
        assert f"- {package}" in tasks
    for command in (
        "ffprobe",
        "pidstat",
        "pw-dump",
        "pw-top",
        "redis-cli",
        "vcgencmd",
        "wpctl",
    ):
        assert f"- {command}" in tasks

    # Preparation records the current/historical bits; it does not require a
    # fresh image or erase history to make installation pass.
    assert "get_throttled" in tasks
    assert "open_cinema_benchmark_throttled" in tasks
    assert "failed_when: false" in tasks
    assert "Require a clean power" not in tasks
    assert "pulse" + "audio" not in tasks.lower()
    assert "pipewire" + "-pulse" not in tasks.lower()

    measurement = read(DEPLOYMENT / "roles/benchmark-tools/files/measure-live-graph")
    for evidence in (
        "pidstat.txt",
        "pw-top.txt",
        "system-samples.csv",
        "decoder-after.ndjson",
        "database-after.txt",
        "redis-after.txt",
        "journal.txt",
        "diskstats-after.txt",
        "final_owned_links",
        "pipewire-error-counters.json",
        "maximum_pipewire_error_increment",
        "orchestrator_average_cpu_percent",
        "decoder_average_cpu_percent",
        "camilladsp_average_cpu_percent",
        "initial_decoder_sequence",
        "final_decoder_sequence",
        "initial_decoder_error_count",
        "final_decoder_error_count",
        "benchmark_evidence_directory",
    ):
        assert evidence in measurement
    assert "workload and carrier declarations are missing or inconsistent" in measurement
    assert "programme-audio" in measurement
    assert "no-carrier" in measurement
    assert "record_status passed" not in measurement
    assert "benchmark_status=passed" not in measurement
    assert "benchmark_status=characterized" in measurement


def test_single_supported_fixture_contract_is_schema_valid_and_natively_scoped() -> None:
    fixture = load_yaml(BENCHMARKS / "fixtures.yml")
    validate(fixture, BENCHMARKS / "fixture.schema.json")

    assert fixture["fixture_contract_id"] == "pi5-8gb-gab8-native-v1"
    assert fixture["device_under_test"]["memory_mb"] == 8192
    assert fixture["device_under_test"]["power"]["rated_watts"] == 27
    assert fixture["device_under_test"]["cooling"]["type"] == "active-fan"
    chain = fixture["audio_chain"]
    assert chain["transport"] == "native-pipewire"
    assert chain["sample_rate_hz"] == 48_000
    assert chain["input"]["kind"] == "spdif-to-i2s"
    assert chain["output"]["model"] == "WONDOM GAB8"
    assert chain["decoder"]["instances"] == 1
    assert chain["camilladsp"]["instances"] == 1
    assert chain["camilladsp"]["processing_period_frames"] == 128
    assert "candidate_tiers" not in fixture


def test_case_manifest_schema_cross_references_and_campaign_bounds() -> None:
    fixture = load_yaml(BENCHMARKS / "fixtures.yml")
    manifest = load_yaml(BENCHMARKS / "cases.yml")
    criteria_policy = load_yaml(BENCHMARKS / "criteria-policy.yml")
    validate(manifest, BENCHMARKS / "cases.schema.json")

    assert manifest["fixture_contract_id"] == fixture["fixture_contract_id"]
    assert manifest["suite_id"] == fixture["suite_id"]
    assert manifest["criteria_policy_id"] == criteria_policy["criteria_policy_id"]
    input_fixtures = set(fixture["input_fixtures"])
    processor_fixtures = set(fixture["processor_fixtures"])
    metric_sets = set(manifest["metric_sets"])
    restoration_actions = manifest["restoration_actions"]
    criteria_sets = criteria_policy["criteria_sets"]
    ids: set[str] = set()
    campaigns: set[str] = set()

    for declared in manifest["cases"]:
        case = effective_case(manifest, declared)
        assert case["id"] not in ids
        ids.add(case["id"])
        campaigns.add(case["campaign"])
        assert case["fixture_id"] == fixture["fixture_contract_id"]
        assert case["input_fixture"] in input_fixtures
        assert case["processor_fixture"] in processor_fixtures
        assert set(case["required_metric_sets"]) <= metric_sets
        assert case["restoration_action"] in restoration_actions
        assert case["criteria_set"] in criteria_sets
        assert criteria_sets[case["criteria_set"]]["campaign_mode"] == "characterization"
        assert case["warm_up_repetitions"] >= 0
        assert case["measured_repetitions"] >= 1
        assert case["duration_seconds"] >= 1
        assert case["timeout_seconds"] >= case["duration_seconds"]
        assert case["expected_outcome"] in {
            "supported",
            "unsupported-by-build",
            "fixture-unavailable",
        }
        assert (case["workload_state"], case["carrier_state"]) in {
            ("idle", "not-applicable"),
            ("no-carrier", "absent"),
            ("programme-audio", "present"),
        }
        for profile in case.get("processor_fixture_matrix", []):
            assert profile in processor_fixtures
        allowed = set(restoration_actions[case["restoration_action"]].get("allowed_services", []))
        assert set(case.get("disruptive_services", [])) <= allowed
        for service_set in case.get("service_matrix", []):
            assert set(service_set) <= allowed

        input_available = (
            fixture["input_fixtures"][case["input_fixture"]].get("registry_status")
            != "pending-registration"
        )
        processor_available = (
            fixture["processor_fixtures"][case["processor_fixture"]].get("profile_status")
            != "pending-registration"
        )
        matrix_available = all(
            fixture["processor_fixtures"][profile].get("profile_status") != "pending-registration"
            for profile in case.get("processor_fixture_matrix", [])
        )
        if not (input_available and processor_available and matrix_available):
            assert case["expected_outcome"] == "fixture-unavailable"
        else:
            assert case["expected_outcome"] != "fixture-unavailable"

    assert ids == {
        "baseline-fixture-and-topology",
        "baseline-collector-overhead",
        "decoder-pcm-stereo",
        "decoder-ac3-51",
        "decoder-eac3-51",
        "decoder-dts-51",
        "decoder-no-carrier-safe-silence",
        "decoder-unsupported-input",
        "decoder-failure-recovery",
        "decoder-format-transitions",
        "camilladsp-profiles-128",
        "camilladsp-profile-replacement",
        "camilladsp-bypass",
        "camilladsp-invalid-configuration",
        "camilladsp-control-interruption",
        "camilladsp-restart-and-rollback",
        "routing-headset-takeover",
        "routing-headset-to-main-fallback",
        "routing-headset-reconnection",
        "recovery-service-matrix",
        "boot-persistence-saved-intent",
        "event-storage-bounded-burst",
        "soak-pcm",
        "soak-encoded-multichannel",
        "soak-representative-dsp",
        "soak-adaptive-routing",
    }

    assert campaigns == {
        "baseline",
        "decoder",
        "camilladsp",
        "adaptive-routing",
        "recovery",
        "boot-persistence",
        "event-storage",
        "soak",
    }
    assert (
        effective_case(
            manifest,
            next(case for case in manifest["cases"] if case["id"] == "baseline-collector-overhead"),
        )["duration_seconds"]
        == 60
    )
    no_carrier = effective_case(
        manifest,
        next(case for case in manifest["cases"] if case["id"] == "decoder-no-carrier-safe-silence"),
    )
    assert no_carrier["workload_state"] == "no-carrier"
    assert no_carrier["carrier_state"] == "absent"
    for case in manifest["cases"]:
        effective = effective_case(manifest, case)
        if effective["campaign"] == "adaptive-routing":
            assert effective["warm_up_repetitions"] >= 1
            assert effective["measured_repetitions"] >= 20
        if effective["campaign"] == "recovery":
            assert effective["warm_up_repetitions"] >= 1
            assert effective["measured_repetitions"] >= 5
        if effective["campaign"] == "soak":
            assert effective["duration_seconds"] >= 600
            assert effective["transition_schedule_kind"]
            schedule = effective["transition_schedule_seconds"]
            assert schedule == sorted(schedule)
            assert all(0 < timestamp < effective["duration_seconds"] for timestamp in schedule)
            assert "transition-timing" in effective["required_metric_sets"]


def test_criteria_modes_cannot_turn_characterization_into_acceptance() -> None:
    policy = load_yaml(BENCHMARKS / "criteria-policy.yml")
    characterization = policy["criteria_sets"]["characterization-v1"]
    acceptance = policy["criteria_sets"]["acceptance-v1"]
    freeze = policy["freeze_contract"]

    assert characterization["campaign_mode"] == "characterization"
    assert characterization["platform_acceptance_allowed"] is False
    assert characterization["thresholds_are_hypotheses"] is True
    assert acceptance["campaign_mode"] == "acceptance"
    assert acceptance["state"] != freeze["required_acceptance_state"]
    assert acceptance["platform_acceptance_allowed"] is False
    assert freeze["digest_algorithm"] == "sha256"
    assert freeze["immutable_copy_required_in_run_bundle"] is True
    assert freeze["mutation_after_run_prepare"] == "forbidden"
    assert freeze["acceptance_requires_distinct_run_from_characterization"] is True


def test_evidence_envelope_template_validates_and_keeps_target_clock_separate() -> None:
    envelope = load_yaml(BENCHMARKS / "evidence-envelope.template.yml")
    validate(envelope, BENCHMARKS / "evidence-envelope.schema.json")
    calibration = envelope["timestamps"]["clockCalibration"]
    assert calibration["clock"] == "CLOCK_BOOTTIME"
    assert calibration["controllerSubtractionAllowed"] is False
    assert envelope["checksums"]["algorithm"] == "sha256"
    assert "invalidation" in envelope
    assert "restoration" in envelope


def test_imported_evidence_is_functional_only_and_points_to_retained_records() -> None:
    index = load_yaml(BENCHMARKS / "imported-evidence.yml")
    assert index["classification"] == "imported-functional"
    assert index["quantitative_use"] == "forbidden"
    assert {
        "tv-spdif-to-main",
        "bluetooth-programme-source-to-main",
        "headset-takeover-and-fallback",
        "active-graph-headless-reboot",
        "processor-and-runtime-restarts",
    } <= {record["id"] for record in index["records"]}
    for record in index["records"]:
        assert (ROOT / record["path"]).is_file()
        assert record["quantitative_metrics"] == []
        assert record["missing_measurements"]


def test_pw_top_summary_preserves_per_object_first_last_delta_and_resets(tmp_path: Path) -> None:
    source = tmp_path / "pw-top.txt"
    source.write_text(
        "\n".join(
            (
                "R 10 128 48000 0 0 0 0 5 F32P decoder-output",
                "R 11 128 48000 0 0 0 0 0 F32P camilla-capture",
                "R 10 128 48000 0 0 0 0 7 F32P decoder-output",
                "R 11 128 48000 0 0 0 0 4 F32P camilla-capture",
                "R 11 128 48000 0 0 0 0 1 F32P camilla-capture",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    command = DEPLOYMENT / "roles/benchmark-tools/files/summarize-pw-top"
    result = subprocess.run(
        ["python3", command, source],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    nodes = {node["name"]: node for node in payload["nodes"]}
    assert nodes["decoder-output"] == {
        "node_id": 10,
        "name": "decoder-output",
        "first_errors": 5,
        "last_errors": 7,
        "delta_errors": 2,
        "observed_increment_errors": 2,
        "counter_resets": 0,
        "samples": 2,
        "first_line": 1,
        "last_line": 3,
    }
    assert nodes["camilla-capture"]["first_errors"] == 0
    assert nodes["camilla-capture"]["last_errors"] == 1
    assert nodes["camilla-capture"]["delta_errors"] == 1
    assert nodes["camilla-capture"]["observed_increment_errors"] == 5
    assert nodes["camilla-capture"]["counter_resets"] == 1
    assert payload["nodes_with_observed_increments"] == 2


def test_remote_redaction_wrapper_propagates_ssh_failure(tmp_path: Path) -> None:
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'device=AA:BB:CC:DD:EE:FF token=do-not-leak'\n"
        "printf '%s\\n' 'benchmark_evidence_directory=/retained/failed/run'\n"
        "exit 23\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    wrapper = BENCHMARKS / "run-live-graph-remote"
    result = subprocess.run(
        [
            "bash",
            wrapper,
            "fixture-host",
            "--case-id",
            "decoder-no-carrier-safe-silence",
            "--workload-state",
            "no-carrier",
            "--carrier-state",
            "absent",
            "60",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 23
    assert "AA:BB:CC:DD:EE:FF" not in result.stdout
    assert "do-not-leak" not in result.stdout
    assert result.stdout.count("[redacted]") == 2
    assert "benchmark_evidence_directory=/retained/failed/run" in result.stdout


def test_audio_fixtures_are_reproducible_versioned_and_opt_in() -> None:
    benchmark = read(DEPLOYMENT / "playbooks/benchmark.yml")
    tasks = read(DEPLOYMENT / "roles/benchmark-fixtures/tasks/main.yml")
    defaults = load_yaml(DEPLOYMENT / "roles/benchmark-fixtures/defaults/main.yml")

    assert "open_cinema_generate_benchmark_fixtures" in benchmark
    assert defaults["open_cinema_benchmark_fixture_version"] == "pi5-8gb-gab8-native-v1"
    assert "sine=frequency=997:sample_rate=48000" in tasks
    assert "pcm-stereo.s16le" in tasks
    assert "ac3-5.1.spdif" in tasks
    assert "eac3-5.1.spdif" in tasks
    assert "dts-5.1.spdif" in tasks
    assert "checksum_algorithm: sha256" in tasks
    assert "ffprobe" in tasks
    assert "manifest.yml" in tasks
    assert "camilladsp_period_frames: 128" in tasks
    assert "audio_transport: native-pipewire" in tasks


def test_benchmark_playbook_and_role_yaml_are_well_formed() -> None:
    yaml.safe_load(read(DEPLOYMENT / "playbooks/benchmark.yml"))
    yaml.safe_load(read(DEPLOYMENT / "roles/benchmark-tools/tasks/main.yml"))
    yaml.safe_load(read(DEPLOYMENT / "roles/benchmark-fixtures/defaults/main.yml"))
    yaml.safe_load(read(DEPLOYMENT / "roles/benchmark-fixtures/tasks/main.yml"))
