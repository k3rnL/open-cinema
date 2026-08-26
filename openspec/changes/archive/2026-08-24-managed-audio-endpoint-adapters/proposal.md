## Why

Open Cinema can route discovered PipeWire endpoints, but endpoint-producing resources such as ROC network transports currently have to be created by hand and kept alive by an external `pw-cli` session. Debugging also needs repeatable audio sources and sinks that do not depend on physical hardware.

## What Changes

- Add managed audio endpoint adapters with persistent configuration and reconciled runtime lifecycle.
- Add ROC receive and send adapters that expose stable PipeWire input/output endpoints and make network parameters configurable from the management UI.
- Add a debug file source that continuously loops an audio file and exposes it as a PipeWire input endpoint.
- Add a debug file recorder that accepts PipeWire audio and writes it to a configured file.
- Add start, stop, restart, health, diagnostics, and endpoint-correlation APIs for adapter instances.
- Add an end-user management menu in `apps/admin`; keep adapter endpoints usable in the existing discovery and graph workflows.
- Add explicit graph Apply and Deactivate actions that can activate an existing published revision or withdraw runtime routes without requiring or losing a draft.
- Keep managed endpoint adapters distinct from physical-device discovery, graph processors, and deployment/service installation.

## Capabilities

### New Capabilities

- `managed-audio-endpoint-adapters`: Persistent, reconciled ROC and debug-file resources that create stable PipeWire-facing endpoints and can be managed from the web UI.

### Modified Capabilities

- `desired-audio-graphs`: Active top-level graphs can be deactivated without deleting their definitions or revision history.
- `audio-reconciliation`: A disabled graph is reconciled by removing only that graph's managed links and returning its applied state to idle.

## Impact

- Adds orchestration persistence, lifecycle drivers, API resources, audit/status projection, and migrations in `open-cinema`.
- Adds shared DTO/client contracts and an adapter-management page in `open-cinema-ui/apps/admin` without custom CSS.
- Adds graph Apply and Deactivate controls to the existing graph list and editor workflows using the established component system.
- Uses locally available PipeWire ROC modules and PipeWire file streaming tools for the initial implementation; appliance package installation and system service deployment remain in the separate deployment change.
- Adapter-created nodes become endpoint candidates for logical endpoint binding and desired graphs, with stable ownership/correlation properties.
