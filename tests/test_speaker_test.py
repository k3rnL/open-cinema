from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from core.orchestration import speaker_test as speaker_test_module
from core.orchestration.speaker_test import (
    SpeakerTestController,
    SpeakerTestOutput,
    build_speaker_test_command,
    output_from_projection,
)
from core.orchestration.speaker_test_worker import build_pw_cat_command, tone_chunks


def _projection(payload, *, current=True):
    return SimpleNamespace(payload=payload, is_current=current, world_generation=7)


def _payload(*, managed=False, known=True):
    channels = ["FL", "FR", "FC", "LFE"]
    return {
        "runtimeKey": "runtime:7:node:42",
        "direction": "output",
        "name": "alsa_output.test-surround",
        "description": "Test surround output",
        "mediaClass": "Audio/Sink",
        "origin": "managed-adapter" if managed else "runtime-device",
        "managed": managed,
        "error": None,
        "device": {"description": "Test device"},
        "ports": [
            {
                "direction": "input",
                "channel": channel,
                "properties": {"port.physical": "true", "port.id": str(index)},
            }
            for index, channel in enumerate(channels)
        ],
        "audioCapabilities": {
            "formats": [
                {
                    "content": "pcm",
                    "positions": {"known": known, "value": channels},
                    "channels": {"known": True, "value": len(channels)},
                    "rate": {"known": True, "value": 48000},
                }
            ]
        },
    }


def _output():
    return SpeakerTestOutput(
        runtime_key="runtime:7:node:42",
        generation=7,
        name="Test surround output",
        description="Test device",
        target_name="alsa_output.test-surround",
        channels=("FL", "FR", "FC", "LFE"),
        rate=48000,
    )


def test_output_requires_physical_pcm_sink_with_known_order():
    output = output_from_projection(_projection(_payload()))
    assert output is not None
    assert output.channels == ("FL", "FR", "FC", "LFE")
    assert output.target_name == "alsa_output.test-surround"

    assert output_from_projection(_projection(_payload(managed=True))) is None
    assert output_from_projection(_projection(_payload(known=False))) is None
    assert output_from_projection(_projection(_payload(), current=False)) is None

    missing_port = _payload()
    missing_port["ports"] = missing_port["ports"][:-1]
    assert output_from_projection(_projection(missing_port)) is None


def test_tone_samples_are_nonzero_only_on_selected_channel():
    channels = ("FL", "FR", "FC", "LFE")
    payload = b"".join(tone_chunks(channels, "FC", rate=8000, duration_ms=250))
    samples = struct.unpack(f"<{len(payload) // 4}f", payload)
    frames = list(zip(*(iter(samples),) * len(channels), strict=True))

    assert any(frame[2] != 0.0 for frame in frames)
    assert all(frame[0] == frame[1] == frame[3] == 0.0 for frame in frames)
    assert max(abs(frame[2]) for frame in frames) <= 0.08


def test_commands_target_exact_sink_and_complete_channel_map():
    helper = build_speaker_test_command(_output(), "FC", "test-token")
    assert helper[:3] == [sys.executable, "-m", "core.orchestration.speaker_test_worker"]
    assert helper[helper.index("--target") + 1] == "alsa_output.test-surround"
    assert helper[helper.index("--channel-map") + 1] == "FL,FR,FC,LFE"

    pw_cat = build_pw_cat_command(
        "alsa_output.test-surround",
        ("FL", "FR", "FC", "LFE"),
        48000,
        "test-token",
    )
    assert pw_cat[:5] == [
        "pw-cat",
        "--playback",
        "--raw",
        "--target",
        "alsa_output.test-surround",
    ]
    assert pw_cat[pw_cat.index("--channel-map") + 1] == "FL,FR,FC,LFE"
    assert 'open-cinema.diagnostic = "speaker-test"' in pw_cat[-2]


