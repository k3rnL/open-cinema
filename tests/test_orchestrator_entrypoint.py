import os
import subprocess
import sys
import tomllib
from pathlib import Path

from opencinema.orchestrator import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_installs_dedicated_orchestrator_command() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["open-cinema-orchestrator"] == (
        "opencinema.orchestrator:main"
    )


def test_check_mode_loads_django_and_exits_without_service_loop() -> None:
    environment = dict(os.environ)
    environment["DJANGO_SETTINGS_MODULE"] = "opencinema.settings"

    completed = subprocess.run(
        [sys.executable, "-m", "opencinema.orchestrator", "--check"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Starting dedicated Open Cinema orchestrator" not in completed.stderr


def test_service_loop_receives_its_own_process_stop_event() -> None:
    called = []

    class FakeService:
        def run(self, stop_event):
            called.append(stop_event.is_set())
            stop_event.set()

    result = main(
        ["--settings", "opencinema.settings"],
        service_factory=FakeService,
    )

    assert result == 0
    assert called == [False]
