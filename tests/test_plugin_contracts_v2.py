from __future__ import annotations

import platform

import pytest

from core.plugin_system import (
    PLUGIN_ENTRY_POINT,
    AdminUICapability,
    ApiCapability,
    AutomationCapability,
    DuplicatePluginDistributionError,
    LifecycleImpact,
    OpenCinemaPlugin,
    PluginDistributionRegistry,
    PluginHealth,
    PluginIdentityMismatchError,
    PluginLifecycleState,
    ProhibitedPluginCapabilityError,
    RuntimePluginIdentity,
    parse_plugin_manifest,
)


def _manifest_document(
    *,
    plugin_id: str = "test.composite",
    capabilities: list[dict[str, object]] | None = None,
    permissions: list[dict[str, object]] | None = None,
    contract_minimum: int = 2,
    contract_maximum: int = 2,
) -> dict[str, object]:
    return {
        "schema-version": 2,
        "plugin": {
            "id": plugin_id,
            "distribution": f"open-cinema-{plugin_id.replace('.', '-')}",
            "display-name": "Composite test",
            "description": "A composite contract fixture.",
            "vendor": "Open Cinema tests",
            "version": "1.2.3",
            "license": "MIT",
            "source-url": "https://example.test/source",
            "documentation-url": "https://example.test/docs",
        },
        "compatibility": {
            "plugin-contract": {
                "minimum": contract_minimum,
                "maximum": contract_maximum,
            },
            "open-cinema": ">=0.3,<1",
            "python": ">=3.12,<4",
            "operating-systems": [platform.system().lower()],
            "architectures": [platform.machine().lower()],
            "capability-versions": {
                "api": {"minimum": 1, "maximum": 1},
                "automation": {"minimum": 1, "maximum": 1},
                "admin-ui": {"minimum": 1, "maximum": 1},
            },
        },
        "capabilities": capabilities
        or [
            {"id": f"{plugin_id}.api", "kind": "api", "version": 1},
            {
                "id": f"{plugin_id}.automation",
                "kind": "automation",
                "version": 1,
            },
            {"id": f"{plugin_id}.admin", "kind": "admin-ui", "version": 1},
        ],
        "permissions": permissions or [],
        "lifecycle": {
            "install": "application-restart",
            "enable": "hot",
            "disable": "hot",
            "update": "application-restart",
            "uninstall": "application-restart",
        },
    }