def test_worker_runs_without_django_setup(tmp_path):
    result_path = tmp_path / "pw-cat-result.json"
    fake_pw_cat = tmp_path / "pw-cat"
    fake_pw_cat.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "payload = sys.stdin.buffer.read()\n"
        "pathlib.Path(os.environ['FAKE_PW_CAT_RESULT']).write_text(\n"
        "    json.dumps({'arguments': sys.argv[1:], 'bytes': len(payload)})\n"
        ")\n",
        encoding="utf-8",
    )
    fake_pw_cat.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["FAKE_PW_CAT_RESULT"] = str(result_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.orchestration.speaker_test_worker",
            "--target",
            "alsa_output.test-surround",
            "--channel-map",
            "FL,FR,FC,LFE",
            "--channel",
            "FC",
            "--rate",
            "8000",
            "--duration-ms",
            "250",
            "--token",
            "plain-worker-test",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["bytes"] == 8000 * 250 // 1000 * 4 * 4
    assert result["arguments"][result["arguments"].index("--target") + 1] == (
        "alsa_output.test-surround"
    )


def test_controller_replaces_and_stops_only_verified_helpers(tmp_path, monkeypatch):
    def command(_output, _channel, token, *, duration_ms):
        return [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            "core.orchestration.speaker_test_worker",
            token,
        ]

    monkeypatch.setattr(speaker_test_module, "build_speaker_test_command", command)
    controller = SpeakerTestController(tmp_path, startup_probe_seconds=0.02)
    first = controller.start(_output(), "FL")
    first_pid = controller._read_state()["pid"]
    second = controller.start(_output(), "FC")
    second_pid = controller._read_state()["pid"]

    assert first["channel"] == "FL"
    assert second["channel"] == "FC"
    assert first_pid != second_pid
    deadline = time.monotonic() + 1
    while Path(f"/proc/{first_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not Path(f"/proc/{first_pid}").exists()
    assert controller.status()["active"] is True

    stopped = controller.stop()
    assert stopped["active"] is False
    assert not (tmp_path / "speaker-test.json").exists()


def test_controller_cleans_stale_pid_without_signalling(tmp_path, monkeypatch):
    controller = SpeakerTestController(tmp_path)
    controller._write_state(
        {
            "active": True,
            "token": "stale",
            "pid": os.getpid(),
            "processStartTicks": -1,
            "runtimeKey": "runtime:1:node:1",
        }
    )
    signalled = []
    monkeypatch.setattr(os, "killpg", lambda *arguments: signalled.append(arguments))

    assert controller.status()["active"] is False
    assert signalled == []
    assert not (tmp_path / "speaker-test.json").exists()


def test_controller_sets_audio_environment_and_cleans_finished_helper(tmp_path, monkeypatch):
    environment_file = tmp_path / "environment.txt"

    def command(_output, _channel, token, *, duration_ms):
        script = (
            "import os,pathlib,time; "
            "pathlib.Path(os.sys.argv[1]).write_text("
            "os.environ['XDG_RUNTIME_DIR'] + '\\n' + "
            "os.environ['DBUS_SESSION_BUS_ADDRESS'] + '\\n' + "
            "os.environ['PIPEWIRE_REMOTE']); "
            "time.sleep(0.12)"
        )
        return [
            sys.executable,
            "-c",
            script,
            str(environment_file),
            "core.orchestration.speaker_test_worker",
            token,
        ]

    for name in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "PIPEWIRE_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(speaker_test_module, "build_speaker_test_command", command)
    controller = SpeakerTestController(tmp_path, startup_probe_seconds=0.01)

    controller.start(_output(), "FL")
    deadline = time.monotonic() + 1
    while not environment_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert environment_file.read_text().splitlines() == [
        f"/run/user/{os.getuid()}",
        f"unix:path=/run/user/{os.getuid()}/bus",
        "pipewire-0",
    ]

    while controller.status()["active"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert controller.status()["active"] is False
