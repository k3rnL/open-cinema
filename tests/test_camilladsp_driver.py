from __future__ import annotations

import copy
import stat
import subprocess
from enum import Enum, auto
from pathlib import Path

import pytest
import yaml
from wyreplumber.runtime import FrozenDict

from core.orchestration.action_planning import ReconciliationPhase
from core.orchestration.camilladsp_driver import (
    CAMILLADSP_RUNTIME_OWNER,
    CamillaDSPBinaryValidator,
    CamillaDSPDriver,
    CamillaDSPDriverError,
    CamillaDSPValidationError,
    SystemdCamillaDSPProcessManager,
    _state_name,
    plan_camilladsp_transition,
)
from core.orchestration.graph_documents import graph_content_digest
from core.plugin_system.contracts import ProcessingDriverRequest


def concrete_configuration(*, channels: int = 2, gain: float = -3.0) -> dict:
    return {
        "title": "Managed test",
        "devices": {
            "samplerate": 48000,
            "chunksize": 1024,
            "capture": {
                "type": "PipeWire",
                "channels": channels,
                "node_name": "opencinema.camilladsp.0.capture",
                "node_description": "Open Cinema CamillaDSP 0 Capture",
                "node_group_name": "opencinema.camilladsp.0.group",
                "autoconnect_to": None,
            },
            "playback": {
                "type": "PipeWire",
                "channels": channels,
                "node_name": "opencinema.camilladsp.0.playback",
                "node_description": "Open Cinema CamillaDSP 0 Playback",
                "node_group_name": "opencinema.camilladsp.0.group",
                "autoconnect_to": None,
            },
        },
        "filters": {"gain": {"type": "Gain", "parameters": {"gain": gain}}},
        "pipeline": [{"type": "Filter", "channels": list(range(channels)), "names": ["gain"]}],
    }


def request(
    *,
    configuration: dict | None = None,
    suppressed: bool = False,
    material_change: bool = True,
) -> ProcessingDriverRequest:
    generated = configuration or concrete_configuration()
    channels = generated["devices"]["playback"]["channels"]
    positions = ["FL", "FR"] if channels == 2 else ["FL", "FR", "FC", "LFE", "SL", "SR"]
    descriptor = {
        "sampleFormat": "FLOAT32LE",
        "rate": 48000,
        "layout": {"channels": channels, "positions": positions},
    }
    return ProcessingDriverRequest(
        "room dsp",
        f"dsp:{graph_content_digest(generated)}",
        FrozenDict(
            {
                "instanceId": "room",
                "controlPort": 1234,
                "generatedConfiguration": generated,
                "configurationDigest": graph_content_digest(generated),
                "profileDigest": "a" * 64,
                "inputDescriptor": descriptor,
                "outputDescriptor": descriptor,
                "captureEndpoint": {
                    "backend": "PipeWire",
                    "nodeName": "opencinema.camilladsp.0.capture",
                    "nodeGroupName": "opencinema.camilladsp.0.group",
                },
                "playbackEndpoint": {
                    "backend": "PipeWire",
                    "nodeName": "opencinema.camilladsp.0.playback",
                    "nodeGroupName": "opencinema.camilladsp.0.group",
                },
                "startupTimeoutSeconds": 0.2,
            }
        ),
        FrozenDict(
            {
                "materialFormatChange": material_change,
                "transitionContext": {"outputSuppressed": suppressed},
            }
        ),
    )


class FakeValidator:
    def __init__(self) -> None:
        self.configurations = []
        self.reject = False

    def validate(self, binary_path, configuration):
        del binary_path
        self.configurations.append(copy.deepcopy(configuration))
        if self.reject:
            raise CamillaDSPValidationError("engine rejected config")
        return copy.deepcopy(configuration)


class FakeManager:
    def __init__(self) -> None:
        self.active = False
        self.starts = 0
        self.stops = 0

    def start(self, instance_id):
        assert instance_id == "room"
        self.active = True
        self.starts += 1

    def stop(self, instance_id):
        assert instance_id == "room"
        self.active = False
        self.stops += 1

    def is_active(self, instance_id):
        assert instance_id == "room"
        return self.active


