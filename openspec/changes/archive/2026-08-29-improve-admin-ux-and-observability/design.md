## Context

See `proposal.md` for motivation. The current Refine/Ant Design management application already has a useful shell and a recognizable React Flow graph editor, but operational and configuration concerns share pages and status elements are inserted conditionally. The Django audio API exposes graph, inventory, runtime projection, managed-adapter restart, and manual-override contracts; it does not yet expose appliance telemetry, generic component control, or persistent volume state. WyrePlumber already provides typed, validated, observed-state-confirmed node volume and mute mutations.

The work crosses the Django API and orchestrator, the shared TypeScript package, `apps/admin`, and a small least-privilege Raspberry deployment addition. `apps/ui` remains out of scope. There is no requirement to preserve legacy user data, but all new writes still need normal migrations and optimistic-concurrency safety.

## Goals / Non-Goals

**Goals:**

- Make the admin app usable as the daily appliance control surface without exposing PipeWire implementation details.
- Preserve the established graph canvas and node appearance while making editing stable, autosaved, and structured.
- Give all asynchronous states a predictable visual location and action hierarchy.
- Define backend contracts that remain safe when devices reconnect, services restart, or the browser has stale state.
- Keep dependencies and Raspberry overhead small.

**Non-Goals:**

- Redesign or implement the physical on-box `apps/ui` application.
- Add software update, release selection, rollback, historical metrics storage, alert delivery, or remote fleet management.
- Add restart support to every observed processor merely because it appears on Managed resources.
- Replace React Flow, rewrite the graph model, or change audio-routing policy.
- Build a fully general JSON Schema form framework; unknown plugin shapes retain an advanced JSON escape hatch.

## Decisions

### 1. Use an operational dashboard hierarchy rather than a table collection

The dashboard will use a responsive Ant Design grid with three visual levels:

1. A top status band containing appliance health, the current human-readable audio path, and master volume/mute.
2. Live CPU and RAM history plus compact temperature, storage, uptime, endpoint, and processor summaries.
3. System information, component versions, recent/degraded details, and a visually separate System controls card.

Full device and resource tables stay on their dedicated pages. Cards use Skeleton for first load and keep fixed internal status areas for refresh/error states. Destructive controls never share a button group with volume.

Ant Design has no chart primitive in the current dependency set. A small accessible SVG `MetricSparkline` will draw the two bounded histories using theme tokens and inline component styles. This avoids a large chart dependency and is the justified custom component in this area. It exposes the current value and trend as text, treats the graphic as supplemental, and does not animate layout.

### 2. Add a separate versioned system API

Appliance data is not audio orchestration state, so it will use `/api/system/v1` rather than expanding `/api/audio/v1`:

- `GET /overview` returns identity, uptime, storage, optional Pi temperature/throttling, readiness summary, observation timestamp, boot identifier, and links.
- `GET /metrics` returns the current CPU and memory sample. The browser polls every two seconds while visible, pauses when hidden, retains a maximum five-minute ring buffer, and marks data stale after three missed intervals. No historical metrics are stored server-side.
- `GET /components` returns a registry of component identifiers, display names, versions, health, observation time, and action descriptors.
- `POST /components/{id}/actions/restart` and `POST /actions/reboot` accept only advertised identifiers and a current action token, return an operation document, and write an administrative audit event.
- `GET /operations/{id}` reports accepted, executing, reconnecting, succeeded, or failed where the initiating service remains able to observe it.

The backend reads Linux `/proc`, `/sys`, `statvfs`, `platform`, package metadata, and the deployment release manifest. Optional Raspberry fields use bounded fixed probes and return unsupported when absent. Fixed version probes use server-owned argv and timeouts; the client cannot provide commands or paths. This avoids adding `psutil` unless implementation proves the standard-library probes insufficient.

### 3. Treat restart as a declared capability, not a generic process endpoint

The system API owns a fixed registry for `open-cinema` and `open-cinema-orchestrator`; the host reboot action is separate. A root-owned helper validates an enumerated action again and invokes only fixed systemd operations. Deployment grants the application identity permission to that helper, not arbitrary `systemctl`, shell, unit-name, or reboot arguments. The API remains staff-only and CSRF-protected.

Self-restart and reboot are scheduled only after an accepted response can be sent. The UI changes to an expected reconnect state, probes session and overview with bounded backoff, and considers success only after a new service start or boot identifier and fresh health are observed. If helper or policy installation is absent, the API advertises the action unavailable and the UI renders explanatory read-only state.

