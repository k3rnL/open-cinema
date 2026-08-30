from __future__ import annotations

import platform
from time import sleep

import pytest

from core.orchestration.node_catalogue import NodePortDefinition, NodeTypeRegistry
from core.orchestration.signal_contracts import (
    AudioContent,
    ChannelLayout,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from core.plugin_system import (
    ConfigurationMigration,
    OpenCinemaPlugin,
    PluginDesiredState,
    PluginDistributionRegistry,
    PluginHealth,
    ProcessingCapability,
    ProcessingDriverExecutor,
    ProcessingDriverFailureClassification,
    ProcessingDriverHook,
    ProcessingDriverRequest,
    ProcessingDriverResult,
    ProcessingHookContext,
    ProcessingHookRunner,
    ProcessingNodeTypeManifest,
    ProcessingPlan,
    ProcessingValidationIssue,
    RuntimePluginIdentity,
    parse_plugin_manifest,
)


def _port(name, direction):
    return NodePortDefinition(
        PortContract(
            name,
            direction,
            SignalContract(
                media_kind=MediaKind.AUDIO,
                content=AudioContent.PCM,
                rates=(48000,),
                layouts=(ChannelLayout(2, ("FL", "FR")),),
            ),
        )
    )


def _node_type(*, migrations=()):
    return ProcessingNodeTypeManifest(
        type_id="test.processing.gain",
        version=1,
        configuration_version=2,
        display_name="Test gain",
        category="processing",
        description="A deterministic test processing node.",
        ports=(
            _port("input", PortDirection.INPUT),
            _port("output", PortDirection.OUTPUT),
        ),
        configuration_schema={
            "type": "object",
            "required": ["gain"],
            "properties": {"gain": {"type": "number"}},
            "additionalProperties": True,
        },
        editable_fields=("/gain",),
        migrations=tuple(migrations),
    )


class RecordingDriver:
    def __init__(self):
        self.calls = []

    def _call(self, hook, request):
        self.calls.append((hook, request))
        return ProcessingDriverResult("ready", {"hook": hook})

    def prepare(self, request):
        return self._call("prepare", request)

    def observe(self, request):
        return self._call("observe", request)

    def activate(self, request):
        return self._call("activate", request)

    def reconfigure(self, request):
        return self._call("reconfigure", request)

    def deactivate(self, request):
        return self._call("deactivate", request)

    def cleanup(self, request):
        return self._call("cleanup", request)


def _validate(context):
    return (ProcessingValidationIssue("$.gain", "gain-warning", "Controlled warning"),)


def _plan(context):
    return ProcessingPlan(
        context.node_instance_id,
        resource_requests=({"kind": "test-dsp", "units": 1},),
        driver_intent={"gain": context.configuration["gain"]},
        explanation={"reason": "test plan"},
    )


class TestProcessingDistribution(OpenCinemaPlugin):
    __test__ = False

    def __init__(self):
        self.recording_driver = RecordingDriver()
        self.processing = ProcessingCapability(
            "test.processing.nodes",
            node_types=(_node_type(),),
            validate_hook=_validate,
            plan_hook=_plan,
            driver_factory=lambda: self.recording_driver,
        )

    @property
    def identity(self):
        return RuntimePluginIdentity("test.processing", "open-cinema-test-processing", "1.0.0")

    def capabilities(self):
        return (self.processing,)


def _manifest():
    return parse_plugin_manifest(
        {
            "schema-version": 2,
            "plugin": {
                "id": "test.processing",
                "distribution": "open-cinema-test-processing",
                "display-name": "Test processing",
                "description": "Processing integration fixture.",
                "vendor": "Tests",
                "version": "1.0.0",
                "license": "MIT",
                "source-url": "https://example.test/source",
                "documentation-url": "https://example.test/docs",
            },
            "compatibility": {
                "plugin-contract": {"minimum": 2, "maximum": 2},
                "open-cinema": ">=0.3,<1",
                "python": ">=3.12,<4",
                "operating-systems": [platform.system().lower()],
                "architectures": [platform.machine().lower()],
            },
            "capabilities": [{"id": "test.processing.nodes", "kind": "processing", "version": 1}],
            "permissions": [],
            "lifecycle": {
                "install": "application-restart",
                "enable": "hot",
                "disable": "application-restart",
                "update": "application-restart",
                "uninstall": "application-restart",
            },
        }
    )


def _context():
    return ProcessingHookContext(
        "node:test",
        {"gain": 0.5},
        2,
        {"input": "stream:test"},
        {"runtime.ready": True},
    )


def _request():
    return ProcessingDriverRequest(
        "node:test",
        "action:test:stable",
        {"gain": 0.5},
        {"resourceId": "test-dsp:0"},
    )


def test_processing_capability_registers_schema_and_preserves_metadata() -> None:
    plugin = TestProcessingDistribution()
    registry = PluginDistributionRegistry()
    record = registry.register(_manifest(), plugin)
    node_registry = NodeTypeRegistry()

    assert registry.register_node_types(node_registry) == ()
    assert node_registry.require("test.processing.gain", 1).display_name == "Test gain"
    assert registry.node_type_owner("test.processing.gain", 1) is record
    metadata = record.capabilities[0].to_document()["schemaMetadata"]["nodeTypes"][0]
    assert metadata["configurationVersion"] == 2
    assert metadata["editableFields"] == ["/gain"]


def test_disabled_processing_capability_preserves_schema_metadata_without_activation() -> None:
    registry = PluginDistributionRegistry()
    record = registry.register(_manifest(), TestProcessingDistribution())
    record.desired_state = PluginDesiredState.DISABLED
    node_registry = NodeTypeRegistry()

    assert registry.register_node_types(node_registry) == ()
    assert node_registry.get("test.processing.gain", 1) is None
    assert registry.processing_node_manifests()[0][2].type_id == "test.processing.gain"


def test_configuration_migration_preserves_opaque_fields_and_validates_result() -> None:
    migration = ConfigurationMigration(
        1,
        2,
        lambda configuration: {**configuration.to_dict(), "gain": 0.75},
    )
    manifest = _node_type(migrations=(migration,))

    migrated = manifest.migrate_configuration(
        {"legacyGain": 75, "opaqueFuture": {"keep": [1, 2, 3]}},
        from_version=1,
    )

    assert migrated["gain"] == 0.75
    assert migrated["opaqueFuture"] == {"keep": (1, 2, 3)}


def test_missing_configuration_migration_does_not_mutate_input() -> None:
    original = {"opaque": {"keep": True}}

    with pytest.raises(ValueError, match="missing configuration migration"):
        _node_type().migrate_configuration(original, from_version=1)

    assert original == {"opaque": {"keep": True}}


def test_processing_validation_and_planning_hooks_are_typed() -> None:
    capability = TestProcessingDistribution().processing

    validation = ProcessingHookRunner.validate("test.processing", capability, _context())
    planning = ProcessingHookRunner.plan("test.processing", capability, _context())

    assert validation.succeeded
    assert validation.issues[0].code == "gain-warning"
    assert planning.succeeded
    assert planning.plan.driver_intent == {"gain": 0.5}


def test_processing_hook_failure_is_isolated() -> None:
    capability = ProcessingCapability(
        "test.processing.failed",
        node_types=(_node_type(),),
        validate_hook=lambda context: (_ for _ in ()).throw(RuntimeError("failed")),
        plan_hook=lambda context: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    validation = ProcessingHookRunner.validate("test.processing", capability, _context())
    planning = ProcessingHookRunner.plan("test.processing", capability, _context())

    assert validation.diagnostic.code == "processing-plugin-validation-failed"
    assert planning.diagnostic.code == "processing-plugin-planning-failed"


@pytest.mark.parametrize("hook", tuple(ProcessingDriverHook))
def test_typed_driver_exposes_every_reconciliation_hook(hook) -> None:
    driver = RecordingDriver()
    outcome = ProcessingDriverExecutor().execute(
        plugin_id="test.processing",
        driver=driver,
        hook=hook,
        request=_request(),
        timeout_seconds=1,
    )

    assert outcome.succeeded
    assert outcome.result.facts["hook"] == hook.value


def test_driver_timeout_is_isolated_and_reports_node_context() -> None:
    class SlowDriver(RecordingDriver):
        def prepare(self, request):
            sleep(0.03)
            return super().prepare(request)

    outcome = ProcessingDriverExecutor().execute(
        plugin_id="test.processing",
        driver=SlowDriver(),
        hook="prepare",
        request=_request(),
        timeout_seconds=0.001,
    )

    assert outcome.failure is ProcessingDriverFailureClassification.TIMEOUT
    assert outcome.diagnostic.details["nodeInstanceId"] == "node:test"


def test_driver_retry_reuses_exact_idempotency_key() -> None:
    class OnceFailingDriver(RecordingDriver):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def prepare(self, request):
            self.attempts += 1
            self.calls.append(("prepare", request))
            if self.attempts == 1:
                raise RuntimeError("transient test failure")
            return ProcessingDriverResult("ready")

    driver = OnceFailingDriver()
    outcome = ProcessingDriverExecutor().execute(
        plugin_id="test.processing",
        driver=driver,
        hook="prepare",
        request=_request(),
        timeout_seconds=1,
        max_attempts=2,
    )

    assert outcome.succeeded
    assert outcome.attempt_idempotency_keys == (
        "action:test:stable",
        "action:test:stable",
    )


def test_node_schema_collision_degrades_only_processing_capability() -> None:
    registry = PluginDistributionRegistry()
    record = registry.register(_manifest(), TestProcessingDistribution())
    node_registry = NodeTypeRegistry()
    node_registry.register(_node_type().to_node_type_definition())

    diagnostics = registry.register_node_types(node_registry)

    assert diagnostics[0].code == "processing-node-schema-registration-failed"
    assert record.capabilities[0].health is PluginHealth.DEGRADED
