from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from core.plugin_system.control_cli import main as control_main
from core.plugin_system.overlay import (
    PluginControlHelper,
    PluginGenerationBuilder,
    PluginGenerationManifest,
    PluginOverlayError,
    PluginOverlayManager,
    export_core_constraints,
    reject_core_dependency_conflicts,
    validate_generation_id,
)
from opencinema_plugin_bootstrap import activate_plugin_overlay


def test_standalone_control_cli_import_does_not_require_django_setup() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import core.plugin_system.control_cli"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _manifest(generation_id: str, previous: str | None = None) -> PluginGenerationManifest:
    return PluginGenerationManifest(
        generation_id,
        "2026-08-30T00:00:00Z",
        {"python": "3.12"},
        ({"filename": "plugin.whl", "digest": "sha256:" + "a" * 64},),
        ({"name": "test-plugin", "version": "1.0.0"},),
        (),
        previous,
    )


def _stage(manager: PluginOverlayManager, generation_id: str, previous=None) -> Path:
    path = manager.create_staging(generation_id)
    manager.write_manifest(generation_id, _manifest(generation_id, previous))
    return path


def _plugin_toml() -> str:
    return """
schema-version = 2
permissions = []
[plugin]
id = "test.plugin"
distribution = "open-cinema-test-plugin"
display-name = "Test"
description = "Overlay fixture."
vendor = "Tests"
version = "1.0.0"
license = "MIT"
source-url = "https://example.test/source"
documentation-url = "https://example.test/docs"
[compatibility]
open-cinema = ">=0.3,<1"
python = ">=3.12,<4"
operating-systems = ["linux"]
architectures = ["x86_64", "aarch64", "arm64"]
[compatibility.plugin-contract]
minimum = 2
maximum = 2
[[capabilities]]
id = "test.plugin.api"
kind = "api"
version = 1
[lifecycle]
install = "application-restart"
enable = "hot"
disable = "hot"
update = "application-restart"
uninstall = "application-restart"
"""


