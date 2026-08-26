from __future__ import annotations

from importlib.resources import files

from opencinema.version import MAJOR, MINOR, PATCH, __version__


def test_runtime_version_is_one_semantic_identity() -> None:
    assert __version__ == f"{MAJOR}.{MINOR}.{PATCH}"


def test_runtime_contracts_are_package_resources() -> None:
    contract_root = files("contracts")
    expected = {
        "audio-condition-v1.schema.json",
        "audio-orchestration-v1.yml",
        "audio-signal-descriptor-v1.schema.json",
        "desired-audio-graph-v1.schema.json",
    }
    observed = {path.name for path in contract_root.iterdir() if path.is_file()}
    observed.discard("__init__.py")
    assert observed == expected
