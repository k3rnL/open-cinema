## Why

The management UI exposes most of Open Cinema's audio concepts, but routine operation still requires technical knowledge and several interactions are unstable or contradictory. The appliance now needs a coherent control surface that explains what it is doing, keeps editing work safe automatically, and exposes the system and audio controls required for daily use.

## What Changes

- Redesign the dashboard as an appliance overview with live CPU and memory history, system identity and health, component versions, active audio-path status, persistent master volume, and guarded service/appliance restart actions.
- Introduce a dedicated Managed resources menu for CamillaDSP, the adaptive decoder, managed adapters, and other supervised resources. Advertise available actions per resource and only render restart controls when the backend declares that action.
- Keep Devices focused on logical and observed audio endpoints, and add capability-aware output volume and mute controls without exposing transient PipeWire identifiers as the primary user concept.
- Make graph activation a single stateful action: inactive published graphs can be applied and active graphs can be deactivated, never both at once. Make graph rows navigable to their editor.
- Replace the technical-first resolved-plan dump with a human explanation of the active source-to-output route, why it was selected, unavailable alternatives, processor and signal-format decisions, transition progress, and errors; retain raw identifiers and JSON only in collapsed technical details.
- Start a draft automatically on the first graph mutation and autosave node positions, configuration, edges, and document structure. Preserve local edits across draft creation, save responses, refreshes, and optimistic-concurrency conflicts, and flush pending saves before Apply.
- Preserve the existing graph appearance while moving configuration editing into a stable Ant Design inspector outside the zoomed canvas. Use structured schema-driven controls for common values and mappings, with raw JSON available only as an advanced fallback for genuinely unstructured data.
- Keep menus and transient status content independent of graph zoom, constrain their viewport size, and prevent alerts, loading states, selection controls, and speaker-test status from moving primary controls unexpectedly.
- Apply a focused UI consistency and accessibility pass to the management app using Ant Design components and tokens, stable page/status regions, responsive layouts, clear action hierarchy, and existing test/reference coverage.

## Capabilities

### New Capabilities

- `appliance-observability-control`: Live appliance metrics, system and component information, health summaries, capability-advertised resource actions, and guarded service or host restart operations.
- `audio-volume-control`: Persistent master volume and mute behavior that follows active output selection, plus capability-aware per-device volume and mute control.

### Modified Capabilities

- `audio-orchestration-api-ui`: Restructure management navigation and dashboard presentation, provide human-first runtime explanations, and require stable, accessible interaction feedback.
- `desired-audio-graphs`: Add implicit draft creation, complete autosave semantics, persistent graph layout, and mutually exclusive activation controls.
- `audio-endpoint-inventory`: Separate physical/logical audio devices from managed processing resources and expose user-facing device control capabilities without relying on transient runtime identity.
- `speaker-channel-testing`: Keep channel controls spatially stable while test status and errors change.

## Impact

- Django audio API: new authenticated system overview/metrics/control and volume contracts; richer managed-resource action metadata and plan-explanation presentation data.
- Orchestration/runtime: persistent master and endpoint volume state, active-output reapplication, capability discovery, and allowlisted control execution.
- Management frontend (`/home/edaniel/WebStormProjects/open-cinema-ui/apps/admin`): dashboard, navigation, devices/resources pages, graph list/editor, runtime explanation, speaker test, shared Ant Design interaction patterns, and regression/accessibility tests.
- Shared TypeScript API package: DTOs, validation, client methods, and event/state integration for the added contracts.
- Raspberry deployment: least-privilege authorization for explicitly supported system actions; unavailable privileges remain visible as unsupported capabilities rather than producing non-functional controls.
- No change to the independent on-box `apps/ui` placeholder in this change.
