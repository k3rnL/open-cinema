## Why

Open Cinema can discover backend application and processing extensions, but plugins cannot
contribute a polished administration experience or be installed, activated, inspected, and
removed by an appliance administrator. A versioned plugin platform is needed before a separately
released librespot integration can behave like a first-class part of the product.

## What Changes

- Extend the existing backend plugin registry into a documented, versioned distribution contract
  with stable identity, compatibility, capabilities, permissions, dependencies, lifecycle impact,
  health, and diagnostics.
- Add declarative administration-UI contributions for navigation, list/detail/settings pages,
  typed forms, guided actions, status surfaces, conditional fields, and write-only secrets.
- Add a Plugins administration area with a hard-coded first-party catalogue, installed-plugin
  inventory, Git-source installation, compatibility and trust review, progress, failure recovery,
  update, enable, disable, and uninstall controls.
- Distinguish hot activation, Open Cinema service restart, and full host reboot requirements, and
  expose only lifecycle operations the installed plugin and host can safely perform.
- Preserve core ownership of authentication, presentation, PipeWire observation, graph resolution,
  and privileged host control while allowing plugins to contribute typed capabilities through
  bounded contracts.
- Document plugin authoring, packaging, UI composition, configuration migration, lifecycle,
  security, CI, release, and compatibility requirements.
- **BREAKING**: replace the version-1 single-kind runtime manifest with a version-2
  distribution-and-capability model; migrate the bundled counter example and existing processing
  registrations to the new contract without retaining a legacy compatibility loader.

## Capabilities

### New Capabilities

- `application-plugin-platform`: Plugin packaging, catalogue discovery, installation, trust,
  compatibility, capabilities, lifecycle, state, health, update, removal, and author contract.
- `declarative-plugin-admin-ui`: Runtime-discovered, Ant Design-based plugin navigation and
  administration pages rendered from bounded declarative contributions.

### Modified Capabilities

- `audio-processing-plugins`: Processing extensions participate in the common versioned plugin
  distribution and capability model while retaining typed planning and core audio-ownership
  boundaries.
- `appliance-observability-control`: Plugin-managed resources and lifecycle operations expose the
  same authenticated, capability-advertised, concurrency-safe control semantics as core resources.

## Impact

This change affects the Python plugin contracts and registry, Django plugin APIs and persistence,
the orchestrator's managed-resource catalogue, privileged installation/restart integration, the
Refine administration application, deployment permissions, the bundled counter plugin, processing
plugin registration, tests, and author documentation. Plugin installation executes trusted code
and therefore requires explicit administrator confirmation, provenance reporting, staged
validation, and recoverable failure handling. The initial marketplace is a maintained first-party
catalogue rather than a remote public service.
