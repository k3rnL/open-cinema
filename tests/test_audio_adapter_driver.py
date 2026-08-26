import io
import signal
import subprocess
import threading
import time
import wave

import pytest

from core.orchestration.audio_adapter_driver import (
    ADAPTER_RUNTIME_OWNER,
    AudioAdapterDriver,
    AudioAdapterDriverError,
    ManagedAdapterRuntime,
    adapter_node_name,
    adapter_node_properties,
    build_adapter_command,
    build_roc_cli_instruction,
    inspect_pcm_wav,
    loop_pcm_wav,
    stop_process_gracefully,
)
from core.orchestration.audio_adapters import (
    DEBUG_FILE_RECORDER,
    DEBUG_FILE_SOURCE,
    ROC_RECEIVER,
    ROC_SENDER,
    normalize_adapter_configuration,
)


def _wav(path, frames=b"\x01\x00\x01\x00" * 32):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(frames)


class FakeProcess:
    def __init__(self, *, pid=321, running=True, wait_timeouts=0):
        self.pid = pid
        self.returncode = None if running else 1
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO(b"driver failed")
        self.signals = []
        self.wait_timeouts = wait_timeouts
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout):
        if self.wait_timeouts:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("adapter", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_stable_metadata_and_roc_commands_are_shell_free():
    properties = adapter_node_properties("adapter-1", 'Receiver "test"', ROC_RECEIVER)
    receiver = normalize_adapter_configuration(ROC_RECEIVER, {"localAddress": "0.0.0.0"})
    sender = normalize_adapter_configuration(ROC_SENDER, {"remoteAddress": "192.168.1.30"})

    receiver_command, _, _ = build_adapter_command("adapter-1", "Receiver", ROC_RECEIVER, receiver)
    sender_command, _, _ = build_adapter_command("adapter-2", "Sender", ROC_SENDER, sender)

    assert properties["node.name"] == adapter_node_name("adapter-1")
    assert properties["open-cinema.owner"] == ADAPTER_RUNTIME_OWNER
    receiver_instruction = build_roc_cli_instruction(
        "adapter-1", "Receiver", ROC_RECEIVER, receiver
    ).decode()
    sender_instruction = build_roc_cli_instruction(
        "adapter-2", "Sender", ROC_SENDER, sender
    ).decode()
    assert receiver_command == ["pw-cli", "--daemon"]
    assert receiver_instruction.startswith("load-module libpipewire-module-roc-source ")
    assert "local.source.port = 10001" in receiver_instruction
    assert sender_command == ["pw-cli", "--daemon"]
    assert sender_instruction.startswith("load-module libpipewire-module-roc-sink ")
    assert 'remote.ip = "192.168.1.30"' in sender_instruction
    assert all(";" not in argument for argument in receiver_command)


def test_plain_rtp_roc_commands_omit_repair_endpoints():
    receiver = normalize_adapter_configuration(
        ROC_RECEIVER, {"localAddress": "0.0.0.0", "fecCode": "disable"}
    )
    sender = normalize_adapter_configuration(
        ROC_SENDER, {"remoteAddress": "192.0.2.1", "fecCode": "disable"}
    )

    receiver_command, _, _ = build_adapter_command(
        "adapter-plain-input", "Plain RTP input", ROC_RECEIVER, receiver
    )
    sender_command, _, _ = build_adapter_command(
        "adapter-plain-output", "Plain RTP output", ROC_SENDER, sender
    )

    receiver_instruction = build_roc_cli_instruction(
        "adapter-plain-input", "Plain RTP input", ROC_RECEIVER, receiver
    ).decode()
    sender_instruction = build_roc_cli_instruction(
        "adapter-plain-output", "Plain RTP output", ROC_SENDER, sender
    ).decode()
    assert 'fec.code = "disable"' in receiver_instruction
    assert "local.repair.port" not in receiver_instruction
    assert 'fec.code = "disable"' in sender_instruction
    assert "remote.repair.port" not in sender_instruction


def test_roc_driver_keeps_pw_cli_alive_with_an_open_command_stream():
    process = FakeProcess()
    calls = []

    def popen(command, **options):
        calls.append((command, options))
        return process

    configuration = normalize_adapter_configuration(
        ROC_RECEIVER, {"localAddress": "0.0.0.0", "fecCode": "disable"}
    )
    runtime = AudioAdapterDriver(popen=popen).start(
        "adapter-1", "Network input", ROC_RECEIVER, configuration
    )

    assert calls[0][0] == ["pw-cli", "--daemon"]
    assert calls[0][1]["stdin"] == subprocess.PIPE
    assert process.stdin.getvalue().startswith(b"load-module libpipewire-module-roc-source ")
    assert runtime.poll().running is True


def test_wav_inspection_and_file_commands(tmp_path):
    source_path = tmp_path / "loop.wav"
    _wav(source_path)
    source = normalize_adapter_configuration(
        DEBUG_FILE_SOURCE, {"path": "loop.wav"}, media_root=tmp_path
    )
    recorder = normalize_adapter_configuration(
        DEBUG_FILE_RECORDER, {"path": "capture.wav"}, media_root=tmp_path
    )

    info = inspect_pcm_wav(source_path)
    source_command, _, _ = build_adapter_command(
        "source", "Loop", DEBUG_FILE_SOURCE, source, media_root=tmp_path
    )
    recorder_command, _, output = build_adapter_command(
        "sink", "Recorder", DEBUG_FILE_RECORDER, recorder, media_root=tmp_path
    )

    assert (info.rate, info.channels, info.sample_format) == (48000, 2, "s16")
    assert source_command[:5] == ["pw-cat", "--playback", "--raw", "--target", "0"]
    assert "Audio/Source" in source_command[-2]
    assert "media.class" in source_command[-2]
    assert recorder_command[0] == "pw-record"
    assert output == tmp_path / "capture.wav"


def test_pcm_feeder_loops_without_replacing_its_sink(tmp_path):
    source_path = tmp_path / "short.wav"
    _wav(source_path, frames=b"\x01\x00\x01\x00")
    stop = threading.Event()

    class StoppingSink(io.BytesIO):
        def flush(self):
            if self.tell() >= 8:
                stop.set()

    progress = {}
    sink = StoppingSink()
    loop_pcm_wav(source_path, sink, stop, progress, chunk_frames=1)
    assert progress["loops"] >= 1
    assert progress["bytes"] >= 8


def test_graceful_stop_escalates_only_after_timeout():
    graceful = FakeProcess()
    forced = FakeProcess(wait_timeouts=1)

    assert stop_process_gracefully(graceful, 0.01) is False
    assert graceful.signals == [signal.SIGINT]
    assert stop_process_gracefully(forced, 0.01) is True
    assert forced.terminated is True
    assert forced.killed is False


def test_feeder_process_is_stopped_before_its_input_stream_is_closed():
    process = FakeProcess()

    class OrderedStream(io.BytesIO):
        def close(self):
            assert process.poll() is not None
            super().close()

    class JoinedFeeder:
        def __init__(self):
            self.joined = False

        def join(self, timeout):
            self.joined = timeout > 0

    process.stdin = OrderedStream()
    feeder_stop = threading.Event()
    feeder = JoinedFeeder()

    ManagedAdapterRuntime(
        process,
        feeder_stop=feeder_stop,
        feeder=feeder,
        stop_timeout=0.01,
    ).stop()

    assert feeder_stop.is_set()
    assert feeder.joined is True


def test_recorder_collision_is_preserved(tmp_path):
    output = tmp_path / "capture.wav"
    output.write_bytes(b"existing")
    configuration = normalize_adapter_configuration(
        DEBUG_FILE_RECORDER,
        {"path": "capture.wav"},
        media_root=tmp_path,
    )
    driver = AudioAdapterDriver(
        media_root=tmp_path, popen=lambda *args, **kwargs: pytest.fail("must not start")
    )
    with pytest.raises(AudioAdapterDriverError, match="already exists"):
        driver.start("adapter", "Recorder", DEBUG_FILE_RECORDER, configuration)
    assert output.read_bytes() == b"existing"


def test_runtime_observes_failure_and_finalizes_recorder(tmp_path):
    output = tmp_path / "capture.wav"
    output.write_bytes(b"wav")
    failed = FakeProcess(running=False)
    observation = ManagedAdapterRuntime(failed, output_path=output).poll()
    assert observation.running is False
    assert observation.error["detail"] == "driver failed"
    assert observation.progress["bytes"] == 3

    running = FakeProcess()
    runtime = ManagedAdapterRuntime(running, output_path=output, stop_timeout=0.01)
    result = runtime.stop()
    assert running.signals == [signal.SIGINT]
    assert result["bytes"] == 3
