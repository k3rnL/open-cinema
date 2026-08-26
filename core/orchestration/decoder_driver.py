from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from wyreplumber.runtime import FrozenDict

from core.plugin_system.contracts import ProcessingDriverRequest, ProcessingDriverResult

from .signal_contracts import ChannelLayout
from .processor_runtime import ManagedProcessorNodeIdentity
from .signal_descriptors import (
    SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalContentKind,
    SignalDescriptor,
    SignalObservationSource,
    SignalObservationSourceKind,
    SignalTransportDescriptor,
    SignalTransportKind,
)

DECODER_PROTOCOL_VERSION = 2
DECODER_RUNTIME_OWNER = "open-cinema.decoder-driver.v1"
DEFAULT_DECODER_RUNTIME_DIRECTORY = Path("/run/open-cinema/decoder")
_SAFE_INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class DecoderProtocolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: object, field: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise DecoderProtocolError(
            "invalid-status",
            f"{field} must be a non-empty string of at most {maximum} characters",
        )
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DecoderProtocolError("invalid-status", f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecoderProtocolError("invalid-status", f"{field} must be a number")
    normalized = float(value)
    if not 0 <= normalized <= 1:
        raise DecoderProtocolError("invalid-status", f"{field} must be between 0 and 1")
    return normalized


@dataclass(frozen=True, slots=True)
class DecoderAudioDescriptor:
    sample_rate: int
    sample_format: str
    channels: int
    channel_layout: str

    @classmethod
    def from_document(cls, document: object, *, field: str) -> DecoderAudioDescriptor:
        if not isinstance(document, Mapping):
            raise DecoderProtocolError("invalid-status", f"{field} must be an object")
        return cls(
            sample_rate=_integer(document.get("sampleRate"), f"{field}.sampleRate", minimum=1),
            sample_format=_required_text(document.get("sampleFormat"), f"{field}.sampleFormat"),
            channels=_integer(document.get("channels"), f"{field}.channels", minimum=1),
            channel_layout=_required_text(document.get("channelLayout"), f"{field}.channelLayout"),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "sampleRate": self.sample_rate,
            "sampleFormat": self.sample_format,
            "channels": self.channels,
            "channelLayout": self.channel_layout,
        }


@dataclass(frozen=True, slots=True)
class DecoderTransportDescriptor(DecoderAudioDescriptor):
    framing: str

    @classmethod
    def from_document(cls, document: object) -> DecoderTransportDescriptor:
        audio = DecoderAudioDescriptor.from_document(document, field="transport")
        if not isinstance(document, Mapping):  # pragma: no cover - checked above.
            raise AssertionError
        framing = _required_text(document.get("framing"), "transport.framing")
        if framing not in {"unknown", "pcm", "iec61937"}:
            raise DecoderProtocolError("invalid-status", "transport.framing is unsupported")
        return cls(
            audio.sample_rate,
            audio.sample_format,
            audio.channels,
            audio.channel_layout,
            framing,
        )

    def to_document(self) -> dict[str, object]:
        return {"framing": self.framing, **super().to_document()}


@dataclass(frozen=True, slots=True)
class DecoderStatus:
    instance_id: str
    sequence: int
    timestamp: str
    lifecycle: str
    mode: str
    transport: DecoderTransportDescriptor
    codec: str | None
    decoded: DecoderAudioDescriptor | None
    emitted: DecoderAudioDescriptor
    confidence: float
    streams: FrozenDict
    errors: tuple[FrozenDict, ...]
    raw: FrozenDict

    @classmethod
    def from_document(cls, document: object) -> DecoderStatus:
        if not isinstance(document, Mapping):
            raise DecoderProtocolError("invalid-status", "decoder message must be an object")
        version = _integer(document.get("protocolVersion"), "protocolVersion", minimum=1)
        if version != DECODER_PROTOCOL_VERSION:
            raise DecoderProtocolError(
                "unsupported-protocol",
                f"decoder protocol {version} is incompatible with {DECODER_PROTOCOL_VERSION}",
            )
        if document.get("messageType") == "error":
            error = document.get("error")
            message = error.get("message") if isinstance(error, Mapping) else "decoder error"
            code = error.get("code") if isinstance(error, Mapping) else "decoder-error"
            raise DecoderProtocolError(str(code), str(message))
        if document.get("messageType") != "status":
            raise DecoderProtocolError("invalid-status", "messageType must be status")
        lifecycle = _required_text(document.get("lifecycle"), "lifecycle")
        if lifecycle not in {"starting", "ready", "stopping", "failed"}:
            raise DecoderProtocolError("invalid-status", "lifecycle is unsupported")
        mode = _required_text(document.get("mode"), "mode")
        if mode not in {"unknown", "detecting", "pcm", "decoding", "error"}:
            raise DecoderProtocolError("invalid-status", "mode is unsupported")
        codec = document.get("codec")
        if codec is not None:
            codec = _required_text(codec, "codec", maximum=64).lower()
        decoded_document = document.get("decoded")
        emitted_document = document.get("emitted")
        confidence_document = document.get("confidence")
        if not isinstance(confidence_document, Mapping):
            raise DecoderProtocolError("invalid-status", "confidence must be an object")
        streams = document.get("streams")
        if not isinstance(streams, Mapping):
            raise DecoderProtocolError("invalid-status", "streams must be an object")
        required_streams = {
            "captureNodeName",
            "captureStreamName",
            "outputNodeName",
            "outputStreamName",
            "nodeGroupName",
        }
        for name in required_streams:
            _required_text(streams.get(name), f"streams.{name}")
        errors = document.get("errors")
        if not isinstance(errors, Sequence) or isinstance(errors, (str, bytes)):
            raise DecoderProtocolError("invalid-status", "errors must be an array")
        normalized_errors = []
        for error in errors:
            if not isinstance(error, Mapping):
                raise DecoderProtocolError("invalid-status", "errors must contain objects")
            _required_text(error.get("code"), "errors.code")
            _required_text(error.get("message"), "errors.message")
            if not isinstance(error.get("recoverable"), bool):
                raise DecoderProtocolError("invalid-status", "errors.recoverable must be boolean")
            normalized_errors.append(FrozenDict(error))
        return cls(
            instance_id=_required_text(document.get("instanceId"), "instanceId"),
            sequence=_integer(document.get("sequence"), "sequence"),
            timestamp=_required_text(document.get("timestamp"), "timestamp"),
            lifecycle=lifecycle,
            mode=mode,
            transport=DecoderTransportDescriptor.from_document(document.get("transport")),
            codec=codec,
            decoded=(
                DecoderAudioDescriptor.from_document(decoded_document, field="decoded")
                if decoded_document is not None
                else None
            ),
            emitted=DecoderAudioDescriptor.from_document(emitted_document, field="emitted"),
            confidence=_number(confidence_document.get("score"), "confidence.score"),
            streams=FrozenDict(streams),
            errors=tuple(normalized_errors),
            raw=FrozenDict(document),
        )

    def signal_descriptor(self) -> SignalDescriptor:
        transport_kind = {
            "unknown": SignalTransportKind.UNKNOWN,
            "pcm": SignalTransportKind.PCM,
            "iec61937": SignalTransportKind.IEC61937,
        }[self.transport.framing]
        if self.codec is not None:
            content = SignalContentDescriptor(SignalContentKind.ENCODED, self.codec)
        elif self.mode == "pcm":
            content = SignalContentDescriptor(SignalContentKind.PCM)
        else:
            content = SignalContentDescriptor(SignalContentKind.UNKNOWN)
        return SignalDescriptor(
            version=SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
            transport=SignalTransportDescriptor(
                transport_kind,
                _audio_format(self.transport),
            ),
            content=content,
            decoded_output=(_audio_format(self.decoded) if self.decoded is not None else None),
            confidence=self.confidence,
            source=SignalObservationSource(
                SignalObservationSourceKind.DECODER,
                self.instance_id,
                self.sequence,
            ),
            observed_at=self.timestamp,
        )

    def mode_decision(self) -> dict[str, object]:
        choice, reason = {
            "unknown": ("silence", "signal_mode_unknown"),
            "detecting": ("silence", "signal_classification_in_progress"),
            "pcm": ("emit-normalized-pcm", "confirmed_pcm_content"),
            "decoding": ("decode-to-working-output", "confirmed_encoded_content"),
            "error": ("silence", "decoder_reported_error"),
        }[self.mode]
        return {
            "mode": self.mode,
            "choice": choice,
            "reason": reason,
            "confidence": self.confidence,
        }


def _audio_format(descriptor: DecoderAudioDescriptor) -> AudioFormatDescriptor:
    positions = {
        "mono": ("MONO",),
        "stereo": ("FL", "FR"),
        "5.1": ("FL", "FR", "FC", "LFE", "SL", "SR"),
        "5.1-side": ("FL", "FR", "FC", "LFE", "SL", "SR"),
        "5.1-back": ("FL", "FR", "FC", "LFE", "RL", "RR"),
        "5.1-rear": ("FL", "FR", "FC", "LFE", "RL", "RR"),
        "7.1": ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"),
    }.get(descriptor.channel_layout, ())
    return AudioFormatDescriptor(
        sample_format=descriptor.sample_format,
        rate=descriptor.sample_rate,
        layout=ChannelLayout(descriptor.channels, positions),
    )


class DecoderStatusClient:
    def __init__(self, socket_path: Path, *, timeout_seconds: float = 1.0) -> None:
        self.socket_path = Path(socket_path)
        self.timeout_seconds = timeout_seconds
        self._socket: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._instance_id: str | None = None
        self._sequence: int | None = None

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        if self._socket is not None:
            self._socket.close()
        self._reader = None
        self._socket = None

    def request_status(self) -> DecoderStatus:
        self._ensure_connected()
        assert self._socket is not None
        self._socket.sendall(
            json.dumps(
                {"protocolVersion": DECODER_PROTOCOL_VERSION, "messageType": "getStatus"},
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        status = self._read_status()
        self._instance_id = status.instance_id
        self._sequence = status.sequence
        return status

    def next_status(self) -> DecoderStatus:
        self._ensure_connected()
        status = self._read_status()
        if self._instance_id != status.instance_id:
            return self.request_status()
        if self._sequence is not None and status.sequence != self._sequence + 1:
            return self.request_status()
        self._sequence = status.sequence
        return status

    def _ensure_connected(self) -> None:
        if self._socket is not None:
            return
        stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stream.settimeout(self.timeout_seconds)
        try:
            stream.connect(str(self.socket_path))
        except Exception:
            stream.close()
            raise
        self._socket = stream
        self._reader = stream.makefile("rb")

    def _read_status(self) -> DecoderStatus:
        assert self._reader is not None
        line = self._reader.readline(1024 * 1024)
        if not line:
            self.close()
            raise DecoderProtocolError("status-disconnected", "decoder status socket disconnected")
        if len(line) >= 1024 * 1024 or not line.endswith(b"\n"):
            raise DecoderProtocolError("status-too-large", "decoder status line is too large")
        try:
            document = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DecoderProtocolError(
                "malformed-status", "decoder emitted malformed JSON"
            ) from error
        return DecoderStatus.from_document(document)


_LAYOUT_ARGUMENTS = {
    ("MONO",): "mono",
    ("FL", "FR"): "stereo",
    ("FL", "FR", "FC", "LFE", "SL", "SR"): "5.1-side",
    ("FL", "FR", "FC", "LFE", "RL", "RR"): "5.1-rear",
    ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"): "7.1",
}


def _configured_descriptor(
    document: object,
    *,
    role: str,
    default: AudioFormatDescriptor,
) -> AudioFormatDescriptor:
    try:
        descriptor = (
            default
            if document is None
            else AudioFormatDescriptor.from_document(document)  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {role}Descriptor: {error}") from error
    if descriptor.sample_format is None or descriptor.rate is None or descriptor.layout is None:
        raise ValueError(f"{role}Descriptor must include sampleFormat, rate, and layout")
    if tuple(descriptor.layout.positions) not in _LAYOUT_ARGUMENTS:
        raise ValueError(f"{role}Descriptor has an unsupported or ambiguous channel layout")
    if descriptor.layout.channels != len(descriptor.layout.positions):
        raise ValueError(f"{role}Descriptor must declare explicit channel positions")
    supported_formats = (
        {"S16LE", "S32LE"}
        if role == "capture"
        else {
            "S16LE",
            "S32LE",
            "FLOAT32LE",
        }
    )
    if descriptor.sample_format not in supported_formats:
        raise ValueError(
            f"{role}Descriptor sampleFormat must be one of {', '.join(sorted(supported_formats))}"
        )
    return descriptor


def _layout_argument(descriptor: AudioFormatDescriptor) -> str:
    assert descriptor.layout is not None
    return _LAYOUT_ARGUMENTS[tuple(descriptor.layout.positions)]


def _positive_configuration_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_configuration_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _validate_position_preserving_expansion(
    capture: AudioFormatDescriptor,
    output: AudioFormatDescriptor,
) -> None:
    assert capture.layout is not None and output.layout is not None
    if capture.rate != output.rate:
        raise ValueError("captureDescriptor and outputDescriptor rates must match")
    output_positions = set(output.layout.positions)
    missing = [
        position
        for position in capture.layout.positions
        if position not in output_positions
        and not (position == "MONO" and "FC" in output_positions)
    ]
    if missing:
        raise ValueError(
            "outputDescriptor would narrow or discard capture positions: " + ", ".join(missing)
        )


@dataclass(frozen=True, slots=True)
class DecoderInstanceConfiguration:
    instance_id: str
    binary_path: str
    capture_descriptor: AudioFormatDescriptor
    output_descriptor: AudioFormatDescriptor
    chunk_frames: int
    detection_window_ms: int
    encoded_confirmations: int
    capture_file: str | None = None
    output_file: str | None = None
    loop_capture_file: bool = False
    startup_timeout_seconds: float = 5.0

    @classmethod
    def from_request(cls, request: ProcessingDriverRequest) -> DecoderInstanceConfiguration:
        configuration = request.configuration.to_dict()
        plan_configuration = request.plan.to_dict().get("driverConfiguration", {})
        if plan_configuration:
            if not isinstance(plan_configuration, Mapping):
                raise ValueError("plan.driverConfiguration must be an object")
            configuration.update(plan_configuration)
        instance_id = configuration.get("instanceId") or stable_instance_id(
            request.node_instance_id
        )
        if not isinstance(instance_id, str) or _SAFE_INSTANCE_ID.fullmatch(instance_id) is None:
            raise ValueError("instanceId must contain only letters, digits, '.', '_' and '-'")
        binary_path = configuration.get("binaryPath", "/usr/local/bin/pcm-auto-decoder")
        if not isinstance(binary_path, str) or not binary_path:
            raise ValueError("binaryPath must be a non-empty string")
        capture_descriptor = _configured_descriptor(
            configuration.get("captureDescriptor"),
            role="capture",
            default=AudioFormatDescriptor("S16LE", 48_000, ChannelLayout(2, ("FL", "FR"))),
        )
        output_descriptor = _configured_descriptor(
            configuration.get("outputDescriptor"),
            role="output",
            default=AudioFormatDescriptor(
                "FLOAT32LE",
                48_000,
                ChannelLayout(8, ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")),
            ),
        )
        _validate_position_preserving_expansion(capture_descriptor, output_descriptor)
        chunk_frames = _positive_configuration_integer(
            configuration.get("chunkFrames", 512), "chunkFrames"
        )
        detection_window_ms = _non_negative_configuration_integer(
            configuration.get("detectionWindowMs", 250), "detectionWindowMs"
        )
        encoded_confirmations = _positive_configuration_integer(
            configuration.get("encodedConfirmations", 2), "encodedConfirmations"
        )
        capture_file = configuration.get("captureFile")
        output_file = configuration.get("outputFile")
        if (capture_file is None) != (output_file is None):
            raise ValueError("offline decoder mode requires captureFile and outputFile together")
        for field, value in (("captureFile", capture_file), ("outputFile", output_file)):
            if value is not None and (not isinstance(value, str) or not value.startswith("/")):
                raise ValueError(f"{field} must be an absolute path or null")
        loop_capture_file = configuration.get("loopCaptureFile", False)
        if not isinstance(loop_capture_file, bool):
            raise ValueError("loopCaptureFile must be boolean")
        if loop_capture_file and capture_file is None:
            raise ValueError("loopCaptureFile requires offline decoder mode")
        timeout = configuration.get("startupTimeoutSeconds", 5.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("startupTimeoutSeconds must be a positive number")
        return cls(
            instance_id,
            binary_path,
            capture_descriptor,
            output_descriptor,
            chunk_frames,
            detection_window_ms,
            encoded_confirmations,
            capture_file,
            output_file,
            loop_capture_file,
            float(timeout),
        )

    @property
    def arguments(self) -> tuple[str, ...]:
        arguments = (
            "--capture-format",
            str(self.capture_descriptor.sample_format),
            "--capture-rate",
            str(self.capture_descriptor.rate),
            "--capture-layout",
            _layout_argument(self.capture_descriptor),
            "--output-format",
            str(self.output_descriptor.sample_format),
            "--output-rate",
            str(self.output_descriptor.rate),
            "--output-layout",
            _layout_argument(self.output_descriptor),
            "--chunk-frames",
            str(self.chunk_frames),
            "--det-window-ms",
            str(self.detection_window_ms),
            "--encoded-confirmations",
            str(self.encoded_confirmations),
        )
        if self.capture_file is None:
            return arguments
        offline = (
            "--capture-file",
            self.capture_file,
            "--output-file",
            str(self.output_file),
        )
        if self.loop_capture_file:
            offline = (*offline, "--loop-capture-file")
        return (*arguments, *offline)

    @property
    def streams(self) -> dict[str, str]:
        prefix = f"open-cinema.decoder.{self.instance_id}"
        return {
            "captureNodeName": f"{prefix}.capture",
            "captureStreamName": f"{prefix}.capture.stream",
            "outputNodeName": f"{prefix}.output",
            "outputStreamName": f"{prefix}.output.stream",
            "nodeGroupName": prefix,
        }

    @property
    def runtime_identities(self) -> tuple[ManagedProcessorNodeIdentity, ...]:
        streams = self.streams
        shared = {
            "open-cinema.processor.kind": "adaptive-decoder",
            "open-cinema.processor.instance": self.instance_id,
        }
        return (
            ManagedProcessorNodeIdentity(
                "adaptive-decoder",
                self.instance_id,
                "capture",
                streams["captureNodeName"],
                streams["nodeGroupName"],
                {**shared, "open-cinema.processor.port": "capture"},
            ),
            ManagedProcessorNodeIdentity(
                "adaptive-decoder",
                self.instance_id,
                "output",
                streams["outputNodeName"],
                streams["nodeGroupName"],
                {**shared, "open-cinema.processor.port": "output"},
            ),
        )


def stable_instance_id(node_instance_id: str) -> str:
    if _SAFE_INSTANCE_ID.fullmatch(node_instance_id):
        return node_instance_id
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_instance_id).strip("-.") or "decoder"
    digest = hashlib.sha256(node_instance_id.encode()).hexdigest()[:10]
    return f"{slug[:68]}-{digest}"


class DecoderProcessManager(Protocol):
    def start(
        self,
        configuration: DecoderInstanceConfiguration,
        *,
        environment_path: Path,
        socket_path: Path,
    ) -> None: ...

    def stop(self, instance_id: str) -> None: ...

    def is_active(self, instance_id: str) -> bool: ...


class SystemdDecoderProcessManager:
    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        command_timeout_seconds: float = 5.0,
    ) -> None:
        if (
            isinstance(command_timeout_seconds, bool)
            or not isinstance(command_timeout_seconds, (int, float))
            or not 0 < command_timeout_seconds <= 30
        ):
            raise ValueError("command_timeout_seconds must be between zero and 30")
        self._runner = runner
        self.command_timeout_seconds = float(command_timeout_seconds)

    @staticmethod
    def unit(instance_id: str) -> str:
        return f"pcm-auto-decoder@{instance_id}.service"

    def _run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(
                ["systemctl", *arguments],
                text=True,
                capture_output=True,
                check=False,
                timeout=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"systemctl {' '.join(arguments)} timed out after "
                f"{self.command_timeout_seconds:g} seconds"
            ) from error
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "systemctl failed")
        return result

    def start(
        self,
        configuration: DecoderInstanceConfiguration,
        *,
        environment_path: Path,
        socket_path: Path,
    ) -> None:
        del environment_path, socket_path
        self._run("start", self.unit(configuration.instance_id))

    def stop(self, instance_id: str) -> None:
        self._run("stop", self.unit(instance_id))

    def is_active(self, instance_id: str) -> bool:
        return (
            self._run("is-active", "--quiet", self.unit(instance_id), check=False).returncode == 0
        )


class SubprocessDecoderProcessManager:
    def __init__(self, *, command_prefix: Sequence[str] | None = None) -> None:
        self.command_prefix = tuple(command_prefix or ())
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def start(
        self,
        configuration: DecoderInstanceConfiguration,
        *,
        environment_path: Path,
        socket_path: Path,
    ) -> None:
        del environment_path
        current = self._processes.get(configuration.instance_id)
        if current is not None and current.poll() is None:
            return
        command = (self.command_prefix or (configuration.binary_path,)) + (
            "--instance-id",
            configuration.instance_id,
            "--status-socket",
            str(socket_path),
            *configuration.arguments,
        )
        self._processes[configuration.instance_id] = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self, instance_id: str) -> None:
        process = self._processes.pop(instance_id, None)
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def is_active(self, instance_id: str) -> bool:
        process = self._processes.get(instance_id)
        return process is not None and process.poll() is None


class DecoderDriver:
    def __init__(
        self,
        process_manager: DecoderProcessManager,
        *,
        runtime_directory: Path = DEFAULT_DECODER_RUNTIME_DIRECTORY,
        status_client_factory: Callable[[Path, float], DecoderStatusClient] | None = None,
    ) -> None:
        self.process_manager = process_manager
        self.runtime_directory = Path(runtime_directory)
        self.status_client_factory = status_client_factory or (
            lambda path, timeout: DecoderStatusClient(path, timeout_seconds=timeout)
        )
        self._clients: dict[str, DecoderStatusClient] = {}

    def prepare(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        self.runtime_directory.mkdir(mode=0o750, parents=True, exist_ok=True)
        environment_path = self._environment_path(configuration.instance_id)
        if environment_path.exists() and not self._is_owned_environment(configuration.instance_id):
            raise RuntimeError(
                f"refusing to replace unowned decoder configuration {environment_path}"
            )
        content = self._environment_content(configuration)
        changed = not environment_path.exists() or environment_path.read_text() != content
        if changed:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.runtime_directory,
                prefix=f".{configuration.instance_id}.",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, environment_path)
        return ProcessingDriverResult(
            "prepared" if changed else "already-prepared",
            self._base_facts(configuration),
            {"configurationDigest": hashlib.sha256(content.encode()).hexdigest()},
        )

    def observe(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        base = self._base_facts(configuration)
        if not self.process_manager.is_active(configuration.instance_id):
            return ProcessingDriverResult(
                "inactive",
                {**base, "processActive": False, "statusChannel": "unavailable"},
            )
        client = self._clients.get(configuration.instance_id)
        if client is None:
            client = self.status_client_factory(
                self._socket_path(configuration.instance_id),
                configuration.startup_timeout_seconds,
            )
            self._clients[configuration.instance_id] = client
        try:
            status = client.request_status()
        except (OSError, DecoderProtocolError) as error:
            self._close_client(configuration.instance_id)
            return ProcessingDriverResult(
                "degraded",
                {
                    **base,
                    "processActive": True,
                    "statusChannel": "unavailable",
                    "statusError": str(error),
                },
            )
        if status.instance_id != configuration.instance_id:
            return ProcessingDriverResult(
                "degraded",
                {
                    **base,
                    "processActive": True,
                    "statusChannel": "mismatched-instance",
                    "observedInstanceId": status.instance_id,
                },
            )
        try:
            signal = status.signal_descriptor()
        except (TypeError, ValueError) as error:
            return ProcessingDriverResult(
                "degraded",
                {
                    **base,
                    "processActive": True,
                    "statusChannel": "invalid-status",
                    "statusError": str(error),
                },
            )
        disagreements = self._contract_disagreements(configuration, status)
        health = (
            "healthy"
            if status.lifecycle == "ready" and status.mode != "error" and not disagreements
            else "degraded"
        )
        actual_decoded = (
            _audio_format(status.decoded).to_document() if status.decoded is not None else None
        )
        emitted_output = _audio_format(status.emitted).to_document()
        signal_document = signal.to_document()
        mode_decision = status.mode_decision()
        resolution_facts = signal.to_facts(configuration.instance_id)
        emitted_descriptor = _audio_format(status.emitted)
        resolution_prefix = f"signal.{configuration.instance_id}.emitted"
        resolution_facts.update(
            {
                f"{resolution_prefix}.sampleFormat": emitted_descriptor.sample_format,
                f"{resolution_prefix}.rate": emitted_descriptor.rate,
                f"{resolution_prefix}.channels": (
                    emitted_descriptor.layout.channels
                    if emitted_descriptor.layout is not None
                    else None
                ),
                f"{resolution_prefix}.layout": (
                    emitted_descriptor.layout.to_document()
                    if emitted_descriptor.layout is not None
                    else None
                ),
            }
        )
        format_explanation = {
            "transport": signal.transport.to_document(),
            "content": signal.content.to_document(),
            "encodedCodec": status.codec,
            "actualDecodedOutput": actual_decoded,
            "emittedWorkingOutput": emitted_output,
            "modeDecision": mode_decision,
            "contractDisagreements": disagreements,
        }
        return ProcessingDriverResult(
            health,
            {
                **base,
                "processActive": True,
                "statusChannel": "connected",
                "lifecycle": status.lifecycle,
                "mode": status.mode,
                "sequence": status.sequence,
                "signalDescriptor": signal_document,
                "transport": signal.transport.to_document(),
                "encodedCodec": status.codec,
                "actualDecodedOutput": actual_decoded,
                "emittedOutput": emitted_output,
                "modeDecision": mode_decision,
                "resolutionFacts": resolution_facts,
                "formatExplanation": format_explanation,
                "streams": status.streams.to_dict(),
                "contractDisagreements": disagreements,
                "errors": [error.to_dict() for error in status.errors],
            },
            {"protocolVersion": DECODER_PROTOCOL_VERSION},
        )

    def activate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        if not self._is_owned_environment(configuration.instance_id):
            self.prepare(request)
        self.process_manager.start(
            configuration,
            environment_path=self._environment_path(configuration.instance_id),
            socket_path=self._socket_path(configuration.instance_id),
        )
        return ProcessingDriverResult(
            "active",
            {**self._base_facts(configuration), "processActive": True},
        )

    def reconfigure(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        self.prepare(request)
        self._close_client(configuration.instance_id)
        self.process_manager.stop(configuration.instance_id)
        self.process_manager.start(
            configuration,
            environment_path=self._environment_path(configuration.instance_id),
            socket_path=self._socket_path(configuration.instance_id),
        )
        return ProcessingDriverResult(
            "reconfigured",
            {**self._base_facts(configuration), "processActive": True},
        )

    def deactivate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        self._close_client(configuration.instance_id)
        self.process_manager.stop(configuration.instance_id)
        return ProcessingDriverResult(
            "inactive",
            {**self._base_facts(configuration), "processActive": False},
        )

    def cleanup(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        configuration = DecoderInstanceConfiguration.from_request(request)
        if not self._is_owned_environment(configuration.instance_id):
            return ProcessingDriverResult(
                "refused-unowned",
                self._base_facts(configuration),
                {"removed": [], "reason": "runtime configuration is not Open Cinema-owned"},
            )
        self.deactivate(request)
        removed: list[str] = []
        if self._is_owned_environment(configuration.instance_id):
            environment_path = self._environment_path(configuration.instance_id)
            environment_path.unlink(missing_ok=True)
            removed.append(str(environment_path))
            socket_path = self._socket_path(configuration.instance_id)
            socket_path.unlink(missing_ok=True)
            removed.append(str(socket_path))
        return ProcessingDriverResult(
            "clean",
            {**self._base_facts(configuration), "processActive": False},
            {"removed": removed},
        )

    def _base_facts(self, configuration: DecoderInstanceConfiguration) -> dict[str, object]:
        return {
            "instanceId": configuration.instance_id,
            "environmentPath": str(self._environment_path(configuration.instance_id)),
            "socketPath": str(self._socket_path(configuration.instance_id)),
            "ownedBy": DECODER_RUNTIME_OWNER,
            "requestedCapture": configuration.capture_descriptor.to_document(),
            "requestedOutput": configuration.output_descriptor.to_document(),
            "streams": configuration.streams,
        }

    @staticmethod
    def _contract_disagreements(
        configuration: DecoderInstanceConfiguration,
        status: DecoderStatus,
    ) -> list[str]:
        disagreements = []
        if _audio_format(status.transport) != configuration.capture_descriptor:
            disagreements.append("capture-format-mismatch")
        if _audio_format(status.emitted) != configuration.output_descriptor:
            disagreements.append("emitted-format-mismatch")
        observed_streams = status.streams.to_dict()
        for field, expected in configuration.streams.items():
            if observed_streams.get(field) != expected:
                disagreements.append(f"stream-identity-mismatch:{field}")
        return disagreements

    def _environment_path(self, instance_id: str) -> Path:
        return self.runtime_directory / f"{instance_id}.env"

    def _socket_path(self, instance_id: str) -> Path:
        return self.runtime_directory / f"{instance_id}.sock"

    @staticmethod
    def _environment_content(configuration: DecoderInstanceConfiguration) -> str:
        arguments = " ".join(configuration.arguments)
        return (
            f"OPEN_CINEMA_OWNER={shlex.quote(DECODER_RUNTIME_OWNER)}\n"
            f"OPEN_CINEMA_INSTANCE_ID={shlex.quote(configuration.instance_id)}\n"
            f"DECODER_ARGS={shlex.quote(arguments)}\n"
        )

    def _is_owned_environment(self, instance_id: str) -> bool:
        environment_path = self._environment_path(instance_id)
        if not environment_path.is_file():
            return False
        try:
            values = {}
            for line in environment_path.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    parsed = shlex.split(value)
                    values[key] = parsed[0] if parsed else ""
        except (OSError, ValueError):
            return False
        return (
            values.get("OPEN_CINEMA_OWNER") == DECODER_RUNTIME_OWNER
            and values.get("OPEN_CINEMA_INSTANCE_ID") == instance_id
        )

    def _close_client(self, instance_id: str) -> None:
        client = self._clients.pop(instance_id, None)
        if client is not None:
            client.close()