Managed resources use the same presentation shape but not the same execution mechanism. Existing managed-adapter restart is exposed as an action link with its update version. CamillaDSP and decoder runtime projections remain read-only until their supervisor has a safe stable restart intent; the UI never guesses a route from resource type or subject text.

### 4. Model volume as reconciled operational state

Add a singleton versioned master-audio record containing normalized level and mute, and a one-to-one logical-endpoint audio record containing a neutral-by-default device level and device mute. These records are operational preferences, not graph revision content and not expiring manual overrides.

For an output, `effective level = master level × endpoint device level`; either master or endpoint mute silences it. The master defaults to `1.0/unmuted`, and an endpoint defaults to `1.0/unmuted`. Input endpoints use only their endpoint level/mute. API documents return desired factors, effective value, observed value, writability, runtime observation version, and update version so the UI can explain rather than flatten the states.

The audio API adds versioned master-level and endpoint-level resources. Writes are staff-authorized, validate the range, use `If-Match`, and record intent. Slider UIs update locally, debounce/coalesce network writes, allow only one in-flight write per scope, and ignore an acknowledgement older than the latest local sequence.

The orchestrator resolves each logical endpoint immediately before mutation and uses WyrePlumber's confirmed volume/mute controls. Volume intent participates in convergence and drift correction whenever active output selection or runtime generation changes. Stale, ambiguous, absent, and non-writable candidates produce explicit pending/degraded state rather than targeting cached node IDs. Runtime capability projection will distinguish observed values from writable controls.

### 5. Make Managed resources a dedicated capability-driven page

Navigation adds Managed resources adjacent to Devices. Devices retains logical endpoint identity, observation, binding, matching details, and per-endpoint controls. Managed resources groups:

- endpoint adapters such as ROC and debug file adapters;
- processing instances such as CamillaDSP and the adaptive decoder;
- correlated PipeWire-facing resources as expandable technical evidence, not duplicate rows.

Each row has stable name/type, desired lifecycle when present, observed health, version, active profile/mode, last observation, and an action cell derived solely from action descriptors. Restart confirmation and progress use the same stable status slot and operation pattern as system controls. The current adapter management page can either redirect to or become a filtered Managed resources view; configuration/create/delete remains available without duplicating navigation concepts.

### 6. Add a presentation DTO for runtime explanations

The backend resolver will keep its deterministic technical explanation document and additionally emit a versioned `presentation` section derived at resolution time. It contains:

- headline state and concise summary;
- ordered route segments with user-facing endpoint/node/processor names;
- trigger and winning-selection reason;
- rejected or unavailable alternatives with reason codes and display text;
- input, decoder-observed, processor, and final signal descriptors;
- overrides, transition state, timestamps, and actionable errors;
- references back to technical stage/correlation identifiers.

Producing this server-side avoids teaching the UI to interpret arbitrary resolver internals and makes explanation wording testable. `PlanExplanation` renders Result, Audio path, Why this route, Signal and processing, and Transition sections using Result, Steps, Timeline, Descriptions, Tags, and Alert. A collapsed Technical details section retains IDs and formatted JSON for debugging.

### 7. Use a serialized autosave coordinator with local-version ownership

The graph editor will own one reducer state containing the base revision, current local document, monotonically increasing local edit sequence, acknowledged sequence, server update version, draft identity, and save state. All mutation sources dispatch through that reducer.

On the first mutation of a published document, the UI immediately applies the change locally and starts draft creation from the base document. Later mutations continue accumulating. Once a draft exists, a coordinator saves the newest document after a short debounce; only one request is in flight. Node movement emits a document mutation on drag stop, while the canvas may update locally during drag.

A response acknowledges the sequence it sent. If newer edits exist, only server identity/version metadata is accepted and newer local content remains authoritative. The next save sends that content. If no newer edit exists, the canonical response may replace the acknowledged document. Apply cancels the debounce, drains the save queue, then validates and publishes exactly the acknowledged latest sequence.

Transient failures retain local content and retry with bounded backoff. A precondition conflict pauses autosave and presents three explicit choices: review/export the local copy, reload the remote draft, or create a new draft/graph copy where supported. No timer or refresh silently discards either version. Browser unload warnings appear only while data is pending, failed, or conflicted; a saved draft is not described as “unsaved changes.”

### 8. Separate compact graph nodes from configuration forms

