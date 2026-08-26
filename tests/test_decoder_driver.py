from __future__ import annotations

import json
import socketserver
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from wyreplumber.runtime import FrozenDict

from core.orchestration.decoder_driver import (
    DECODER_RUNTIME_OWNER,
    DecoderDriver,
    DecoderInstanceConfiguration,
    DecoderStatusClient,
    SubprocessDecoderProcessManager,
    SystemdDecoderProcessManager,
    stable_instance_id,
)
from core.plugin_system.contracts import ProcessingDriverRequest


def status_document(*, sequence: int = 4, instance_id: str = "decoder-main") -> dict:
    return {
        "protocolVersion": 2,
        "messageType": "status",
        "instanceId": instance_id,
        "sequence": sequence,
        "timestamp": "2026-08-22T21:04:05.123Z",
        "lifecycle": "ready",
        "mode": "decoding",
        "transport": {
            "framing": "iec61937",
            "sampleRate": 48000,
            "sampleFormat": "s16le",
            "channels": 2,
            "channelLayout": "stereo",
        },
        "codec": "ac3",
        "decoded": {
            "sampleRate": 48000,
            "sampleFormat": "f32(planar)",
            "channels": 6,
            "channelLayout": "5.1",
        },
        "emitted": {
            "sampleRate": 48000,
            "sampleFormat": "float32le",
            "channels": 8,
            "channelLayout": "7.1",
        },
        "confidence": {
            "score": 1.0,
            "observations": 2,
            "requiredObservations": 2,
        },
        "streams": {
            "captureNodeName": f"open-cinema.decoder.{instance_id}.capture",
            "captureStreamName": f"open-cinema.decoder.{instance_id}.capture.stream",
            "outputNodeName": f"open-cinema.decoder.{instance_id}.output",
            "outputStreamName": f"open-cinema.decoder.{instance_id}.output.stream",
            "nodeGroupName": f"open-cinema.decoder.{instance_id}",
        },
        "errors": [],
    }


class _StatusHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        while request := self.rfile.readline():
            parsed = json.loads(request)
            assert parsed == {"protocolVersion": 2, "messageType": "getStatus"}
            document = self.server.status_documents.pop(0)  # type: ignore[attr-defined]
            self.wfile.write(json.dumps(document).encode() + b"\n")
            self.wfile.flush()
            event = getattr(self.server, "event_document", None)
            if event is not None:
                self.server.event_document = None  # type: ignore[attr-defined]
                self.wfile.write(json.dumps(event).encode() + b"\n")
                self.wfile.flush()


class StatusServer:
    def __init__(
        self,
        path: Path,
        documents: list[dict],
        *,
        event_document: dict | None = None,
    ) -> None:
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        self.server = Server(str(path), _StatusHandler)
        self.server.status_documents = documents  # type: ignore[attr-defined]
        self.server.event_document = event_document  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


class FakeSystemctl:
    def __init__(self) -> None:
        self.active = False
        self.commands: list[tuple[str, ...]] = []
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        self.kwargs.append(dict(kwargs))
        operation = command[1]
        if operation == "start":
            self.active = True
        elif operation == "stop":
            self.active = False
        return subprocess.CompletedProcess(
            command,
            0 if operation != "is-active" or self.active else 3,
            "",
            "",
        )


def request() -> ProcessingDriverRequest:
    return ProcessingDriverRequest(
        "graph/decoder main",
        "generation-7:decoder-main",
        FrozenDict(
            {
                "instanceId": "decoder-main",
                "captureDescriptor": {
                    "sampleFormat": "S16LE",
                    "rate": 48000,
                    "layout": {"channels": 2, "positions": ["FL", "FR"]},
                },
                "outputDescriptor": {
                    "sampleFormat": "FLOAT32LE",
                    "rate": 48000,
                    "layout": {
                        "channels": 8,
                        "positions": ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"],
                    },
                },
                "startupTimeoutSeconds": 1,
            }
        ),
        FrozenDict(),
    )


@pytest.mark.parametrize("manager_kind", ["systemd", "subprocess"])
def test_production_and_development_drivers_share_management_contract(
    tmp_path: Path,
    manager_kind: str,
) -> None:
    runtime = tmp_path / "decoder"
    runtime.mkdir()
    status_server = StatusServer(
        runtime / "decoder-main.sock",
        [status_document(), status_document(sequence=5)],
    )
    fake_systemctl = FakeSystemctl()
    if manager_kind == "systemd":
        manager = SystemdDecoderProcessManager(runner=fake_systemctl)
    else:
        manager = SubprocessDecoderProcessManager(
            command_prefix=(sys.executable, "-c", "import time; time.sleep(60)")
        )
    driver = DecoderDriver(manager, runtime_directory=runtime)
    try:
        prepared = driver.prepare(request())
        environment = runtime / "decoder-main.env"
        assert prepared.status == "prepared"
        assert DECODER_RUNTIME_OWNER in environment.read_text()
        assert stat.S_IMODE(environment.stat().st_mode) == 0o600
        assert driver.prepare(request()).status == "already-prepared"

        assert driver.activate(request()).status == "active"
        observed = driver.observe(request())
        facts = observed.facts.to_dict()
        assert observed.status == "healthy"
        assert facts["statusChannel"] == "connected"
        assert facts["signalDescriptor"]["content"] == {
            "kind": "encoded",
            "codec": "ac3",
        }
        assert facts["signalDescriptor"]["decodedOutput"]["layout"] == {
            "channels": 6,
            "positions": ["FL", "FR", "FC", "LFE", "SL", "SR"],
        }
        assert facts["streams"]["outputNodeName"].endswith(".output")
        assert facts["contractDisagreements"] == []
        assert facts["actualDecodedOutput"]["layout"]["channels"] == 6
        assert facts["emittedOutput"]["layout"] == {
            "channels": 8,
            "positions": ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"],
        }
        assert facts["transport"]["kind"] == "iec61937"
        assert facts["encodedCodec"] == "ac3"
        assert facts["modeDecision"] == {
            "mode": "decoding",
            "choice": "decode-to-working-output",
            "reason": "confirmed_encoded_content",
            "confidence": 1.0,
        }
        assert facts["resolutionFacts"]["signal.decoder-main.decoded.channels"] == 6
        assert facts["resolutionFacts"]["signal.decoder-main.emitted.channels"] == 8
        assert facts["formatExplanation"] == {
            "transport": facts["transport"],
            "content": {"kind": "encoded", "codec": "ac3"},
            "encodedCodec": "ac3",
            "actualDecodedOutput": facts["actualDecodedOutput"],
            "emittedWorkingOutput": facts["emittedOutput"],
            "modeDecision": facts["modeDecision"],
            "contractDisagreements": [],
        }

        assert driver.deactivate(request()).status == "inactive"
        cleaned = driver.cleanup(request())
        assert cleaned.status == "clean"
        assert not environment.exists()
        assert not (runtime / "decoder-main.sock").exists()
    finally:
        if manager_kind == "subprocess":
            manager.stop("decoder-main")
        status_server.close()

    if manager_kind == "systemd":
        assert ("systemctl", "start", "pcm-auto-decoder@decoder-main.service") in (
            fake_systemctl.commands
        )


