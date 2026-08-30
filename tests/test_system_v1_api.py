from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.test import APIClient

from api.models import RuntimeProjection
from api.system_v1 import components, probes

pytestmark = pytest.mark.django_db


@pytest.fixture
def system_user():
    return get_user_model().objects.create_user(username="system-v1-user")


@pytest.fixture
def client(system_user):
    value = APIClient()
    value.force_authenticate(system_user)
    return value


def test_system_schema_requires_authentication_and_uses_problem_contract() -> None:
    response = APIClient().get("/api/system/v1/schema")

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "not-authenticated"
    assert response.json()["apiVersion"] == 1
    assert response["Open-Cinema-API-Version"] == "1"


def test_system_schema_bootstraps_csrf_and_rejects_unsupported_versions(client) -> None:
    response = client.get("/api/system/v1/schema")

    assert response.status_code == 200
    assert response.json()["service"] == "open-cinema-system"
    assert response.json()["links"]["overview"] == "/api/system/v1/overview"
    assert response["Open-Cinema-Schema-Version"] == "1"
    assert "csrftoken" in response.cookies

    incompatible = client.get(
        "/api/system/v1/overview",
        HTTP_OPEN_CINEMA_API_VERSION="99",
    )
    assert incompatible.status_code == 406
    assert incompatible.json()["code"] == "unsupported-api-version"