The existing node cards, ports, edges, background, minimap, badges, and resolved/runtime overlays remain the graph's visual baseline. Selection applies a stable highlight but does not add a toolbar or replace summaries with input controls inside the node.

A page-level Ant Design Drawer is the node inspector. It overlays rather than resizes the canvas on desktop and uses an appropriate full-width presentation on narrow screens. It contains metadata, structured configuration, validation, and compact destructive actions with confirmation. With autosave there is no per-node Save or Reload toolbar. Graph-level add menus remain outside the transformed React Flow viewport and use portal rendering, content-based minimum width, a viewport-relative maximum width/height, and scrolling.

The structured field renderer handles primitives, enum and union selection, repeatable arrays, editable key/value maps, selectors, parameter/public-port declarations, and subgraph mappings. Unsupported shapes are preserved losslessly and exposed under Advanced JSON with parsing and schema validation. This replaces the current broad object/array-to-JSON fallback without pretending every plugin schema can be represented.

### 9. Centralize stable feedback and action rules

The admin app will introduce small shared patterns composed from Ant Design primitives: page heading/actions, a reserved status region, capability action, and section skeleton. These are components, not a new visual design system. Status text uses `aria-live` as appropriate and button loading states retain width.

Graph lifecycle has one primary slot based on viewed context:

- graph list or inactive published revision: Apply;
- graph list or active published revision: Deactivate;
- editable draft: Apply changes, even if it will replace an active revision;
- subgraph or ineligible revision: no live action, with an explanatory disabled/read-only state where useful.

Row navigation excludes interactive descendants. Deactivation of the revision currently active is available from its published context rather than appearing beside draft Apply changes.

Speaker test always renders the same output selector, status slot, channel grid, and Stop area. Active/error text changes inside the reserved slot, so a delayed response cannot move a channel button under the pointer.

### 10. Verify behavior, accessibility, and visual stability at component boundaries

Backend tests cover authentication, capability advertisement, fixed action allowlists, metrics failure isolation, versions, concurrency, endpoint resolution, volume reconciliation, and route-switch reapplication. WyrePlumber integration uses its existing control contract and adds Open Cinema adapter tests rather than changing the binding unless a missing capability is found.

Frontend unit tests use fake timers and deferred promises for autosave ordering, draft creation races, stale response handling, slider coalescing, and stable action selection. Playwright mocks gain system, volume, resource-action, and presentation DTOs. Reference images cover dashboard, Devices, Managed resources, graph list, graph editor and inspector at multiple zooms, runtime explanation, and speaker test before/after status changes in light and dark modes. Tests assert bounding boxes for controls that previously shifted and run serious/critical accessibility checks.

## Risks / Trade-offs

- **[Volume multiplication is less familiar than a single sink slider]** → Label the endpoint control as Device level, show the effective value in details, default endpoint level to neutral, and provide plain-language help.
- **[Autosave can overwrite newer work if responses race]** → Centralize mutations in one sequence-aware coordinator, serialize writes, and test delayed/out-of-order responses explicitly.
- **[Self-restart and reboot intentionally break the request channel]** → Return accepted state before scheduling, track start/boot identity, and make expected reconnection a first-class UI state.
- **[System probes vary across Linux and development hosts]** → Treat every optional probe independently, use bounded fixed inputs, and expose unsupported values without failing the page.
- **[A Drawer may cover graph context on small displays]** → Use an overlay that can be closed without losing edits, keep node selection visible, and use full-width responsive behavior only where needed.
- **[Human explanation text can drift from resolver behavior]** → Derive presentation fields in the resolver result, keep reason codes stable, and test them alongside technical evidence.
- **[Two API namespaces add contract surface]** → Keep appliance concerns isolated, use the same authentication/problem/concurrency conventions, and export both through the shared client package.

## Migration Plan

1. Add models and read-only system/volume/resource capability contracts with default neutral audio state; deploy without advertising privileged actions.
2. Add orchestrator volume reconciliation and validate route switching, reconnect, mute, and drift on development fixtures and the Raspberry Pi.
3. Add the shared clients and admin pages behind capability detection; keep existing graph Apply behavior until autosave tests pass.
4. Deploy the allowlisted host-control helper and permissions, then advertise only the actions proven by an installation self-check.
5. Enable the new dashboard, navigation, graph autosave/inspector, explanation, and stable speaker test; update visual references and run frontend/backend acceptance suites.
6. Roll back by removing action advertisement and serving the prior frontend. Neutral volume records and draft layout data can remain because older code ignores them; the helper permission can be removed independently.