class FakeControl:
    def __init__(self) -> None:
        self.current = None
        self.engine_state = "Running"
        self.fail_next_set = False
        self.disconnected = False
        self.validated = []
        self.stop_calls = 0

    def validate_config(self, configuration):
        self.validated.append(copy.deepcopy(configuration))
        return copy.deepcopy(configuration)

    def active_config(self):
        if self.disconnected:
            raise ConnectionError("websocket disconnected")
        return copy.deepcopy(self.current)

    def set_active_config(self, configuration):
        if self.fail_next_set:
            self.fail_next_set = False
            raise RuntimeError("apply failed")
        self.current = copy.deepcopy(configuration)
        self.engine_state = "Running"

    def state(self):
        if self.disconnected:
            raise ConnectionError("websocket disconnected")
        return self.engine_state

    def stop(self):
        self.stop_calls += 1
        self.engine_state = "Inactive"

    def close(self):
        return None


class DefaultFillingControl(FakeControl):
    def validate_config(self, configuration):
        normalized = copy.deepcopy(configuration)
        normalized["devices"].setdefault("volume_limit", 50.0)
        return normalized


def test_binary_validator_uses_camilladsp_check_mode() -> None:
    commands = []

    def runner(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "valid", "")

    validator = CamillaDSPBinaryValidator(runner=runner)

    validated = validator.validate("/usr/local/bin/camilladsp", concrete_configuration())

    assert validated == concrete_configuration()
    assert commands[0][0][0:2] == ["/usr/local/bin/camilladsp", "--check"]
    assert commands[0][1]["timeout"] == 10


def test_systemd_camilladsp_commands_are_bounded() -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = SystemdCamillaDSPProcessManager(
        runner=runner,
        command_timeout_seconds=3,
    )
    manager.start("room")

    assert calls[0][1]["timeout"] == 3


def test_systemd_camilladsp_timeout_is_actionable() -> None:
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    manager = SystemdCamillaDSPProcessManager(runner=runner)

    with pytest.raises(CamillaDSPDriverError, match="timed out after 5 seconds"):
        manager.stop("room")


def test_pycamilladsp_enum_state_uses_its_name_instead_of_numeric_value() -> None:
    class ProcessingState(Enum):
        RUNNING = auto()
        STALLED = auto()

    assert _state_name(ProcessingState.RUNNING) == "running"
    assert _state_name(ProcessingState.STALLED) == "stalled"


def test_driver_lifecycle_is_idempotent_and_exposes_processor_facts(tmp_path: Path) -> None:
    manager = FakeManager()
    validator = FakeValidator()
    control = FakeControl()
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=validator,
        control_factory=lambda instance: control,
    )

    assert driver.prepare(request()).status == "prepared"
    assert driver.prepare(request()).status == "already-prepared"
    config_path = tmp_path / "room.yml"
    env_path = tmp_path / "room.env"
    assert config_path.read_text().startswith(CAMILLADSP_RUNTIME_OWNER)
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600

    assert driver.activate(request()).status == "active"
    assert driver.activate(request()).status == "already-active"
    observed = driver.observe(request())
    facts = observed.facts.to_dict()
    assert observed.status == "healthy"
    assert facts["connection"] == "connected"
    assert facts["engineState"] == "running"
    assert facts["activeConfigurationDigest"] == graph_content_digest(concrete_configuration())
    assert facts["inputDescriptor"]["layout"]["channels"] == 2
    assert facts["streams"]["playback"]["nodeName"].endswith("playback")
    assert facts["warnings"] == []
    assert facts["readiness"] is True
    assert facts["lastFailure"] is None
    assert manager.starts == 1

    assert driver.deactivate(request()).status == "inactive"
    assert driver.cleanup(request()).status == "clean"
    assert not config_path.exists()
    assert not env_path.exists()


def test_invalid_configuration_is_blocked_before_runtime_files(tmp_path: Path) -> None:
    manager = FakeManager()
    validator = FakeValidator()
    validator.reject = True
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=validator,
        control_factory=lambda instance: FakeControl(),
    )

    result = driver.prepare(request())

    assert result.status == "invalid"
    assert result.facts["validation"] == "invalid"
    assert not (tmp_path / "room.yml").exists()
    assert not manager.active


def test_normalized_camilladsp_defaults_do_not_look_like_runtime_drift(
    tmp_path: Path,
) -> None:
    manager = FakeManager()
    control = DefaultFillingControl()
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: control,
    )

    assert driver.activate(request()).status == "active"
    assert driver.observe(request()).status == "healthy"


