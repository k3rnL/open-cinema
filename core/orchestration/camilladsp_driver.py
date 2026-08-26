from __future__ import annotations

import copy
import hashlib
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from core.plugin_system.contracts import ProcessingDriverRequest, ProcessingDriverResult

from .action_planning import PhasedDriverAction, ReconciliationPhase
from .camilladsp_config import (
    CamillaDSPConfigError,
    validate_camilladsp_config_structure,
)
from .driver_actions import (
    ActionAssertionOperator,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverCommand,
)
from .graph_documents import graph_content_digest
from .signal_descriptors import AudioFormatDescriptor

CAMILLADSP_RUNTIME_OWNER = "# open-cinema-owner: camilladsp-v1"
_SAFE_INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_READY_STATES = {"running", "paused"}


class CamillaDSPDriverError(RuntimeError):
    pass


class CamillaDSPValidationError(CamillaDSPDriverError):
    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors or (message,)


def stable_camilladsp_instance_id(node_instance_id: str) -> str:
    if _SAFE_INSTANCE_ID.fullmatch(node_instance_id):
        return node_instance_id
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_instance_id).strip("-.") or "dsp"
    digest = hashlib.sha256(node_instance_id.encode()).hexdigest()[:10]
    return f"{slug[:68]}-{digest}"


def _state_name(value: object) -> str:
    if isinstance(getattr(value, "name", None), str):
        value = value.name
    elif hasattr(value, "value"):
        value = value.value
    return str(value).rsplit(".", 1)[-1].lower()


@dataclass(frozen=True, slots=True)
class CamillaDSPInstanceConfiguration:
    instance_id: str
    binary_path: str
    control_host: str
    control_port: int
    startup_timeout_seconds: float
    generated_configuration: dict[str, object]
    configuration_digest: str
    profile_digest: str
    input_descriptor: AudioFormatDescriptor
    output_descriptor: AudioFormatDescriptor
    capture_endpoint: dict[str, object]
    playback_endpoint: dict[str, object]

    @classmethod
    def from_request(
        cls,
        request: ProcessingDriverRequest,
    ) -> "CamillaDSPInstanceConfiguration":
        configuration = request.configuration.to_dict()
        planned = request.plan.to_dict().get("driverConfiguration", {})
        if planned:
            if not isinstance(planned, Mapping):
                raise CamillaDSPConfigError("plan.driverConfiguration must be an object")
            configuration.update(planned)
        instance_id = configuration.get("instanceId") or stable_camilladsp_instance_id(
            request.node_instance_id
        )
        if not isinstance(instance_id, str) or _SAFE_INSTANCE_ID.fullmatch(instance_id) is None:
            raise CamillaDSPConfigError(
                "instanceId must contain only letters, digits, '.', '_' and '-'"
            )
        binary_path = configuration.get("binaryPath", "/usr/local/bin/camilladsp")
        host = configuration.get("controlHost", "127.0.0.1")
        port = configuration.get("controlPort", 1234)
        timeout = configuration.get("startupTimeoutSeconds", 5.0)
        generated = configuration.get("generatedConfiguration")
        if not isinstance(binary_path, str) or not binary_path:
            raise CamillaDSPConfigError("binaryPath must be a non-empty string")
        if not isinstance(host, str) or not host or any(character.isspace() for character in host):
            raise CamillaDSPConfigError("controlHost must be a non-empty host token")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise CamillaDSPConfigError("controlPort must be between 1 and 65535")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise CamillaDSPConfigError("startupTimeoutSeconds must be positive")
        if not isinstance(generated, Mapping):
            raise CamillaDSPConfigError("generatedConfiguration must be an object")
        generated = copy.deepcopy(dict(generated))
        digest = graph_content_digest(generated)
        declared_digest = configuration.get("configurationDigest", digest)
        if declared_digest != digest:
            raise CamillaDSPConfigError("configurationDigest does not match generatedConfiguration")
        profile_digest = configuration.get("profileDigest")
        if not isinstance(profile_digest, str) or not profile_digest:
            raise CamillaDSPConfigError("profileDigest must be a non-empty string")
        try:
            input_descriptor = AudioFormatDescriptor.from_document(
                configuration.get("inputDescriptor")
            )
            output_descriptor = AudioFormatDescriptor.from_document(
                configuration.get("outputDescriptor")
            )
        except (TypeError, ValueError) as error:
            raise CamillaDSPConfigError(f"invalid processor descriptor: {error}") from error
        capture_endpoint = configuration.get("captureEndpoint", {})
        playback_endpoint = configuration.get("playbackEndpoint", {})
        if not isinstance(capture_endpoint, Mapping) or not isinstance(playback_endpoint, Mapping):
            raise CamillaDSPConfigError("processor endpoints must be objects")
        return cls(
            instance_id=instance_id,
            binary_path=binary_path,
            control_host=host,
            control_port=port,
            startup_timeout_seconds=float(timeout),
            generated_configuration=generated,
            configuration_digest=digest,
            profile_digest=profile_digest,
            input_descriptor=input_descriptor,
            output_descriptor=output_descriptor,
            capture_endpoint=copy.deepcopy(dict(capture_endpoint)),
            playback_endpoint=copy.deepcopy(dict(playback_endpoint)),
        )

    @property
    def material_descriptor(self) -> tuple[object, ...]:
        return (
            self.input_descriptor.rate,
            self.input_descriptor.layout,
            self.output_descriptor.rate,
            self.output_descriptor.layout,
        )


