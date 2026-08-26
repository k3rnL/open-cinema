import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1]
FILTER_PATH = ROOT / "deployment" / "filter_plugins" / "open_cinema_compatibility.py"
ROLE_PATH = ROOT / "deployment" / "roles" / "preflight" / "tasks" / "main.yml"


def load_filter_module():
    spec = importlib.util.spec_from_file_location("open_cinema_compatibility", FILTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wireplumber_command_output_is_normalized() -> None:
    compatibility = load_filter_module()

    assert (
        compatibility.open_cinema_extract_version(
            "wireplumber\nCompiled with libwireplumber 0.5.8\n"
        )
        == "0.5.8"
    )
    assert compatibility.open_cinema_extract_version("wireplumber 0.5") == "0.5.0"
    assert compatibility.open_cinema_extract_version("not installed") == ""


@pytest.mark.parametrize("version", ["0.5.8", "0.5.15", "0.5.99"])
def test_selected_wireplumber_family_passes(version: str) -> None:
    compatibility = load_filter_module()
    bounds = {"minimum": "0.5.8", "maximum_exclusive": "0.6.0"}

    assert compatibility.open_cinema_version_in_range(version, bounds)


@pytest.mark.parametrize("version", ["0.4.17", "0.5.7", "0.6.0", "1.0.0"])
def test_versions_outside_selected_wireplumber_family_fail(version: str) -> None:
    compatibility = load_filter_module()
    bounds = {"minimum": "0.5.8", "maximum_exclusive": "0.6.0"}

    assert not compatibility.open_cinema_version_in_range(version, bounds)


def test_preflight_contains_actionable_wireplumber_failure() -> None:
    role_tasks = yaml.safe_load(ROLE_PATH.read_text(encoding="utf-8"))
    family_check = next(
        task for task in role_tasks if task["name"] == "Collect audio runtime incompatibilities"
    )
    final_check = next(
        task
        for task in role_tasks
        if task["name"] == "Reject every incompatible component before deployment mutation"
    )
    collection = family_check["ansible.builtin.set_fact"][
        "open_cinema_preflight_audio_failures"
    ]
    message = final_check["ansible.builtin.assert"]["fail_msg"]

    assert "wireplumber" in collection
    assert "installed version" in collection
    assert "outside [" in collection
    assert "pkg-config cannot find" in collection
    assert "Correct every item" in message
    assert "open_cinema_preflight_result_path" in message
