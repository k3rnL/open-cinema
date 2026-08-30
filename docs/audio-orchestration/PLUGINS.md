# Plugin platform version 2

Open Cinema loads one distribution entry point from `open_cinema.plugins` and
reads one static `open-cinema-plugin.toml` before importing its Python code. A
distribution may contribute API, automation, processing, managed-resource,
managed-audio-source, and declarative administration-UI capabilities. The
static and runtime plugin IDs, distribution, version, capability IDs, kinds,
and versions must agree.

The contract is deliberately not an audio-backend abstraction. PipeWire graph
observation, WirePlumber policy, device ownership, desired-graph resolution,
and reconciliation remain core responsibilities. A managed audio source, such
as librespot, exposes its instances and correlation facts; core decides where
that source is routed.

## Installation and runtime model

The Plugins page exposes a maintained first-party catalogue and a separate
Installed inventory. Advanced users may inspect and install a credential-free
HTTPS Git source after explicitly acknowledging that plugin Python executes
with the Open Cinema service account's privileges.

Every candidate is acquired into bounded staging, built as a wheel, checked
against the static manifest, dependency constraints, permissions, and current
contract, then resolved with every already installed plugin into a new
immutable overlay generation. Only a complete generation is activated.
`current` and `last-known-good` pointers are atomic and rollback never mutates
the base virtual environment.

Install, enable, disable, update, uninstall, cleanup, retry, and rollback are
persistent serialized operations. Their effective lifecycle is `hot`,
`application-restart`, or `host-reboot`; Open Cinema raises the impact when a
capability cannot disappear safely in the current process. Plugin data is
retained by default on uninstall, while explicit delete removes documents,
instances, and secrets but leaves desired graph nodes intact and unavailable.

## Storage, secrets, and UI

Plugins use namespaced core repositories with JSON Schema validation, optimistic
concurrency, bounded documents, repeatable instances, and pure version-by-version
configuration migrations. Secrets are write-only references stored outside the
database. They are never returned by API, diagnostics, operation records, or
logs.

Administration UI contributions are data, not executable browser bundles.
Open Cinema UI validates the descriptor and renders product-owned Ant Design
settings, resource, overview, detail, and guided-flow templates at the stable
`/plugins/:pluginId/:pageId` route. Unknown schemas fail closed within that
plugin's page. Core navigation and the dashboard do not wait for plugin data
endpoints. Disabled, failed, and incompatible plugins remain visible only in
Plugins diagnostics.

## Processing and managed resources

Processing contributions retain the typed node, immutable planning context,
configuration migration, and bounded driver contracts. Processors manage only
their declared program instances and facts. Managed-resource providers expose
fresh observations and explicit supported actions. Managed-audio-source
providers add repeatable source instances with declared PCM/encoded signal
shape and PipeWire correlation keys; they do not create an alternative session
manager.

See [Plugin authoring](../plugins/AUTHORING.md),
[plugin administration](../plugins/ADMINISTRATION.md), and the
[external counter walkthrough](../plugins/COUNTER_EXAMPLE.md).