class CamillaDSPEngineValidator(Protocol):
    def validate(
        self,
        binary_path: str,
        configuration: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class CamillaDSPBinaryValidator:
    """Use the deployed CamillaDSP parser, without starting an audio stream."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_seconds: float = 10,
    ) -> None:
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def validate(
        self,
        binary_path: str,
        configuration: Mapping[str, object],
    ) -> Mapping[str, object]:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yml",
        ) as candidate:
            yaml.safe_dump(dict(configuration), candidate, sort_keys=False)
            candidate.flush()
            try:
                result = self._runner(
                    [binary_path, "--check", candidate.name],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=self._timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise CamillaDSPDriverError(
                    f"CamillaDSP validation command is unavailable: {error}"
                ) from error
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "CamillaDSP rejected config"
            raise CamillaDSPValidationError(error)
        return copy.deepcopy(dict(configuration))


class CamillaDSPControl(Protocol):
    def validate_config(self, configuration: Mapping[str, object]) -> Mapping[str, object]: ...

    def active_config(self) -> Mapping[str, object] | None: ...

    def set_active_config(self, configuration: Mapping[str, object]) -> None: ...

    def state(self) -> object: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class PyCamillaDSPControl:
    def __init__(self, host: str, port: int) -> None:
        try:
            import camilladsp
        except ImportError as error:  # pragma: no cover - deployment dependency.
            raise CamillaDSPDriverError("pycamilladsp is not installed") from error
        self._client = camilladsp.CamillaClient(host, port)
        self._client.connect()

    def validate_config(self, configuration: Mapping[str, object]) -> Mapping[str, object]:
        return self._client.config.validate(dict(configuration))

    def active_config(self) -> Mapping[str, object] | None:
        return self._client.config.active()

    def set_active_config(self, configuration: Mapping[str, object]) -> None:
        self._client.config.set_active(dict(configuration))

    def state(self) -> object:
        return self._client.general.state()

    def stop(self) -> None:
        self._client.general.stop()

    def close(self) -> None:
        self._client.disconnect()


class CamillaDSPProcessManager(Protocol):
    def start(self, instance_id: str) -> None: ...

    def stop(self, instance_id: str) -> None: ...

    def is_active(self, instance_id: str) -> bool: ...


class SystemdCamillaDSPProcessManager:
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
        return f"camilladsp@{instance_id}.service"

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
            raise CamillaDSPDriverError(
                f"systemctl {' '.join(arguments)} timed out after "
                f"{self.command_timeout_seconds:g} seconds"
            ) from error
        if check and result.returncode != 0:
            raise CamillaDSPDriverError(
                result.stderr.strip() or result.stdout.strip() or "systemctl failed"
            )
        return result

    def start(self, instance_id: str) -> None:
        self._run("start", self.unit(instance_id))

    def stop(self, instance_id: str) -> None:
        self._run("stop", self.unit(instance_id))

    def is_active(self, instance_id: str) -> bool:
        return (
            self._run("is-active", "--quiet", self.unit(instance_id), check=False).returncode == 0
        )


def _atomic_owned_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if path.exists() and not path.read_text(encoding="utf-8").startswith(CAMILLADSP_RUNTIME_OWNER):
        raise CamillaDSPDriverError(f"refusing to overwrite unowned runtime file {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _owned(path: Path) -> bool:
    return path.exists() and path.read_text(encoding="utf-8").startswith(CAMILLADSP_RUNTIME_OWNER)


class CamillaDSPDriver:
    def __init__(
        self,
        process_manager: CamillaDSPProcessManager,
        *,
        runtime_directory: Path = Path("/run/open-cinema/camilladsp"),
        engine_validator: CamillaDSPEngineValidator | None = None,
        control_factory: (
            Callable[[CamillaDSPInstanceConfiguration], CamillaDSPControl] | None
        ) = None,
    ) -> None:
        self._manager = process_manager
        self._runtime = Path(runtime_directory)
        self._validator = engine_validator or CamillaDSPBinaryValidator()
        self._control_factory = control_factory or (
            lambda instance: PyCamillaDSPControl(
                instance.control_host,
                instance.control_port,
            )
        )
        self._controls: dict[str, CamillaDSPControl] = {}
        self._last_failures: dict[str, str] = {}

    def _paths(self, instance_id: str) -> tuple[Path, Path]:
        return (
            self._runtime / f"{instance_id}.yml",
            self._runtime / f"{instance_id}.env",
        )

    def _control(self, instance: CamillaDSPInstanceConfiguration) -> CamillaDSPControl:
        control = self._controls.get(instance.instance_id)
        if control is None:
            control = self._control_factory(instance)
            self._controls[instance.instance_id] = control
        return control

    def _drop_control(self, instance_id: str) -> None:
        control = self._controls.pop(instance_id, None)
        if control is not None:
            try:
                control.close()
            except Exception:
                pass

    def _validate(
        self,
        instance: CamillaDSPInstanceConfiguration,
    ) -> Mapping[str, object]:
        structural = validate_camilladsp_config_structure(instance.generated_configuration)
        if not structural.valid:
            raise CamillaDSPValidationError(
                "generated CamillaDSP configuration is structurally invalid",
                errors=structural.errors,
            )
        return self._validator.validate(
            instance.binary_path,
            instance.generated_configuration,
        )

    def _write_instance(
        self,
        instance: CamillaDSPInstanceConfiguration,
        configuration: Mapping[str, object] | None = None,
    ) -> None:
        config_path, environment_path = self._paths(instance.instance_id)
        for path in (config_path, environment_path):
            if path.exists() and not _owned(path):
                raise CamillaDSPDriverError(f"refusing to overwrite unowned runtime file {path}")
        document = dict(configuration or instance.generated_configuration)
        config_text = (
            CAMILLADSP_RUNTIME_OWNER
            + "\n"
            + yaml.safe_dump(
                document,
                sort_keys=False,
            )
        )
        environment_text = "\n".join(
            (
                CAMILLADSP_RUNTIME_OWNER,
                f"CAMILLADSP_CONFIG={config_path}",
                f"CAMILLADSP_ADDRESS={instance.control_host}",
                f"CAMILLADSP_PORT={instance.control_port}",
                "",
            )
        )
        _atomic_owned_write(config_path, config_text)
        _atomic_owned_write(environment_path, environment_text)

    def _facts(
        self,
        instance: CamillaDSPInstanceConfiguration,
        *,
        connection: str,
        engine_state: str,
        active_digest: str | None,
        readiness: bool,
        warnings: tuple[str, ...] = (),
        last_failure: str | None = None,
    ) -> dict[str, object]:
        return {
            "connection": connection,
            "engineState": engine_state,
            "activeConfigurationDigest": active_digest,
            "requestedConfigurationDigest": instance.configuration_digest,
            "profileDigest": instance.profile_digest,
            "inputDescriptor": instance.input_descriptor.to_document(),
            "outputDescriptor": instance.output_descriptor.to_document(),
            "streams": {
                "capture": copy.deepcopy(instance.capture_endpoint),
                "playback": copy.deepcopy(instance.playback_endpoint),
            },
            "validation": "valid",
            "warnings": list(warnings),
            "readiness": readiness,
            "lastFailure": last_failure,
        }

    def _invalid_result(self, error: Exception) -> ProcessingDriverResult:
        errors = getattr(error, "errors", (str(error),))
        return ProcessingDriverResult(
            "invalid",
            facts={"readiness": False, "validation": "invalid"},
            details={"errors": list(errors)},
        )

    def _unavailable_result(self, error: Exception) -> ProcessingDriverResult:
        status = "ownership-refused" if "unowned runtime file" in str(error) else "unavailable"
        return ProcessingDriverResult(
            status,
            facts={"readiness": False, "validation": "unknown"},
            details={"error": str(error)},
        )

    @staticmethod
    def _normalized_digest(
        control: CamillaDSPControl,
        configuration: Mapping[str, object],
    ) -> str:
        normalized = control.validate_config(configuration)
        if not isinstance(normalized, Mapping):
            raise CamillaDSPDriverError("CamillaDSP validation returned no configuration")
        return graph_content_digest(normalized)

    @staticmethod
    def _material_config_changed(
        previous: Mapping[str, object] | None,
        candidate: Mapping[str, object],
    ) -> bool:
        def signature(configuration):
            if not isinstance(configuration, Mapping):
                return None
            devices = configuration.get("devices")
            if not isinstance(devices, Mapping):
                return None
            capture = devices.get("capture")
            playback = devices.get("playback")
            return (
                devices.get("samplerate"),
                devices.get("capture_samplerate", devices.get("samplerate")),
                capture.get("channels") if isinstance(capture, Mapping) else None,
                playback.get("channels") if isinstance(playback, Mapping) else None,
            )

        return signature(previous) != signature(candidate)

    def prepare(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        try:
            instance = CamillaDSPInstanceConfiguration.from_request(request)
            self._validate(instance)
            config_path, environment_path = self._paths(instance.instance_id)
            same = False
            if _owned(config_path) and _owned(environment_path):
                current = yaml.safe_load(config_path.read_text(encoding="utf-8").split("\n", 1)[1])
                same = graph_content_digest(current) == instance.configuration_digest
            if same:
                status = "already-prepared"
            else:
                self._write_instance(instance)
                status = "prepared"
            return ProcessingDriverResult(
                status,
                facts={
                    "readiness": False,
                    "validation": "valid",
                    "requestedConfigurationDigest": instance.configuration_digest,
                    "profileDigest": instance.profile_digest,
                },
                details={
                    "configPath": str(config_path),
                    "environmentPath": str(environment_path),
                },
            )
        except (CamillaDSPConfigError, CamillaDSPValidationError) as error:
            return self._invalid_result(error)
        except (CamillaDSPDriverError, OSError) as error:
            return self._unavailable_result(error)

    def _wait_ready(
        self,
        instance: CamillaDSPInstanceConfiguration,
        control: CamillaDSPControl,
    ) -> str:
        deadline = time.monotonic() + instance.startup_timeout_seconds
        state = "unknown"
        while time.monotonic() < deadline:
            state = _state_name(control.state())
            if state in _READY_STATES:
                return state
            if state in {"inactive", "stalled"}:
                break
            time.sleep(0.02)
        raise CamillaDSPDriverError(f"CamillaDSP did not become ready (state={state})")

    def _wait_inactive(
        self,
        instance: CamillaDSPInstanceConfiguration,
        control: CamillaDSPControl,
    ) -> None:
        deadline = time.monotonic() + instance.startup_timeout_seconds
        state = "unknown"
        while time.monotonic() < deadline:
            state = _state_name(control.state())
            if state == "inactive":
                return
            time.sleep(0.02)
        raise CamillaDSPDriverError(
            f"CamillaDSP did not stop before material reconfiguration (state={state})"
        )

    def activate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        prepared = self.prepare(request)
        if prepared.status not in {"prepared", "already-prepared"}:
            return prepared
        instance = CamillaDSPInstanceConfiguration.from_request(request)
        runtime_resources_recreated = False
        try:
            if not self._manager.is_active(instance.instance_id):
                self._manager.start(instance.instance_id)
            control = self._control(instance)
            expected_digest = self._normalized_digest(
                control,
                instance.generated_configuration,
            )
            active = control.active_config()
            active_digest = self._normalized_digest(control, active) if active is not None else None
            if active_digest != expected_digest:
                runtime_resources_recreated = self._material_config_changed(
                    active,
                    instance.generated_configuration,
                )
                if runtime_resources_recreated and active is not None:
                    # A live PipeWire channel-layout change otherwise leaves the
                    # old CamillaDSP nodes eligible while its processing threads
                    # drain.  Stop the old graph first so SetConfig creates one
                    # unambiguous replacement resource set.
                    control.stop()
                    self._wait_inactive(instance, control)
                control.set_active_config(instance.generated_configuration)
                status = "active"
            else:
                status = "already-active"
            state = self._wait_ready(instance, control)
            active = control.active_config()
            if active is None or self._normalized_digest(control, active) != expected_digest:
                raise CamillaDSPDriverError(
                    "CamillaDSP active configuration failed post-activation verification"
                )
            self._last_failures.pop(instance.instance_id, None)
            return ProcessingDriverResult(
                status,
                facts=self._facts(
                    instance,
                    connection="connected",
                    engine_state=state,
                    active_digest=instance.configuration_digest,
                    readiness=True,
                ),
                details={"runtimeResourcesRecreated": runtime_resources_recreated},
            )
        except Exception as error:
            self._last_failures[instance.instance_id] = str(error)
            self._drop_control(instance.instance_id)
            return ProcessingDriverResult(
                "unhealthy",
                facts=self._facts(
                    instance,
                    connection="disconnected",
                    engine_state="unknown",
                    active_digest=None,
                    readiness=False,
                    last_failure=str(error),
                ),
                details={
                    "error": str(error),
                    "runtimeResourcesRecreated": runtime_resources_recreated,
                },
            )

    def observe(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        try:
            instance = CamillaDSPInstanceConfiguration.from_request(request)
        except CamillaDSPConfigError as error:
            return self._invalid_result(error)
        if not self._manager.is_active(instance.instance_id):
            self._drop_control(instance.instance_id)
            failure = self._last_failures.get(instance.instance_id, "process is inactive")
            return ProcessingDriverResult(
                "unhealthy",
                facts=self._facts(
                    instance,
                    connection="disconnected",
                    engine_state="inactive",
                    active_digest=None,
                    readiness=False,
                    last_failure=failure,
                ),
            )
        try:
            control = self._control(instance)
            state = _state_name(control.state())
            active = control.active_config()
            expected_digest = self._normalized_digest(
                control,
                instance.generated_configuration,
            )
            observed_digest = (
                self._normalized_digest(control, active) if active is not None else None
            )
            matches = observed_digest == expected_digest
            active_digest = (
                instance.configuration_digest
                if matches
                else (graph_content_digest(active) if active is not None else None)
            )
            warnings = ()
            if not matches:
                warnings = ("active-configuration-drift",)
            ready = state in _READY_STATES and matches
            return ProcessingDriverResult(
                "healthy" if ready else "degraded",
                facts=self._facts(
                    instance,
                    connection="connected",
                    engine_state=state,
                    active_digest=active_digest,
                    readiness=ready,
                    warnings=warnings,
                    last_failure=self._last_failures.get(instance.instance_id),
                ),
            )
        except Exception as error:
            self._last_failures[instance.instance_id] = str(error)
            self._drop_control(instance.instance_id)
            return ProcessingDriverResult(
                "unhealthy",
                facts=self._facts(
                    instance,
                    connection="disconnected",
                    engine_state="unknown",
                    active_digest=None,
                    readiness=False,
                    last_failure=str(error),
                ),
            )

    def reconfigure(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        try:
            instance = CamillaDSPInstanceConfiguration.from_request(request)
            self._validate(instance)
        except (CamillaDSPConfigError, CamillaDSPValidationError) as error:
            return self._invalid_result(error)
        except (CamillaDSPDriverError, OSError) as error:
            return self._unavailable_result(error)
        if not self._manager.is_active(instance.instance_id):
            return self.activate(request)
        control = None
        previous = None
        previous_digest = None
        try:
            control = self._control(instance)
            previous = control.active_config()
            previous_digest = graph_content_digest(previous) if previous is not None else None
            expected_digest = self._normalized_digest(
                control,
                instance.generated_configuration,
            )
            observed_digest = (
                self._normalized_digest(control, previous) if previous is not None else None
            )
            if observed_digest == expected_digest:
                return self.activate(request)
            plan = request.plan.to_dict()
            transition = plan.get("transitionContext", {})
            material_change = bool(plan.get("materialFormatChange", False)) or (
                self._material_config_changed(
                    previous,
                    instance.generated_configuration,
                )
            )
            if material_change and (
                not isinstance(transition, Mapping)
                or transition.get("outputSuppressed") is not True
            ):
                return ProcessingDriverResult(
                    "suppression-required",
                    facts={"readiness": False, "validation": "valid"},
                    details={"reason": "format or layout changes require suppression"},
                )
            self._normalized_digest(control, instance.generated_configuration)
            self._write_instance(instance)
            control.set_active_config(instance.generated_configuration)
            state = self._wait_ready(instance, control)
            active = control.active_config()
            if active is None or self._normalized_digest(control, active) != expected_digest:
                raise CamillaDSPDriverError(
                    "CamillaDSP active configuration failed post-reconfigure verification"
                )
            self._last_failures.pop(instance.instance_id, None)
            return ProcessingDriverResult(
                "reconfigured",
                facts=self._facts(
                    instance,
                    connection="connected",
                    engine_state=state,
                    active_digest=instance.configuration_digest,
                    readiness=True,
                ),
            )
        except Exception as error:
            rollback_error = None
            try:
                if previous is not None and control is not None:
                    control.set_active_config(previous)
                    self._write_instance(instance, previous)
                    self._wait_ready(instance, control)
            except Exception as caught:
                rollback_error = str(caught)
            failure = str(error)
            self._last_failures[instance.instance_id] = failure
            return ProcessingDriverResult(
                "rolled-back" if rollback_error is None else "rollback-failed",
                facts=self._facts(
                    instance,
                    connection="connected",
                    engine_state="running" if rollback_error is None else "unknown",
                    active_digest=previous_digest if rollback_error is None else None,
                    readiness=False,
                    last_failure=failure,
                ),
                details={"error": failure, "rollbackError": rollback_error},
            )

    def deactivate(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        try:
            instance = CamillaDSPInstanceConfiguration.from_request(request)
        except CamillaDSPConfigError as error:
            return self._invalid_result(error)
        if not self._manager.is_active(instance.instance_id):
            self._drop_control(instance.instance_id)
            return ProcessingDriverResult("already-inactive", facts={"readiness": False})
        control = self._controls.get(instance.instance_id)
        if control is not None:
            try:
                control.stop()
            except Exception:
                pass
        self._manager.stop(instance.instance_id)
        self._drop_control(instance.instance_id)
        return ProcessingDriverResult("inactive", facts={"readiness": False})

    def cleanup(self, request: ProcessingDriverRequest) -> ProcessingDriverResult:
        try:
            instance = CamillaDSPInstanceConfiguration.from_request(request)
        except CamillaDSPConfigError as error:
            return self._invalid_result(error)
        paths = self._paths(instance.instance_id)
        unowned = [str(path) for path in paths if path.exists() and not _owned(path)]
        if unowned:
            return ProcessingDriverResult(
                "ownership-refused",
                facts={"readiness": False},
                details={"unownedPaths": unowned},
            )
        if self._manager.is_active(instance.instance_id):
            self._manager.stop(instance.instance_id)
        self._drop_control(instance.instance_id)
        for path in paths:
            if _owned(path):
                path.unlink()
        return ProcessingDriverResult("clean", facts={"readiness": False})


def plan_camilladsp_transition(
    *,
    instance_id: str,
    intent_scope: str,
    configuration_digest: str,
    output_target: str,
    material_format_change: bool,
) -> tuple[PhasedDriverAction, ...]:
    """Build the processor's ordered contribution to reconciliation."""

    def action(
        phase: ReconciliationPhase,
        operation: str,
        expected_subject: str,
        expected: object,
    ) -> PhasedDriverAction:
        identity = DriverActionIdentity(
            "camilladsp",
            "processor-instance",
            instance_id,
            operation,
        )
        command = DriverCommand(
            operation,
            {
                "instanceId": instance_id,
                "configurationDigest": configuration_digest,
                "outputTarget": output_target,
            },
        )
        return PhasedDriverAction(
            phase,
            DriverAction.create(
                identity=identity,
                command=command,
                intent_scope=intent_scope,
                timeout_seconds=10,
                verification=(
                    ActionVerification(
                        expected_subject,
                        ActionAssertionOperator.EQUALS,
                        expected,
                    ),
                ),
                recovery=ActionRecoveryPolicy(
                    ActionRecoveryMode.NONE_REQUIRED,
                    "The transition coordinator owns rollback to the previous plan.",
                ),
                metadata={"materialFormatChange": material_format_change},
            ),
        )

    planned = [
        action(
            ReconciliationPhase.PREPARE,
            "prepare",
            f"processor.{instance_id}.validation",
            "valid",
        )
    ]
    if material_format_change:
        planned.append(
            action(
                ReconciliationPhase.SUPPRESS,
                "suppress",
                f"processor.{instance_id}.outputSuppressed",
                True,
            )
        )
    planned.extend(
        (
            action(
                ReconciliationPhase.CONFIGURE,
                "reconfigure",
                f"processor.{instance_id}.activeConfigurationDigest",
                configuration_digest,
            ),
            action(
                ReconciliationPhase.ROUTE,
                "route",
                f"processor.{instance_id}.outputTarget",
                output_target,
            ),
            action(
                ReconciliationPhase.VERIFY,
                "verify",
                f"processor.{instance_id}.readiness",
                True,
            ),
        )
    )
    if material_format_change:
        planned.append(
            action(
                ReconciliationPhase.UNSUPPRESS,
                "unsuppress",
                f"processor.{instance_id}.outputSuppressed",
                False,
            )
        )
    return tuple(planned)