def _wheel(tmp_path: Path, *, requirement: str | None = None) -> Path:
    path = tmp_path / "open_cinema_test_plugin-1.0.0-py3-none-any.whl"
    metadata = "Metadata-Version: 2.3\nName: open-cinema-test-plugin\nVersion: 1.0.0\n"
    if requirement is not None:
        metadata += f"Requires-Dist: {requirement}\n"
    plugin_module = """
from django.apps import apps
from core.plugin_system import ApiCapability, OpenCinemaPlugin, RuntimePluginIdentity

if not apps.ready:
    raise RuntimeError("Django apps must be ready before plugin import")

class TestPlugin(OpenCinemaPlugin):
    @property
    def identity(self):
        return RuntimePluginIdentity("test.plugin", "open-cinema-test-plugin", "1.0.0")

    def capabilities(self):
        return (ApiCapability("test.plugin.api"),)
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("test_plugin/__init__.py", plugin_module)
        archive.writestr("test_plugin/open-cinema-plugin.toml", _plugin_toml())
        archive.writestr("open_cinema_test_plugin-1.0.0.dist-info/METADATA", metadata)
        archive.writestr(
            "open_cinema_test_plugin-1.0.0.dist-info/entry_points.txt",
            "[open_cinema.plugins]\ntest.plugin = test_plugin:TestPlugin\n",
        )
        archive.writestr(
            "open_cinema_test_plugin-1.0.0.dist-info/RECORD",
            "\n".join(
                (
                    "test_plugin/__init__.py,,",
                    "test_plugin/open-cinema-plugin.toml,,",
                    "open_cinema_test_plugin-1.0.0.dist-info/METADATA,,",
                    "open_cinema_test_plugin-1.0.0.dist-info/entry_points.txt,,",
                    "open_cinema_test_plugin-1.0.0.dist-info/RECORD,,",
                )
            ),
        )
    return path


def test_generation_activation_rollback_and_cleanup_preserve_recovery_boundaries(
    tmp_path,
) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins", retention=1)
    _stage(manager, "gen-first")
    assert manager.activate("gen-first") is None
    _stage(manager, "gen-second", "gen-first")
    assert manager.activate("gen-second") == "gen-first"
    _stage(manager, "gen-third", "gen-second")
    manager.activate("gen-third")

    assert manager.pointer("current") == "gen-third"
    assert manager.pointer("last-known-good") == "gen-second"
    assert manager.rollback() == ("gen-third", "gen-second")
    assert manager.pointer("current") == "gen-second"
    assert manager.pointer("last-known-good") == "gen-third"
    removed = manager.cleanup()
    assert "gen-first" in removed
    assert manager.generation_path("gen-second").exists()
    assert manager.generation_path("gen-third").exists()


@pytest.mark.parametrize(
    "generation_id",
    ("../escape", "/absolute", "gen-../../escape", "GEN-UPPER", "gen space"),
)
def test_generation_ids_reject_paths_and_unbounded_syntax(generation_id) -> None:
    with pytest.raises(PluginOverlayError):
        validate_generation_id(generation_id)


def test_control_helper_accepts_only_fixed_actions_and_server_owned_identifiers(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    _stage(manager, "gen-candidate")
    helper = PluginControlHelper(manager)

    assert helper.execute("validate", "gen-candidate")["generationId"] == "gen-candidate"
    with pytest.raises(PluginOverlayError):
        helper.execute("activate", "../../etc")
    with pytest.raises(PluginOverlayError):
        helper.execute("systemctl restart open-cinema", None)


def test_early_bootstrap_appends_valid_overlay_after_core_paths(tmp_path, monkeypatch) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    _stage(manager, "gen-active")
    manager.activate("gen-active")
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ROOT", str(manager.root))
    before = tuple(sys.path)

    result = activate_plugin_overlay()

    try:
        assert not result.recovery_mode
        assert result.generation_id == "gen-active"
        assert sys.path[-1] == result.overlay_path
        assert tuple(sys.path[: len(before)]) == before
    finally:
        if result.overlay_path in sys.path:
            sys.path.remove(result.overlay_path)


def test_invalid_pointer_enters_diagnosable_recovery_mode(tmp_path, monkeypatch) -> None:
    root = tmp_path / "plugins"
    pointers = root / "pointers"
    pointers.mkdir(parents=True)
    (pointers / "current.json").write_text(json.dumps({"generationId": "../../bad"}))
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ROOT", str(root))

    result = activate_plugin_overlay()

    assert result.recovery_mode
    assert result.overlay_path is None
    assert os.environ["OPEN_CINEMA_PLUGIN_RECOVERY_DIAGNOSTIC"]


def test_local_editable_override_is_explicit_and_bounded(tmp_path, monkeypatch) -> None:
    editable = tmp_path / "open-cinema-test-plugin"
    editable.mkdir()
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ROOT", str(tmp_path / "plugins"))
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_ALLOW_EDITABLE", "1")
    monkeypatch.setenv("OPEN_CINEMA_PLUGIN_EDITABLE_DIRS", str(editable))

    result = activate_plugin_overlay()

    try:
        assert result.editable_paths == (str(editable.resolve()),)
        assert sys.path[-1] == str(editable.resolve())
    finally:
        sys.path.remove(str(editable.resolve()))


def test_core_dependency_conflict_is_rejected_before_install(tmp_path) -> None:
    wheel = _wheel(tmp_path, requirement="Django>=999")

    with pytest.raises(PluginOverlayError, match="conflicts with core"):
        reject_core_dependency_conflicts((wheel,), {"django": "6.0.3"})


def test_core_constraints_exclude_the_plugin_distribution_being_replaced(
    tmp_path, monkeypatch
) -> None:
    class Distribution:
        metadata = {"Name": "open-cinema-test-plugin"}
        version = "0.1.0"

        @staticmethod
        def locate_file(path):
            return tmp_path / path

    monkeypatch.setattr(
        "core.plugin_system.overlay.metadata.distributions",
        lambda: (Distribution(),),
    )

    resolved = export_core_constraints(
        tmp_path / "constraints.txt",
        excluded_distributions=frozenset({"open-cinema-test-plugin"}),
    )

    assert resolved == {}
    assert (tmp_path / "constraints.txt").read_text(encoding="utf-8") == "\n"


class FakeInstaller:
    def __init__(self):
        self.commands = []

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        target = Path(argv[argv.index("--target") + 1])
        with zipfile.ZipFile(argv[-1]) as archive:
            archive.extractall(target)
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")


def test_generation_builder_targets_fresh_overlay_and_records_artifacts(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    wheel = _wheel(tmp_path)
    installer = FakeInstaller()
    builder = PluginGenerationBuilder(manager, runner=installer)

    manifest = builder.build(
        generation_id="gen-build",
        wheels=(wheel,),
        created_at="2026-08-30T00:00:00Z",
        previous_generation=None,
    )

    assert manifest.artifacts[0]["digest"].startswith("sha256:")
    assert manifest.resolved_distributions == (
        {"name": "open-cinema-test-plugin", "version": "1.0.0"},
    )
    assert manager.validate("gen-build", staged=True)["plugins"][0]["id"] == "test.plugin"
    assert not (Path(sys.prefix) / "open_cinema_test_plugin-1.0.0.dist-info").exists()
    assert "--no-cache" in installer.commands[0]


def test_build_failure_removes_partial_generation(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    wheel = _wheel(tmp_path)

    def fail(argv, **kwargs):
        raise RuntimeError("installer failed")

    with pytest.raises(RuntimeError, match="installer failed"):
        PluginGenerationBuilder(manager, runner=fail).build(
            generation_id="gen-failed",
            wheels=(wheel,),
            created_at="2026-08-30T00:00:00Z",
            previous_generation=None,
        )

    assert not manager.generation_path("gen-failed", staged=True).exists()


def test_installer_failure_reports_bounded_stderr_and_cleans_staging(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    wheel = _wheel(tmp_path)

    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(
            2,
            argv,
            stderr="Failed to initialize cache: permission denied",
        )

    with pytest.raises(
        PluginOverlayError,
        match="Failed to initialize cache: permission denied",
    ):
        PluginGenerationBuilder(manager, runner=fail).build(
            generation_id="gen-installer-failed",
            wheels=(wheel,),
            created_at="2026-08-30T00:00:00Z",
            previous_generation=None,
        )

    assert not manager.generation_path("gen-installer-failed", staged=True).exists()


def test_generation_builder_enforces_storage_limit_and_cleans_staging(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    wheel = _wheel(tmp_path)

    class OversizedInstaller(FakeInstaller):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            target = Path(argv[argv.index("--target") + 1])
            (target / "oversized.bin").write_bytes(b"x" * (1024 * 1024))
            return result

    with pytest.raises(PluginOverlayError, match="storage limit"):
        PluginGenerationBuilder(
            manager,
            runner=OversizedInstaller(),
            max_generation_bytes=1024 * 1024,
        ).build(
            generation_id="gen-oversized",
            wheels=(wheel,),
            created_at="2026-08-30T00:00:00Z",
            previous_generation=None,
        )

    assert not manager.generation_path("gen-oversized", staged=True).exists()


def test_control_cli_accepts_only_server_owned_generation_identifiers(tmp_path, capsys) -> None:
    arguments = [
        "--root",
        str(tmp_path / "plugins"),
        "--retention",
        "3",
        "--check",
        "activate",
    ]

    assert control_main([*arguments, "gen-safe"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert control_main([*arguments, "../../tmp/escape"]) == 64
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_partial_generation_cannot_switch_active_pointer(tmp_path) -> None:
    manager = PluginOverlayManager(tmp_path / "plugins")
    manager.create_staging("gen-partial")
    manager.write_manifest(
        "gen-partial",
        PluginGenerationManifest(
            "gen-partial",
            "2026-08-30T00:00:00Z",
            {"python": "3.12"},
            (),
            (),
            ({"id": "test.plugin", "version": "1.0.0"},),
        ),
    )

    with pytest.raises(PluginOverlayError, match="contract validation failed"):
        manager.activate("gen-partial")

    assert manager.pointer("current") is None
    assert manager.generation_path("gen-partial", staged=True).exists()