def test_overview_reports_full_platform_state(client, monkeypatch) -> None:
    monkeypatch.setattr(probes, "hostname", lambda: "open-cinema")
    monkeypatch.setattr(probes, "hardware_model", lambda: "Raspberry Pi 5 Model B Rev 1.0")
    monkeypatch.setattr(probes, "operating_system", lambda: "Debian GNU/Linux 13")
    monkeypatch.setattr(probes, "kernel", lambda: "6.12.0-rpi")
    monkeypatch.setattr(probes, "boot_id", lambda: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(probes, "uptime_seconds", lambda: 1234.5)
    monkeypatch.setattr(
        probes,
        "storage",
        lambda: {"usedBytes": 25, "totalBytes": 100, "percent": 25.0},
    )
    monkeypatch.setattr(probes, "temperature_celsius", lambda: 46.8)
    monkeypatch.setattr(
        probes,
        "throttling",
        lambda: {"supported": True, "active": False, "raw": "0x0"},
    )

    response = client.get("/api/system/v1/overview")

    assert response.status_code == 200
    assert response.json() == {
        "schemaVersion": 1,
        "observedAt": response.json()["observedAt"],
        "hostname": "open-cinema",
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "operatingSystem": "Debian GNU/Linux 13",
        "kernel": "6.12.0-rpi",
        "bootId": "11111111-2222-3333-4444-555555555555",
        "uptimeSeconds": 1234.5,
        "storage": {"usedBytes": 25, "totalBytes": 100, "percent": 25.0},
        "temperatureCelsius": 46.8,
        "throttling": {"supported": True, "active": False, "raw": "0x0"},
        "application": response.json()["application"],
        "unavailableFields": [],
    }


def test_overview_isolates_optional_probe_failures(client, monkeypatch) -> None:
    monkeypatch.setattr(probes, "hardware_model", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(probes, "temperature_celsius", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(probes, "throttling", lambda: (_ for _ in ()).throw(OSError()))

    response = client.get("/api/system/v1/overview")

    assert response.status_code == 200
    assert response.json()["model"] is None
    assert response.json()["temperatureCelsius"] is None
    assert response.json()["throttling"] == {
        "supported": False,
        "active": None,
        "raw": None,
    }
    assert set(response.json()["unavailableFields"]) >= {
        "model",
        "temperatureCelsius",
        "throttling",
    }


def test_metrics_report_timestamped_cpu_and_memory_and_isolate_failure(client, monkeypatch) -> None:
    monkeypatch.setattr(probes, "cpu_percent", lambda: 7.5)
    monkeypatch.setattr(
        probes,
        "memory",
        lambda: {"usedBytes": 20, "totalBytes": 80, "percent": 25.0},
    )
    response = client.get("/api/system/v1/metrics")
    assert response.status_code == 200
    assert response.json()["cpuPercent"] == 7.5
    assert response.json()["memory"]["percent"] == 25.0
    assert response.json()["unavailableFields"] == []

    monkeypatch.setattr(probes, "cpu_percent", lambda: (_ for _ in ()).throw(OSError()))
    degraded = client.get("/api/system/v1/metrics")
    assert degraded.status_code == 200
    assert degraded.json()["cpuPercent"] is None
    assert degraded.json()["memory"] is not None
    assert degraded.json()["unavailableFields"] == ["cpuPercent"]


def test_components_use_fixed_registry_manifest_and_runtime_health(client, monkeypatch) -> None:
    RuntimeProjection.objects.create(
        projection_type="orchestration-health",
        subject_key="orchestrator",
        world_generation=1,
        world_sequence=1,
        observed_at=timezone.now(),
        payload={"ready": True},
    )
    RuntimeProjection.objects.create(
        projection_type="processor-health",
        subject_key="camilladsp:room",
        world_generation=1,
        world_sequence=2,
        observed_at=timezone.now(),
        payload={"nodeType": "processor.camilladsp-profile-selector", "ready": True},
    )
    RuntimeProjection.objects.create(
        projection_type="processor-health",
        subject_key="decoder:tv",
        world_generation=1,
        world_sequence=3,
        observed_at=timezone.now(),
        payload={"nodeType": "processor.pcm-auto-decoder", "ready": False},
    )
    monkeypatch.setattr(
        components,
        "_load_manifest",
        lambda: {
            "components": {
                "open_cinema": {"version": "0.3.2"},
                "management_ui": {"version": "2.0.0"},
                "wyreplumber": {"version": "0.2.0"},
                "camilladsp": {"version": "4.1.3"},
                "pcm_auto_decoder": {"version": "0.2.2"},
            }
        },
    )
    monkeypatch.setattr(
        components,
        "_command_version",
        lambda component_id: {"pipewire": "1.4.8", "wireplumber": "0.5.8"}.get(component_id),
    )

    response = client.get("/api/system/v1/components")

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["items"]}
    assert set(by_id) == {
        "open-cinema",
        "open-cinema-orchestrator",
        "management-ui",
        "wyreplumber",
        "pipewire",
        "wireplumber",
        "camilladsp",
        "pcm-auto-decoder",
    }
    assert by_id["camilladsp"]["version"] == "4.1.3"
    assert by_id["camilladsp"]["health"] == "ready"
    assert by_id["pcm-auto-decoder"]["health"] == "degraded"
    assert by_id["pipewire"]["version"] == "1.4.8"
    assert by_id["open-cinema"]["actions"][0]["id"] == "restart"
    assert by_id["open-cinema"]["actions"][0]["available"] is False
    assert by_id["open-cinema-orchestrator"]["actions"][0]["id"] == "restart"
    assert all(
        item["actions"] == []
        for component_id, item in by_id.items()
        if component_id not in {"open-cinema", "open-cinema-orchestrator"}
    )
    assert "/home/" not in response.content.decode()


def test_system_json_schemas_and_openapi_are_valid(client) -> None:
    schemas = client.get("/api/system/v1/schemas")
    assert schemas.status_code == 200
    for schema in schemas.json()["schemas"].values():
        Draft202012Validator.check_schema(schema)

    openapi = client.get("/api/system/v1/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["openapi"] == "3.1.0"
    assert openapi.json()["servers"] == [{"url": "/api/system/v1"}]
    assert {"/overview", "/metrics", "/components"} <= set(openapi.json()["paths"])


def test_linux_probe_parsers_are_bounded_and_typed(tmp_path: Path, monkeypatch) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Debian"\nPRETTY_NAME="Debian GNU/Linux 13"\n', encoding="utf-8")
    model = tmp_path / "model"
    model.write_text("Raspberry Pi 5 Model B Rev 1.0\x00\n", encoding="utf-8")
    uptime = tmp_path / "uptime"
    uptime.write_text("123.45 100.00\n", encoding="utf-8")
    memory = tmp_path / "meminfo"
    memory.write_text("MemTotal: 8000 kB\nMemAvailable: 6000 kB\n", encoding="utf-8")
    cpu = tmp_path / "stat"
    cpu.write_text("cpu  10 0 10 80 0 0 0 0 0 0\n", encoding="utf-8")
    temperature = tmp_path / "temp"
    temperature.write_text("46800\n", encoding="utf-8")

    assert probes.operating_system(os_release) == "Debian GNU/Linux 13"
    assert probes.hardware_model(model) == "Raspberry Pi 5 Model B Rev 1.0"
    assert probes.uptime_seconds(uptime) == 123.45
    assert probes.memory(memory) == {
        "usedBytes": 2_048_000,
        "totalBytes": 8_192_000,
        "percent": 25.0,
    }
    assert probes._cpu_totals(cpu) == (100, 80)
    assert probes.temperature_celsius(temperature) == 46.8

    monkeypatch.setattr(probes.shutil, "which", lambda name: "/usr/bin/vcgencmd")
    monkeypatch.setattr(
        probes.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "throttled=0x0\n", ""),
    )
    assert probes.throttling() == {"supported": True, "active": False, "raw": "0x0"}