def test_material_activation_stops_old_graph_and_reports_runtime_replacement(
    tmp_path: Path,
) -> None:
    manager = FakeManager()
    control = FakeControl()
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: control,
    )
    assert driver.activate(request()).status == "active"

    changed = concrete_configuration(channels=6)
    result = driver.activate(request(configuration=changed))

    assert result.status == "active"
    assert result.details["runtimeResourcesRecreated"] is True
    assert control.stop_calls == 1
    assert control.engine_state == "Running"


def test_stalled_material_activation_still_reports_runtime_replacement(
    tmp_path: Path,
) -> None:
    class StalledAfterSetControl(FakeControl):
        def set_active_config(self, configuration):
            super().set_active_config(configuration)
            self.engine_state = "Stalled"

    manager = FakeManager()
    control = StalledAfterSetControl()
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: control,
    )
    control.current = concrete_configuration()
    manager.active = True

    changed = concrete_configuration(channels=6)
    result = driver.activate(request(configuration=changed))

    assert result.status == "unhealthy"
    assert result.details["runtimeResourcesRecreated"] is True
    assert control.stop_calls == 1


def test_prepare_refuses_all_files_before_partially_overwriting_unowned_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "room.env").write_text("USER_OWNED=yes\n")
    driver = CamillaDSPDriver(
        FakeManager(),
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: FakeControl(),
    )

    result = driver.prepare(request())

    assert result.status == "ownership-refused"
    assert not (tmp_path / "room.yml").exists()
    assert (tmp_path / "room.env").read_text() == "USER_OWNED=yes\n"


def test_reconfigure_requires_suppression_and_rolls_back_failure(tmp_path: Path) -> None:
    manager = FakeManager()
    control = FakeControl()
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: control,
    )
    original = request()
    assert driver.activate(original).status == "active"

    candidate_config = concrete_configuration(gain=-8)
    candidate = request(configuration=candidate_config)
    assert driver.reconfigure(candidate).status == "suppression-required"

    control.fail_next_set = True
    failed = driver.reconfigure(request(configuration=candidate_config, suppressed=True))

    assert failed.status == "rolled-back"
    assert graph_content_digest(control.current) == graph_content_digest(concrete_configuration())
    persisted = (tmp_path / "room.yml").read_text().split("\n", 1)[1]
    assert graph_content_digest(yaml.safe_load(persisted)) == graph_content_digest(
        concrete_configuration()
    )


def test_control_disconnect_and_process_restart_reconnect_cleanly(tmp_path: Path) -> None:
    manager = FakeManager()
    controls = [FakeControl(), FakeControl(), FakeControl()]
    created = []

    def factory(instance):
        del instance
        control = controls[len(created)]
        created.append(control)
        return control

    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=factory,
    )
    assert driver.activate(request()).status == "active"
    controls[0].disconnected = True
    assert driver.observe(request()).status == "unhealthy"
    controls[1].current = concrete_configuration()
    assert driver.observe(request()).status == "healthy"

    manager.active = False
    assert driver.observe(request()).status == "unhealthy"
    manager.active = True
    controls[2].current = concrete_configuration()
    assert driver.observe(request()).status == "healthy"
    assert len(created) == 3


def test_cleanup_refuses_unowned_runtime_files_without_stopping_instance(tmp_path: Path) -> None:
    manager = FakeManager()
    manager.active = True
    (tmp_path / "room.yml").write_text("title: user-owned\n")
    driver = CamillaDSPDriver(
        manager,
        runtime_directory=tmp_path,
        engine_validator=FakeValidator(),
        control_factory=lambda instance: FakeControl(),
    )

    result = driver.cleanup(request())

    assert result.status == "ownership-refused"
    assert manager.stops == 0
    assert (tmp_path / "room.yml").exists()


def test_transition_contribution_orders_safe_format_change_phases() -> None:
    actions = plan_camilladsp_transition(
        instance_id="room",
        intent_scope="plan:7",
        configuration_digest="b" * 64,
        output_target="headset",
        material_format_change=True,
    )

    assert tuple(item.phase for item in actions) == (
        ReconciliationPhase.PREPARE,
        ReconciliationPhase.SUPPRESS,
        ReconciliationPhase.CONFIGURE,
        ReconciliationPhase.ROUTE,
        ReconciliationPhase.VERIFY,
        ReconciliationPhase.UNSUPPRESS,
    )
    assert actions[2].action.metadata["materialFormatChange"] is True
