# Application and processing plugins

Open Cinema has two explicit extension contracts. Neither is an audio backend.
WirePlumber observation, endpoint volume/mute, defaults, stream targets,
profiles/routes, and session-link ownership remain core orchestration
responsibilities.

## Application plugins

An `ApplicationPlugin` extends the web application with namespaced routes,
Django model packages, and named automation hooks. Its
`ApplicationPluginManifest` declares a stable lowercase plugin ID, display
metadata, package version, supported Open Cinema plugin-contract range, route
namespace, model packages, and automation IDs.

Application plugins are loaded from the
`open_cinema.application_plugins` Python package entry-point group. The
registry checks compatibility and duplicate IDs before lifecycle start, then
records `available`, `started`, `stopped`, `failed`, or `incompatible` state and
health. One import or lifecycle failure is retained as a diagnostic and does
not prevent unrelated plugins or runtime observation from starting.

The bundled counter example now uses this contract. Its model remains a normal
installed Django application, while routes and the `counter.current-value`
automation are registered through the application manifest. It has no
dependency on processing plugins or audio runtime control.

## Processing plugins

A `ProcessingPlugin` contributes one or more
`ProcessingNodeTypeManifest` values. Each node type declares:

- a namespaced ID and structural version;
- a configuration version and Draft 2020-12 JSON schema;
- display name, category, and description;
- UI-editable JSON pointer fields;
- typed ports whose signal contracts include encoded/PCM content, formats,
  rates, layouts, latency, codecs, and capabilities;
- explicit one-version-at-a-time configuration migrations.

Configuration migration preserves fields the migration does not intentionally
change and validates the final object against the current schema. A missing
migration step, newer unsupported configuration version, invalid schema, or
invalid migrated result makes that node unavailable without discarding its
opaque stored configuration.

Processing plugins are loaded from the
`open_cinema.processing_plugins` entry-point group. Their node IDs use the
`plugin.<plugin-id>.*` namespace so catalogue ownership and missing-plugin
diagnostics are unambiguous.

## Pure planning and typed drivers

Processing `validate` and `plan` hooks receive immutable detached context and
must be side-effect-free. The failure-isolating runner accepts only typed
validation issues and processing plans. Exceptions become plugin diagnostics;
they do not stop other plugins or the WirePlumber observer.

Runtime work uses a separate typed driver with exactly these hooks:
`prepare`, `observe`, `activate`, `reconfigure`, `deactivate`, and `cleanup`.
Every request contains the node instance, immutable configuration and plan, and
a reconciliation idempotency key. Bounded retries reuse that exact key. A
timeout is reported as an uncertain isolated failure and is not retried inside
the executor, because Python cannot safely cancel a hook already running in a
thread; reconciliation must observe before deciding whether a later retry is
safe.

## Prohibited audio ownership

Plugin discovery rejects application or processing classes that attempt to
declare audio-backend selection, device discovery, session observation, or
backend registration methods such as `get_audio_backend`. The diagnostic code
is `prohibited-audio-capability` and lists the offending capabilities. There is
no audio-backend plugin contract or compatibility shim.

Audio processors remain extensible, but their drivers manage only the processor
resources and facts declared by their node types. They request typed
reconciliation actions and cannot become an alternative owner of endpoints or
the PipeWire session.

## Catalogue and explanations

The plugin catalogue exposes contract and entry-point versions, manifest
metadata, lifecycle state, health, diagnostics, node-type schemas,
configuration versions, editable fields, ports, and migration boundaries.
Plan availability explanations correlate every required node type to its
plugin, health, configuration version, and incompatibility detail. A missing
plugin is an explicit unavailable node, not a reason to drop its configuration
from the desired graph.
