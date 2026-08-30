# Authoring an Open Cinema plugin

## Package contract

A plugin is a normal Python wheel with one `open_cinema.plugins` entry point and
one packaged `open-cinema-plugin.toml`. Use a repository name beginning with
`open-cinema-`, a stable lowercase plugin ID, and namespaced capability, route,
field, page, resource, automation, and processing-node IDs.

```toml
[project]
name = "open-cinema-example"
version = "1.0.0"

[project.entry-points."open_cinema.plugins"]
example = "open_cinema_example.plugin:ExamplePlugin"
```

The static manifest declares publisher metadata, exact distribution identity,
Open Cinema/Python/platform compatibility, plugin-contract and capability
versions, permissions with reasons, optional external requirements and
configuration schema, capability declarations, and lifecycle impact for every
operation. It is inspected before any plugin code runs. Source archives and
wheels must contain the same manifest.

Import public types from `open_cinema_plugin_sdk`. Implement
`OpenCinemaPlugin.identity` and `capabilities()`. Optional `start()` and `stop()`
receive a frozen, bounded `DistributionLifecycleContext` and return a typed
`PluginRuntimeResult`; they must be idempotent. Do not import registry,
persistence, overlay, or orchestration implementation modules.

## Capabilities

- `ApiCapability` supplies routes mounted only below `/api/plugins/<plugin-id>/`.
  Core authentication, CSRF, enabled-state, timeout, and error correlation
  wrappers remain in force.
- `AutomationCapability` supplies namespaced, bounded hooks.
- `ProcessingCapability` supplies typed graph node definitions, pure planning,
  migrations, and drivers.
- `ManagedResourceCapability` observes long-lived resources and advertises only
  actions it can currently perform.
- `ManagedAudioSourceCapability` manages repeatable source instances and reports
  source signal/correlation facts for core resolution.
- `AdminUICapability` supplies a validated declarative descriptor. It never
  supplies JavaScript or CSS.

Plugins cannot declare authentication, device observation, an audio backend,
WirePlumber reconciliation, arbitrary host commands, or unrestricted systemd
units. External programs must be named in the manifest, probed explicitly, and
started through a bounded provider contract.

A managed-audio-source graph node declares its durable endpoint role on the root
of its configuration schema:

```json
{
  "x-open-cinema-managed-audio-source": {
    "pluginId": "example.receiver",
    "capabilityId": "example.receiver.sources",
    "instanceProperty": "instanceId"
  }
}
```

The named instance field should use the `plugin-instance-select` widget with the
same plugin and capability IDs. Core derives the stable logical-endpoint UUID,
checks availability, translates the selected source to exactly one fresh
PipeWire stream, and preserves the node when the instance is absent. Plugins
must not store or resolve transient runtime node IDs.

## Configuration and secrets

Register versioned JSON Schemas for settings and instance documents. Every
migration is a pure `n -> n+1` function and the result is validated before it
replaces active data. Use optimistic concurrency tokens on writes. Secret
fields use core secret references: UI reads only `{configured: true|false}` and
submitting an empty field does not reveal or overwrite an existing value.

Managed providers may use the bounded host service
`logical_endpoint_references()` to warn before deleting an instance whose
durable endpoint remains in saved graphs. The host scopes results to the
instance owner; plugins should preserve those graph references as unavailable.

Declarative UI supports settings, resource list/detail, overview/status, and
guided-flow pages. Prefer typed `text`, `number`, `boolean`, `enum`,
`multiselect`, `duration`, `path`, `url`, `secret`, `repeatable`, and `group`
fields. Bind only to the plugin API namespace, use simple bounded conditional
visibility, and advertise action availability/reason/concurrency tokens from
the server. The renderer intentionally has no arbitrary JSON or HTML widget.

A `resource-list` response may expose an `editor` object containing a typed
`document` and write `href`, per-item `actions` using the same confirmation and
lifecycle vocabulary, a bounded `summary`, diagnostics, and a
`guidedOperation`. The product renderer opens these in a responsive Ant Design
drawer without shifting the list. `external-authorization` guided operations
provide an authorization URL plus typed callback and cancellation endpoints;
tokens remain server-side. A create binding may name a validated
`successPageId` for the post-create handoff. These response semantics are
generic—plugin-specific React components remain prohibited.

## CI and release

Install Open Cinema as a development dependency, then validate both checkout
and built artifact with the public suite:

```python
from open_cinema_plugin_sdk import assert_plugin_contract

def test_distribution_contract(built_wheel):
    assert_plugin_contract(".", wheel=built_wheel, plugin=ExamplePlugin())
```

Run tests on Python 3.12 and 3.13, build a wheel and source archive, inspect
their contents, and publish immutable checksums/provenance. Tags and manifest
versions must match. A first-party catalogue release also pins repository,
revision, resolved commit, and artifact digest. Compatibility changes require a
new plugin or capability contract version; unknown versions fail closed.
