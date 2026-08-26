from __future__ import annotations

import hashlib
import json
import signal
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from django.conf import settings

from .audio_adapters import (
    DEBUG_FILE_RECORDER,
    DEBUG_FILE_SOURCE,
    ROC_RECEIVER,
    ROC_SENDER,
    resolve_adapter_media_path,
)

ADAPTER_RUNTIME_OWNER = "open-cinema.adapter-supervisor.v1"


class AudioAdapterDriverError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PCMWaveInfo:
    rate: int
    channels: int
    sample_width: int
    sample_format: str
    channel_map: str
    frame_count: int


@dataclass(frozen=True, slots=True)
class AdapterProcessObservation:
    running: bool
    process_id: int | None
    exit_code: int | None
    progress: dict[str, object]
    error: dict[str, object]


def adapter_node_name(adapter_id: object) -> str:
    return f"open-cinema-adapter-{adapter_id}"


def adapter_configuration_digest(
    kind: str,
    configuration: dict[str, object],
    restart_generation: int = 0,
) -> str:
    document = {
        "kind": kind,
        "configuration": configuration,
        "restartGeneration": restart_generation,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def adapter_node_properties(
    adapter_id: object,
    name: str,
    kind: str,
) -> dict[str, object]:
    network = kind in {ROC_RECEIVER, ROC_SENDER}
    direction = "input" if kind in {ROC_RECEIVER, DEBUG_FILE_SOURCE} else "output"
    return {
        "node.name": adapter_node_name(adapter_id),
        "node.description": name,
        "media.class": "Audio/Source" if direction == "input" else "Audio/Sink",
        "node.virtual": True,
        "node.network": network,
        "node.autoconnect": False,
        "open-cinema.owner": ADAPTER_RUNTIME_OWNER,
        "open-cinema.adapter.id": str(adapter_id),
        "open-cinema.adapter.kind": kind,
        "open-cinema.adapter.direction": direction,
    }


def _spa_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def pipewire_properties_document(properties: dict[str, object]) -> str:
    fields = " ".join(f"{key} = {_spa_value(value)}" for key, value in sorted(properties.items()))
    return f"{{ {fields} }}"


def _roc_module_arguments(
    adapter_id: object,
    name: str,
    kind: str,
    configuration: dict[str, object],
) -> tuple[str, str]:
    properties = pipewire_properties_document(adapter_node_properties(adapter_id, name, kind))
    common = {
        "fec.code": configuration["fecCode"],
    }
    if kind == ROC_RECEIVER:
        module = "libpipewire-module-roc-source"
        values = {
            **common,
            "local.ip": configuration["localAddress"],
            "local.source.port": configuration["sourcePort"],
            "local.control.port": configuration["controlPort"],
            "sess.latency.msec": configuration["latencyMs"],
            "resampler.profile": configuration["resamplerProfile"],
            "source.name": name,
        }
        if configuration["fecCode"] != "disable":
            values["local.repair.port"] = configuration["repairPort"]
        nested_name = "source.props"
    else:
        module = "libpipewire-module-roc-sink"
        values = {
            **common,
            "remote.ip": configuration["remoteAddress"],
            "remote.source.port": configuration["sourcePort"],
            "remote.control.port": configuration["controlPort"],
            "sink.name": name,
        }
        if configuration["fecCode"] != "disable":
            values["remote.repair.port"] = configuration["repairPort"]
        nested_name = "sink.props"
    fields = " ".join(f"{key} = {_spa_value(value)}" for key, value in sorted(values.items()))
    return module, f"{{ {fields} {nested_name} = {properties} }}"


def build_roc_cli_instruction(
    adapter_id: object,
    name: str,
    kind: str,
    configuration: dict[str, object],
) -> bytes:
    module, arguments = _roc_module_arguments(adapter_id, name, kind, configuration)
    return f"load-module {module} {arguments}\n".encode("utf-8")


def inspect_pcm_wav(path: Path) -> PCMWaveInfo:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise AudioAdapterDriverError("Debug source must use uncompressed PCM WAV.")
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            formats = {1: "u8", 2: "s16", 4: "s32"}
            maps = {1: "mono", 2: "stereo", 6: "surround-51", 8: "surround-71"}
            if sample_width not in formats:
                raise AudioAdapterDriverError(
                    f"Unsupported PCM sample width {sample_width * 8} bits."
                )
            if channels not in maps:
                raise AudioAdapterDriverError(
                    f"Unsupported WAV channel count {channels}; use 1, 2, 6, or 8 channels."
                )
            return PCMWaveInfo(
                rate=source.getframerate(),
                channels=channels,
                sample_width=sample_width,
                sample_format=formats[sample_width],
                channel_map=maps[channels],
                frame_count=source.getnframes(),
            )
    except (wave.Error, EOFError, OSError) as error:
        raise AudioAdapterDriverError(f"Cannot inspect PCM WAV: {error}") from error


def build_adapter_command(
    adapter_id: object,
    name: str,
    kind: str,
    configuration: dict[str, object],
    *,
    media_root: Path | None = None,
) -> tuple[list[str], PCMWaveInfo | None, Path | None]:
    if kind in {ROC_RECEIVER, ROC_SENDER}:
        return ["pw-cli", "--daemon"], None, None
    properties = pipewire_properties_document(adapter_node_properties(adapter_id, name, kind))
    path = resolve_adapter_media_path(configuration["path"], root=media_root)
    if kind == DEBUG_FILE_SOURCE:
        info = inspect_pcm_wav(path)
        return (
            [
                "pw-cat",
                "--playback",
                "--raw",
                "--target",
                "0",
                "--rate",
                str(info.rate),
                "--channels",
                str(info.channels),
                "--channel-map",
                info.channel_map,
                "--format",
                info.sample_format,
                "--properties",
                properties,
                "-",
            ],
            info,
            path,
        )
    if kind == DEBUG_FILE_RECORDER:
        return (
            [
                "pw-record",
                "--target",
                "0",
                "--rate",
                str(configuration["rate"]),
                "--channels",
                str(configuration["channels"]),
                "--channel-map",
                str(configuration["channelMap"]),
                "--format",
                str(configuration["sampleFormat"]),
                "--properties",
                properties,
                str(path),
            ],
            None,
            path,
        )
    raise AudioAdapterDriverError(f"Unsupported adapter driver kind {kind!r}.")


def loop_pcm_wav(
    path: Path,
    sink: BinaryIO,
    stop_event: threading.Event,
    progress: dict[str, int],
    *,
    chunk_frames: int = 4096,
) -> None:
    try:
        with wave.open(str(path), "rb") as source:
            while not stop_event.is_set():
                frames = source.readframes(chunk_frames)
                if not frames:
                    source.rewind()
                    progress["loops"] = progress.get("loops", 0) + 1
                    continue
                sink.write(frames)
                sink.flush()
                progress["bytes"] = progress.get("bytes", 0) + len(frames)
    except (BrokenPipeError, OSError, wave.Error) as error:
        if not stop_event.is_set():
            progress["error"] = str(error)


def _stderr_document(process) -> dict[str, object]:
    if process.poll() is None:
        return {}
    detail = ""
    stream = getattr(process, "stderr", None)
    if stream is not None:
        try:
            value = stream.read(4096)
            detail = (
                value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            )
        except (OSError, ValueError):
            detail = ""
    return {
        "code": "adapter-process-exited",
        "exitCode": process.returncode,
        "detail": detail.strip() or f"Adapter process exited with code {process.returncode}.",
    }


def stop_process_gracefully(process, timeout: float) -> bool:
    if process.poll() is not None:
        return False
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
        return True


class ManagedAdapterRuntime:
    def __init__(
        self,
        process,
        *,
        output_path: Path | None = None,
        feeder_stop: threading.Event | None = None,
        feeder: threading.Thread | None = None,
        progress: dict[str, int] | None = None,
        stop_timeout: float = 3.0,
    ) -> None:
        self.process = process
        self.output_path = output_path
        self.feeder_stop = feeder_stop
        self.feeder = feeder
        self.progress = progress if progress is not None else {}
        self.stop_timeout = stop_timeout

    def poll(self) -> AdapterProcessObservation:
        running = self.process.poll() is None
        progress: dict[str, object] = dict(self.progress)
        if self.output_path is not None and self.output_path.exists():
            progress["bytes"] = self.output_path.stat().st_size
        return AdapterProcessObservation(
            running=running,
            process_id=self.process.pid if running else None,
            exit_code=None if running else self.process.returncode,
            progress=progress,
            error={} if running else _stderr_document(self.process),
        )

    def stop(self) -> dict[str, object]:
        if self.feeder_stop is not None:
            self.feeder_stop.set()
        forced = stop_process_gracefully(self.process, self.stop_timeout)
        stream = getattr(self.process, "stdin", None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if self.feeder is not None:
            self.feeder.join(timeout=self.stop_timeout)
        return {"forced": forced, **self.poll().progress}


class AudioAdapterDriver:
    def __init__(
        self,
        *,
        media_root: Path | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        stop_timeout: float | None = None,
    ) -> None:
        self.media_root = Path(media_root or settings.AUDIO_ADAPTER_MEDIA_ROOT)
        self.popen = popen
        self.thread_factory = thread_factory
        self.stop_timeout = float(
            stop_timeout
            if stop_timeout is not None
            else settings.AUDIO_ADAPTER_LIFECYCLE["stop_timeout_seconds"]
        )

    def start(
        self,
        adapter_id: object,
        name: str,
        kind: str,
        configuration: dict[str, object],
    ) -> ManagedAdapterRuntime:
        command, _, path = build_adapter_command(
            adapter_id,
            name,
            kind,
            configuration,
            media_root=self.media_root,
        )
        if kind == DEBUG_FILE_RECORDER:
            assert path is not None
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not configuration["replaceExisting"]:
                raise AudioAdapterDriverError(
                    f"Recording {configuration['path']!r} already exists; enable replacement explicitly."
                )
        stdin = (
            subprocess.PIPE
            if kind in {ROC_RECEIVER, ROC_SENDER, DEBUG_FILE_SOURCE}
            else subprocess.DEVNULL
        )
        try:
            process = self.popen(
                command,
                stdin=stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as error:
            raise AudioAdapterDriverError(f"Cannot start {kind}: {error}") from error
        if kind in {ROC_RECEIVER, ROC_SENDER}:
            assert process.stdin is not None
            try:
                process.stdin.write(
                    build_roc_cli_instruction(adapter_id, name, kind, configuration)
                )
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                stop_process_gracefully(process, self.stop_timeout)
                raise AudioAdapterDriverError(f"Cannot configure {kind}: {error}") from error
            return ManagedAdapterRuntime(process, stop_timeout=self.stop_timeout)
        if kind != DEBUG_FILE_SOURCE:
            return ManagedAdapterRuntime(
                process,
                output_path=path if kind == DEBUG_FILE_RECORDER else None,
                stop_timeout=self.stop_timeout,
            )
        assert process.stdin is not None and path is not None
        stop_event = threading.Event()
        progress: dict[str, int] = {"bytes": 0, "loops": 0}
        feeder = self.thread_factory(
            target=loop_pcm_wav,
            args=(path, process.stdin, stop_event, progress),
            name=f"audio-adapter-{adapter_id}",
            daemon=True,
        )
        feeder.start()
        return ManagedAdapterRuntime(
            process,
            feeder_stop=stop_event,
            feeder=feeder,
            progress=progress,
            stop_timeout=self.stop_timeout,
        )