def _ui_descriptor(plugin_id: str = "test.composite") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "navigation": [
            {
                "id": f"{plugin_id}.navigation",
                "label": "Composite",
                "pageId": f"{plugin_id}.settings",
                "order": 20,
            }
        ],
        "pages": [
            {
                "id": f"{plugin_id}.settings",
                "title": "Composite settings",
                "template": "settings",
                "binding": {
                    "read": f"/api/plugins/{plugin_id}/configuration",
                    "write": f"/api/plugins/{plugin_id}/configuration",
                },
                "sections": [
                    {
                        "id": f"{plugin_id}.general",
                        "title": "General",
                        "presentation": "card",
                        "fields": [
                            {
                                "id": f"{plugin_id}.name",
                                "path": "/name",
                                "label": "Name",
                                "widget": "text",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class CompositePlugin(OpenCinemaPlugin):
    def __init__(self, plugin_id: str = "test.composite", *, partial: bool = False) -> None:
        self.plugin_id = plugin_id
        self.partial = partial

    @property
    def identity(self) -> RuntimePluginIdentity:
        return RuntimePluginIdentity(
            self.plugin_id,
            f"open-cinema-{self.plugin_id.replace('.', '-')}",
            "1.2.3",
        )

    def capabilities(self):
        contributions = [
            ApiCapability(f"{self.plugin_id}.api", routes=lambda: ("status",)),
            AutomationCapability(
                f"{self.plugin_id}.automation",
                hooks={f"{self.plugin_id}.tick": lambda: "tick"},
            ),
        ]
        if not self.partial:
            contributions.append(
                AdminUICapability(
                    f"{self.plugin_id}.admin",
                    descriptor=_ui_descriptor(self.plugin_id),
                )
            )
        return tuple(contributions)


def test_valid_composite_distribution_has_one_identity_and_independent_capabilities() -> None:
    manifest = parse_plugin_manifest(_manifest_document())
    registry = PluginDistributionRegistry()

    record = registry.register(manifest, CompositePlugin())

    assert record.state is PluginLifecycleState.AVAILABLE
    assert record.health is PluginHealth.HEALTHY
    assert [item.declaration.capability_id for item in record.capabilities] == [
        "test.composite.api",
        "test.composite.automation",
        "test.composite.admin",
    ]
    assert all(item.health is PluginHealth.HEALTHY for item in record.capabilities)
    document = registry.catalogue_document()["plugins"][0]
    assert document["desiredState"] == "enabled"
    assert document["lifecycleImpact"]["install"] == LifecycleImpact.APPLICATION_RESTART
    assert document["capabilities"][2]["schemaMetadata"]["descriptor"]["schemaVersion"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.pop("compatibility"),
        lambda document: document.update({"unknown-contract-feature": True}),
        lambda document: document["lifecycle"].update({"enable": "magic"}),
    ],
)
def test_malformed_static_manifest_is_rejected_before_runtime_activation(mutation) -> None:
    document = _manifest_document()
    mutation(document)

    with pytest.raises(ValueError):
        parse_plugin_manifest(document)


def test_static_and_runtime_identity_must_match() -> None:
    manifest = parse_plugin_manifest(_manifest_document())

    with pytest.raises(PluginIdentityMismatchError, match="runtime identity"):
        PluginDistributionRegistry().register(manifest, CompositePlugin("test.other"))


def test_incompatible_plugin_remains_inspectable_without_runtime_capabilities() -> None:
    manifest = parse_plugin_manifest(_manifest_document(contract_minimum=3, contract_maximum=3))

    record = PluginDistributionRegistry().register(manifest, CompositePlugin())

    assert record.state is PluginLifecycleState.INCOMPATIBLE
    assert record.health is PluginHealth.INCOMPATIBLE
    assert all(item.contribution is None for item in record.capabilities)
    assert record.compatibility.reasons == ("plugin-contract-incompatible",)


def test_duplicate_capability_declarations_are_rejected() -> None:
    capabilities = [
        {"id": "test.composite.same", "kind": "api", "version": 1},
        {"id": "test.composite.same", "kind": "automation", "version": 1},
    ]

    with pytest.raises(ValueError, match="capability IDs must be unique"):
        parse_plugin_manifest(_manifest_document(capabilities=capabilities))


def test_duplicate_distribution_identity_does_not_replace_first_plugin() -> None:
    manifest = parse_plugin_manifest(_manifest_document())
    registry = PluginDistributionRegistry()
    first = registry.register(manifest, CompositePlugin())

    with pytest.raises(DuplicatePluginDistributionError):
        registry.register(manifest, CompositePlugin())

    assert registry.get("test.composite") is first


def test_prohibited_core_ownership_is_rejected() -> None:
    manifest = parse_plugin_manifest(
        _manifest_document(
            permissions=[
                {
                    "id": "audio.device-observation",
                    "reason": "Attempt to replace core observation.",
                }
            ]
        )
    )

    with pytest.raises(ProhibitedPluginCapabilityError) as raised:
        PluginDistributionRegistry().register(manifest, CompositePlugin())

    assert raised.value.capabilities == ("audio.device-observation",)


class FakeDistribution:
    name = "open-cinema-test-composite"
    version = "1.2.3"
    files = ()

    def __init__(self, manifest_text: str) -> None:
        self.manifest_text = manifest_text

    def read_text(self, filename: str) -> str | None:
        return self.manifest_text


class FakeEntryPoint:
    group = PLUGIN_ENTRY_POINT
    name = "test.composite"

    def __init__(self, manifest_text: str, loader) -> None:
        self.dist = FakeDistribution(manifest_text)
        self.loader = loader

    def load(self):
        return self.loader()


VALID_TOML = f"""
schema-version = 2
permissions = []

[plugin]
id = "test.composite"
distribution = "open-cinema-test-composite"
display-name = "Composite test"
description = "A composite contract fixture."
vendor = "Open Cinema tests"
version = "1.2.3"
license = "MIT"
source-url = "https://example.test/source"
documentation-url = "https://example.test/docs"

[compatibility]
open-cinema = ">=0.3,<1"
python = ">=3.12,<4"
operating-systems = ["{platform.system().lower()}"]
architectures = ["{platform.machine().lower()}"]

[compatibility.plugin-contract]
minimum = 2
maximum = 2

[[capabilities]]
id = "test.composite.api"
kind = "api"
version = 1

[[capabilities]]
id = "test.composite.automation"
kind = "automation"
version = 1

[[capabilities]]
id = "test.composite.admin"
kind = "admin-ui"
version = 1

[lifecycle]
install = "application-restart"
enable = "hot"
disable = "hot"
update = "application-restart"
uninstall = "application-restart"
"""


def test_import_failure_is_retained_without_blocking_other_distributions() -> None:
    healthy = FakeEntryPoint(VALID_TOML, CompositePlugin)
    failing_toml = VALID_TOML.replace("test.composite", "test.failed").replace(
        "open-cinema-test-composite", "open-cinema-test-failed"
    )
    failed = FakeEntryPoint(
        failing_toml,
        lambda: (_ for _ in ()).throw(RuntimeError("import exploded")),
    )
    failed.name = "test.failed"
    registry = PluginDistributionRegistry()

    registry.discover(entry_points_provider=lambda: (failed, healthy))

    assert registry.get("test.failed").state is PluginLifecycleState.FAILED
    assert registry.get("test.composite").health is PluginHealth.HEALTHY
    assert any(item.code == "plugin-entry-point-import-failed" for item in registry.diagnostics)


def test_malformed_manifest_never_imports_entry_point() -> None:
    imported = False

    def loader():
        nonlocal imported
        imported = True
        return CompositePlugin()

    malformed = FakeEntryPoint(VALID_TOML + "\nunknown = true\n", loader)
    registry = PluginDistributionRegistry()

    registry.discover(entry_points_provider=lambda: (malformed,))

    assert not imported
    assert registry.records == ()
    assert registry.diagnostics[0].code == "manifest-schema-invalid"


def test_missing_runtime_capability_degrades_only_that_capability() -> None:
    manifest = parse_plugin_manifest(_manifest_document())

    record = PluginDistributionRegistry().register(manifest, CompositePlugin(partial=True))

    assert record.state is PluginLifecycleState.AVAILABLE
    assert record.health is PluginHealth.DEGRADED
    assert record.capabilities[0].health is PluginHealth.HEALTHY
    assert record.capabilities[1].health is PluginHealth.HEALTHY
    assert record.capabilities[2].health is PluginHealth.FAILED
    assert record.capabilities[2].diagnostics[0].code == "declared-capability-missing"
