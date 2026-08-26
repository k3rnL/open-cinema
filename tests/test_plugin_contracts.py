from __future__ import annotations

from collections import defaultdict
from time import sleep

import pytest

from core.orchestration.node_catalogue import (
    NodePortDefinition,
    NodeTypeRegistry,
)
from core.orchestration.signal_contracts import (
    AudioContent,
    ChannelLayout,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from core.plugin_system import (
    APPLICATION_PLUGIN_ENTRY_POINT,
    PROCESSING_PLUGIN_ENTRY_POINT,
    ApplicationLifecycleContext,
    ApplicationPlugin,
    ApplicationPluginManifest,
    ConfigurationMigration,
    DuplicatePluginIdError,
    PluginCompatibility,
    PluginHealth,
    PluginLifecycleState,
    PluginRegistry,
    ProcessingDriverExecutor,
    ProcessingDriverFailureClassification,
    ProcessingDriverHook,
    ProcessingDriverRequest,
    ProcessingDriverResult,
    ProcessingHookContext,
    ProcessingHookRunner,
    ProcessingNodeTypeManifest,
    ProcessingPlan,
    ProcessingPlugin,
    ProcessingPluginManifest,
    ProcessingValidationIssue,
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


def _node_type(*, type_id="plugin.test-processing.gain", migrations=()):
    return ProcessingNodeTypeManifest(
        type_id=type_id,
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


class TestProcessingPlugin(ProcessingPlugin):
    __test__ = False

    def __init__(self, *, plugin_id="test-processing", compatibility=None, fail=None):
        self.plugin_id = plugin_id
        self.compatibility = compatibility or PluginCompatibility()
        self.fail = fail
        self.recording_driver = RecordingDriver()

    @property
    def manifest(self):
        return ProcessingPluginManifest(
            self.plugin_id,
            "Test processing",
            "1.2.3",
            "Processing contract test plugin.",
            self.compatibility,
        )

    def node_types(self):
        return (_node_type(type_id=f"plugin.{self.plugin_id}.gain"),)

    def validate(self, context):
        if self.fail == "validate":
            raise RuntimeError("validation exploded")
        return (ProcessingValidationIssue("$.gain", "gain-warning", "Controlled warning"),)

    def plan(self, context):
        if self.fail == "plan":
            raise RuntimeError("planning exploded")
        return ProcessingPlan(
            context.node_instance_id,
            resource_requests=({"kind": "test-dsp", "units": 1},),
            driver_intent={"gain": context.configuration["gain"]},
            explanation={"reason": "test plan"},
        )

    def driver(self):
        return self.recording_driver


class TestApplicationPlugin(ApplicationPlugin):
    __test__ = False

    def __init__(self, plugin_id="test-app", *, fail_start=False):
        self.plugin_id = plugin_id
        self.fail_start = fail_start
        self.lifecycle = []

    @property
    def manifest(self):
        return ApplicationPluginManifest(
            self.plugin_id,
            "Test application",
            "1.0.0",
            "Application contract test plugin.",
            route_namespace=self.plugin_id,
            model_packages=(f"plugin.{self.plugin_id}.models",),
            automation_ids=(f"{self.plugin_id}.tick",),
        )

    def get_urls(self):
        return ("status",)

    def automation_hooks(self):
        return {f"{self.plugin_id}.tick": lambda: "tick"}

    def start(self, context):
        self.lifecycle.append(("start", context.settings.to_dict()))
        if self.fail_start:
            raise RuntimeError("start exploded")

    def stop(self, context):
        self.lifecycle.append(("stop", context.settings.to_dict()))


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


def test_explicit_manifests_registry_lifecycle_and_entry_point_groups() -> None:
    registry = PluginRegistry()
    application = TestApplicationPlugin()
    processing = TestProcessingPlugin()

    app_record = registry.register_application(application)
    processing_record = registry.register_processing(processing)
    registry.start_applications(ApplicationLifecycleContext({"mode": "test"}))

    assert app_record.state is PluginLifecycleState.STARTED
    assert app_record.health is PluginHealth.HEALTHY
    assert processing_record.state is PluginLifecycleState.AVAILABLE
    assert application.lifecycle == [("start", {"mode": "test"})]
    assert application.automation_hooks()["test-app.tick"]() == "tick"
    catalogue = registry.catalogue_document()
    assert catalogue["entryPointGroups"] == {
        "application": APPLICATION_PLUGIN_ENTRY_POINT,
        "processing": PROCESSING_PLUGIN_ENTRY_POINT,
    }

    registry.stop_applications(ApplicationLifecycleContext({"mode": "test"}))
    assert app_record.state is PluginLifecycleState.STOPPED
    assert application.lifecycle[-1][0] == "stop"


def test_processing_node_schema_exposes_editable_fields_ports_and_signal_constraints() -> None:
    manifest = _node_type()
    document = manifest.to_document()

    assert document["configurationVersion"] == 2
    assert document["editableFields"] == ["/gain"]
    assert document["ports"][0]["direction"] == "input"
    assert document["ports"][0]["contract"] == {
        "mediaKind": "audio",
        "content": "pcm",
        "rates": [48000],
        "layouts": [{"channels": 2, "positions": ["FL", "FR"]}],
    }
    registry = PluginRegistry()
    registry.register_processing(TestProcessingPlugin())
    node_registry = NodeTypeRegistry()
    assert registry.register_node_types(node_registry) == ()
    assert node_registry.require("plugin.test-processing.gain", 1).display_name == "Test gain"


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


def test_missing_or_invalid_configuration_migration_fails_without_mutating_input() -> None:
    original = {"opaque": {"keep": True}}
    manifest = _node_type()

    with pytest.raises(ValueError, match="missing configuration migration"):
        manifest.migrate_configuration(original, from_version=1)

    assert original == {"opaque": {"keep": True}}


def test_validation_and_planning_hooks_are_typed_and_failure_isolated() -> None:
    healthy = TestProcessingPlugin()
    failed_validation = TestProcessingPlugin(plugin_id="bad-validation", fail="validate")
    failed_plan = TestProcessingPlugin(plugin_id="bad-plan", fail="plan")

    validation = ProcessingHookRunner.validate(healthy, _context())
    planning = ProcessingHookRunner.plan(healthy, _context())
    isolated_validation = ProcessingHookRunner.validate(failed_validation, _context())
    isolated_plan = ProcessingHookRunner.plan(failed_plan, _context())

    assert validation.succeeded
    assert validation.issues[0].code == "gain-warning"
    assert planning.succeeded
    assert planning.plan.driver_intent == {"gain": 0.5}
    assert isolated_validation.diagnostic.code == "processing-plugin-validation-failed"
    assert isolated_plan.diagnostic.code == "processing-plugin-planning-failed"
    assert ProcessingHookRunner.plan(healthy, _context()).succeeded


@pytest.mark.parametrize("hook", tuple(ProcessingDriverHook))
def test_typed_processing_driver_exposes_every_reconciliation_hook(hook) -> None:
    plugin = TestProcessingPlugin()

    outcome = ProcessingDriverExecutor().execute(
        plugin_id=plugin.manifest.plugin_id,
        driver=plugin.driver(),
        hook=hook,
        request=_request(),
        timeout_seconds=1,
    )

    assert outcome.succeeded
    assert outcome.result.status == "ready"
    assert outcome.result.facts["hook"] == hook.value


def test_driver_timeout_is_isolated_and_reports_node_context() -> None:
    class SlowDriver(RecordingDriver):
        def prepare(self, request):
            sleep(0.03)
            return super().prepare(request)

    outcome = ProcessingDriverExecutor().execute(
        plugin_id="slow",
        driver=SlowDriver(),
        hook="prepare",
        request=_request(),
        timeout_seconds=0.001,
    )

    assert outcome.failure is ProcessingDriverFailureClassification.TIMEOUT
    assert outcome.diagnostic.code == "processing-driver-timeout"
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
        plugin_id="retry",
        driver=driver,
        hook="prepare",
        request=_request(),
        timeout_seconds=1,
        max_attempts=2,
    )

    assert outcome.succeeded
    assert outcome.attempts == 2
    assert outcome.attempt_idempotency_keys == (
        "action:test:stable",
        "action:test:stable",
    )
    assert {request.idempotency_key for _hook, request in driver.calls} == {"action:test:stable"}


class FakeEntryPoint:
    def __init__(self, name, group, loader):
        self.name = name
        self.group = group
        self.loader = loader

    def load(self):
        return self.loader()


class FakeEntryPoints(tuple):
    def select(self, *, group):
        return tuple(item for item in self if item.group == group)


def test_failed_import_and_start_do_not_block_other_plugins() -> None:
    healthy = TestApplicationPlugin("healthy")
    broken_start = TestApplicationPlugin("broken-start", fail_start=True)
    entries = FakeEntryPoints(
        (
            FakeEntryPoint(
                "broken-import",
                APPLICATION_PLUGIN_ENTRY_POINT,
                lambda: (_ for _ in ()).throw(ImportError("missing dependency")),
            ),
            FakeEntryPoint("healthy", APPLICATION_PLUGIN_ENTRY_POINT, lambda: healthy),
            FakeEntryPoint(
                "broken-start",
                APPLICATION_PLUGIN_ENTRY_POINT,
                lambda: broken_start,
            ),
        )
    )
    registry = PluginRegistry()

    registry.discover(entry_points_provider=lambda: entries)
    registry.start_applications(ApplicationLifecycleContext())

    assert registry.get("healthy").state is PluginLifecycleState.STARTED
    assert registry.get("broken-start").state is PluginLifecycleState.FAILED
    assert any(
        diagnostic.code == "plugin-entry-point-load-failed" for diagnostic in registry.diagnostics
    )
    assert healthy.get_urls() == ("status",)


def test_duplicate_ids_are_rejected_without_replacing_first_plugin() -> None:
    registry = PluginRegistry()
    first = TestApplicationPlugin("duplicate")
    registry.register_application(first)

    with pytest.raises(DuplicatePluginIdError):
        registry.register_application(TestApplicationPlugin("duplicate"))

    assert registry.get("duplicate").plugin is first


def test_audio_backend_registration_is_rejected() -> None:
    class LegacyBackendPlugin(TestApplicationPlugin):
        def get_audio_backend(self):
            return object()

    entries = FakeEntryPoints(
        (
            FakeEntryPoint(
                "legacy-backend",
                APPLICATION_PLUGIN_ENTRY_POINT,
                lambda: LegacyBackendPlugin("legacy-backend"),
            ),
        )
    )
    registry = PluginRegistry()

    registry.discover(entry_points_provider=lambda: entries)

    diagnostic = registry.diagnostics[0]
    assert diagnostic.code == "prohibited-audio-capability"
    assert diagnostic.details["capabilities"] == ("get_audio_backend",)
    assert registry.get("legacy-backend") is None


def test_incompatible_and_missing_node_types_are_visible_in_catalogue_and_plan() -> None:
    registry = PluginRegistry()
    incompatible = TestProcessingPlugin(
        plugin_id="future-processing",
        compatibility=PluginCompatibility(2, 3),
    )
    record = registry.register_processing(incompatible)

    assert record.state is PluginLifecycleState.INCOMPATIBLE
    explanation = registry.plan_availability_explanation(
        (
            ("plugin.future-processing.gain", 1),
            ("plugin.missing.processor", 1),
        )
    )
    nodes = {item["typeId"]: item for item in explanation["nodes"]}
    future = nodes["plugin.future-processing.gain"]
    missing = nodes["plugin.missing.processor"]
    assert future["available"] is False
    assert future["pluginHealth"] == "incompatible"
    assert future["configurationVersion"] == 2
    assert future["incompatibility"]["code"] == "plugin-contract-incompatible"
    assert missing["reason"] == "processing-plugin-or-node-type-unavailable"


def test_node_schema_registration_failure_degrades_only_owning_plugin() -> None:
    registry = PluginRegistry()
    healthy = registry.register_processing(TestProcessingPlugin())
    node_registry = NodeTypeRegistry()
    node_registry.register(healthy.node_types[0].to_node_type_definition())

    diagnostics = registry.register_node_types(node_registry)

    assert diagnostics[0].code == "processing-node-schema-registration-failed"
    assert healthy.health is PluginHealth.DEGRADED
    unrelated = TestApplicationPlugin("unrelated")
    unrelated_record = registry.register_application(unrelated)
    assert unrelated_record.health is PluginHealth.HEALTHY