def test_systemd_decoder_commands_are_bounded() -> None:
    fake_systemctl = FakeSystemctl()
    manager = SystemdDecoderProcessManager(
        runner=fake_systemctl,
        command_timeout_seconds=3,
    )

    manager.start(
        DecoderInstanceConfiguration.from_request(request()),
        environment_path=Path("unused"),
        socket_path=Path("unused"),
    )

    assert fake_systemctl.active is True
    assert fake_systemctl.kwargs[0]["timeout"] == 3


def test_systemd_decoder_timeout_is_actionable() -> None:
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    manager = SystemdDecoderProcessManager(runner=runner)

    with pytest.raises(RuntimeError, match="timed out after 5 seconds"):
        manager.stop("decoder-main")


def test_status_client_resynchronizes_after_sequence_gap(tmp_path: Path) -> None:
    path = tmp_path / "status.sock"
    server = StatusServer(
        path,
        [status_document(sequence=1), status_document(sequence=4)],
        event_document=status_document(sequence=3),
    )
    client = DecoderStatusClient(path)
    try:
        assert client.request_status().sequence == 1
        assert client.next_status().sequence == 4
    finally:
        client.close()
        server.close()


def test_status_socket_failure_is_degraded_and_recovers_on_next_bounded_observation(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "decoder"
    runtime.mkdir()
    fake_systemctl = FakeSystemctl()
    fake_systemctl.active = True
    driver = DecoderDriver(
        SystemdDecoderProcessManager(runner=fake_systemctl),
        runtime_directory=runtime,
    )

    unavailable = driver.observe(request())
    assert unavailable.status == "degraded"
    assert unavailable.facts["processActive"] is True
    assert unavailable.facts["statusChannel"] == "unavailable"

    server = StatusServer(runtime / "decoder-main.sock", [status_document()])
    try:
        recovered = driver.observe(request())
    finally:
        server.close()

    assert recovered.status == "healthy"
    assert recovered.facts["statusChannel"] == "connected"
    assert recovered.facts["sequence"] == 4


def test_cleanup_refuses_unowned_runtime_files(tmp_path: Path) -> None:
    runtime = tmp_path / "decoder"
    runtime.mkdir()
    environment = runtime / "decoder-main.env"
    environment.write_text("OPEN_CINEMA_OWNER=somebody-else\n")
    fake_systemctl = FakeSystemctl()
    fake_systemctl.active = True
    driver = DecoderDriver(
        SystemdDecoderProcessManager(runner=fake_systemctl),
        runtime_directory=runtime,
    )

    outcome = driver.cleanup(request())

    assert outcome.status == "refused-unowned"
    assert environment.exists()
    assert fake_systemctl.active is True
    assert all(command[1] != "stop" for command in fake_systemctl.commands)
    with pytest.raises(RuntimeError, match="refusing to replace unowned"):
        driver.prepare(request())


def test_instance_ids_are_stable_and_safe() -> None:
    assert stable_instance_id("living-room") == "living-room"
    generated = stable_instance_id("graph/decoder main")
    assert generated.startswith("graph-decoder-main-")
    assert generated == stable_instance_id("graph/decoder main")


def test_driver_generates_native_single_output_arguments() -> None:
    configuration = DecoderInstanceConfiguration.from_request(request())

    assert "--capture-layout" in configuration.arguments
    assert "--output-layout" in configuration.arguments
    assert configuration.arguments[configuration.arguments.index("--output-layout") + 1] == "7.1"
    assert configuration.arguments[configuration.arguments.index("--det-window-ms") + 1] == "250"
    assert "--source" not in configuration.arguments
    assert "--sink" not in configuration.arguments
    assert configuration.streams == {
        "captureNodeName": "open-cinema.decoder.decoder-main.capture",
        "captureStreamName": "open-cinema.decoder.decoder-main.capture.stream",
        "outputNodeName": "open-cinema.decoder.decoder-main.output",
        "outputStreamName": "open-cinema.decoder.decoder-main.output.stream",
        "nodeGroupName": "open-cinema.decoder.decoder-main",
    }
