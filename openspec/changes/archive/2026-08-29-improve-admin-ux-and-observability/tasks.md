## 1. Baseline and contract fixtures

- [x] 1.1 Run the current admin application against deterministic API fixtures and refresh baseline screenshots for dashboard, Devices, graph list, graph editor with and without a selected node, runtime explanation, and speaker test in light and dark modes.
- [x] 1.2 Record the current bounding boxes and interaction states for graph header actions, node cards, graph menus, speaker channel buttons, and page status regions so layout-stability regressions can be tested.
- [x] 1.3 Add representative backend fixtures for Raspberry system data, partial/unsupported system data, component versions/actions, writable and read-only endpoint volume, managed resources, and human runtime explanations.
- [x] 1.4 Add matching shared-package and Playwright API fixtures with realistic TV → decoder → CamillaDSP → speakers/headset routes and reconnecting resources.

## 2. Appliance observation backend

- [x] 2.1 Create a `system_v1` API namespace with the established authentication, CSRF, version-header, problem-document, and schema metadata conventions.
- [x] 2.2 Implement independently fault-tolerant probes for hostname/model, OS/kernel, boot identity, uptime, storage, CPU, memory, and optional Raspberry temperature/throttling without accepting client-controlled paths or commands.
- [x] 2.3 Implement the system overview and current metric sample endpoints, including observation timestamps, supported/unavailable field state, and bounded probe timeouts.
- [x] 2.4 Implement a fixed component registry for Open Cinema, the orchestrator, WyrePlumber, PipeWire/WirePlumber runtime, CamillaDSP, and the adaptive decoder using package metadata, release-manifest data, runtime health, and bounded version probes.
- [x] 2.5 Add API schema/OpenAPI documents and tests for full Raspberry data, non-Raspberry fallback, individual probe failure, authentication, version compatibility, and privacy-safe responses.
- [x] 2.6 Benchmark the observation endpoints on the Raspberry and verify the two-second dashboard cadence has negligible CPU, memory, disk, and subprocess overhead.

## 3. Guarded component and appliance controls

- [x] 3.1 Define component action and operation documents with stable identifiers, availability/reason, current action token, requested/executing/reconnecting/succeeded/failed states, timestamps, and audit correlation.
- [x] 3.2 Implement staff-only restart and reboot endpoints backed by a fixed server registry; reject stale tokens, unadvertised actions, arbitrary unit names, paths, arguments, and non-staff callers.
- [x] 3.3 Implement the root-owned system-control helper with an internal enum-to-fixed-systemd-operation map and support delayed Open Cinema restart, orchestrator restart, and appliance reboot only.
- [x] 3.4 Add Ansible installation, ownership, sudo/policy authorization, self-check, and removal/rollback tasks for the helper; advertise actions only after the self-check succeeds.
- [x] 3.5 Persist or reconstruct enough operation state to distinguish expected self-restart/reboot disconnection from failure and to verify a new service-start or boot identifier after reconnect.
- [x] 3.6 Add unit, API, helper, permission, and Raspberry integration tests covering allowed actions, duplicates, stale state, absent permission, malicious identifiers, response-before-shutdown, reconnect, audit records, and failure reporting.

## 4. Persistent audio level domain and API

- [x] 4.1 Add versioned master audio state and logical-endpoint audio state models with neutral defaults, validation, timestamps, and migrations; keep them independent from graph revisions and temporary overrides.
- [x] 4.2 Define and expose desired master, endpoint, effective, observed, writable, applying/degraded, runtime-version, and update-version DTOs in the audio API schemas.
- [x] 4.3 Implement authenticated GET/PATCH master-level and endpoint-level resources with `If-Match`, normalized range validation, staff authorization, intent events, and consistent error documents.
- [x] 4.4 Extend endpoint candidate projection to distinguish observed volume/mute values from confirmed writable capabilities and preserve unknown/read-only state.
- [x] 4.5 Resolve logical endpoint mutations against the latest unique runtime candidate and reject unavailable, ambiguous, stale-generation, or read-only targets without accepting transient runtime IDs as durable input.
- [x] 4.6 Add model and API tests for defaults, persistence, validation, concurrency, disconnected preferences, input level, output level, mute, ambiguous binding, stale runtime, read-only capability, and event/audit output.

## 5. Audio level reconciliation

- [x] 5.1 Add desired effective-level calculation for active outputs (`master × endpoint level`, with either mute taking precedence) and endpoint-only level calculation for inputs.
- [x] 5.2 Add idempotent orchestrator actions that call WyrePlumber's confirmed volume/mute controls using current runtime identity and compare the requested and observed properties.
- [x] 5.3 Integrate level actions into transition ordering so required volume state is applied before a route is reported converged and failures produce actionable degraded state.
- [x] 5.4 Reapply level intent after active-output changes, Bluetooth reconnect, runtime-generation changes, orchestrator restart, and observed drift without repeatedly writing an already confirmed value.
- [x] 5.5 Publish level reconciliation progress and effective/observed state through runtime projections and event recovery so all clients converge after missed events.
- [x] 5.6 Add unit and integration tests for speakers → headset → speakers switching, multiple active outputs, endpoint-specific mute, master mute, input level, device recreation, write failure, retry bounds, drift repair, and orchestrator restart.
- [x] 5.7 Validate master and device controls with the physical main speakers, Bluetooth headset, and TV input on the Raspberry, including safe levels and route-change timing.

## 6. Managed resources and explanation contracts

- [x] 6.1 Define a stable managed-resource presentation DTO that correlates adapter definitions, processor health, and PipeWire-facing projections into one resource with name, kind, version, desired lifecycle, observed health, mode/profile, and technical evidence.
- [x] 6.2 Add capability action descriptors to managed resources, map existing managed-adapter restart with its update version, and keep CamillaDSP/decoder read-only until their supervisor exposes a safe restart intent.
- [x] 6.3 Add managed-resource API and schema tests for correlation, duplicate suppression, adapter restart advertisement, read-only processors, stale state, unavailable resources, and action reasons.
- [x] 6.4 Define the versioned human explanation presentation DTO with headline, route segments, selection trigger/reason, alternatives, signal changes, processors, overrides, transition, errors, and references to technical evidence.
- [x] 6.5 Generate presentation data alongside the existing deterministic resolver explanation without removing or rewriting the technical document.
- [x] 6.6 Add resolver/API tests for normal TV playback, encoded decode and channel adaptation, headset preference, speaker fallback, unavailable preferred output, inactive graph, waiting processor, transition, and failed reconciliation wording/data.

## 7. Shared TypeScript clients and UI foundations

- [x] 7.1 Add validated shared DTOs and clients for system overview, metrics, components, operations, master/endpoint levels, managed resources/actions, and explanation presentation, including unsupported contract errors.
- [x] 7.2 Extend orchestration event/store handling for volume, managed-resource, operation, and explanation updates with monotonic ordering and snapshot recovery.
- [x] 7.3 Add shared client/validation tests for successful documents, optional platform fields, action capabilities, read-only controls, stale versions, malformed payloads, and API-version mismatches.
- [x] 7.4 Build reusable Ant Design-based page heading/action, reserved status region, section skeleton, capability action, and value-with-freshness components with keyboard, focus, and `aria-live` behavior.
- [x] 7.5 Build an accessible token-driven SVG metric sparkline with bounded input, empty/stale behavior, light/dark themes, and text alternatives; do not add a chart dependency.
- [x] 7.6 Replace full-screen page spinners and conditionally inserted top-level alerts in the affected workflows with shell-preserving Skeletons and stable status regions.

## 8. Dashboard redesign

- [x] 8.1 Implement the responsive top status band showing overall appliance health, current human-readable audio route/format, and master level/mute with links to runtime details.
- [x] 8.2 Implement bounded CPU and RAM polling/history, visibility pause/resume, freshness detection, and compact temperature, storage, uptime, endpoint, and processor summaries.
- [x] 8.3 Implement system information and component version/health presentation with unsupported/unknown values, observation age, and drill-down links rather than raw identifiers.
- [x] 8.4 Implement coalesced master level/mute controls with immediate feedback, serialized writes, optimistic-concurrency handling, effective/observed state, and stable error/progress placement.
- [x] 8.5 Implement the separate System controls card with capability-aware Open Cinema restart, orchestrator restart, and reboot confirmations, duplicate prevention, expected-disconnection messaging, and bounded reconnect progress.
- [x] 8.6 Add dashboard unit and Playwright tests for normal, degraded, stale metrics, partial probes, read-only controls, volume race, restart/reboot reconnect, responsive layout, light/dark theme, keyboard use, and accessibility.

## 9. Devices and Managed resources UI

- [x] 9.1 Remove managed processor/resource tables from Devices and add a dedicated Managed resources navigation resource and route in `apps/admin` without changing `apps/ui`.
- [x] 9.2 Redesign Devices around logical endpoint name, direction, availability, concise capability/status, last seen, binding, and expandable human evidence while retaining unavailable endpoints.
- [x] 9.3 Add capability-aware device/input level and mute controls using logical endpoint state, coalesced writes, observed/effective details, disconnected preferences, and stable read-only/applying/error states.
- [x] 9.4 Replace selector and binding raw JSON in the normal Devices workflow with readable predicate/evidence descriptions, keeping raw documents in collapsed technical details.
- [x] 9.5 Build Managed resources groups for adapters and processors with lifecycle, health, version, profile/mode, freshness, expandable correlations, and actions derived only from server descriptors.
- [x] 9.6 Integrate existing adapter create/edit/enable/disable/delete/restart workflows into Managed resources or redirect the old Audio adapters route to a clear filtered view without duplicating menu concepts.
- [x] 9.7 Add unit and Playwright tests for device/resource separation, ROC adapter restart, read-only CamillaDSP/decoder, stale resource action, volume capability variants, binding, unavailable devices, row expansion, responsive layout, and accessibility.

## 10. Graph lifecycle and autosave

- [x] 10.1 Implement and unit-test a reducer/state machine for base document, local edit sequence, acknowledged sequence, draft identity, server update version, queued/in-flight saves, saved/pending/offline/failed/conflict states, and disposal.
- [x] 10.2 Route every graph mutation source—metadata, node create/delete/move/collapse/configuration, edges, public ports, parameters, conditions, subgraph bindings, and auto layout—through the same immutable local document dispatcher.
- [x] 10.3 Start or reuse a draft on the first mutation of a published revision while preserving all mutations made before draft creation returns.
- [x] 10.4 Implement bounded debounce, one in-flight save, latest-document queueing, acknowledgement sequencing, and stale-response handling so canonical responses never reset newer positions or values.
- [x] 10.5 Persist viewport and drag-stop node layout separately from transient runtime overlays and canvas drag frames, and restore it without automatic `fitView` overriding saved presentation.
- [x] 10.6 Flush the latest autosave before validation/publication/activation and preserve the existing safe Apply progress and prior-active-audio behavior on validation or activation failure.
- [x] 10.7 Implement offline retry and optimistic-conflict UI that preserves local content and offers review/export, reload remote, or supported copy recovery without silent overwrite.
- [x] 10.8 Replace unsaved-change language and unload prompts with a compact stable autosave status; warn only for pending, failed, offline, or conflicted local work.
- [x] 10.9 Add fake-timer/deferred-promise tests for first-edit draft races, move-then-field edit, edges, auto layout, response-after-newer-edit, rapid mutation coalescing, transient retry, conflict, refresh, unmount, and Apply during save.

## 11. Graph interaction redesign

- [x] 11.1 Implement one primary lifecycle-action selector: list/published inactive → Apply, list/published active → Deactivate, editable draft → Apply changes, and ineligible graph/subgraph → no executable live action.
- [x] 11.2 Make graph table rows keyboard- and pointer-navigable to the editor while preventing buttons, confirmations, menus, and links from also triggering row navigation.
- [x] 11.3 Keep graph nodes compact and visually consistent in selected/unselected state; remove the expanding selected-node toolbar and inline form-induced node resizing while retaining ports, summaries, badges, overlays, and validation markers.
- [x] 11.4 Build the responsive page-level Ant Design node inspector with structured metadata/configuration, contextual validation, confirmed clear/delete actions, and no per-node Save/Reload controls.
- [x] 11.5 Implement structured schema fields for primitives, enums/unions, bounded arrays, key/value maps, selector predicates, graph parameters, public ports, and subgraph parameter/port bindings.
- [x] 11.6 Keep lossless Advanced JSON only for unsupported/unstructured schemas, with explicit opt-in, parse/schema validation, error retention, and cancel semantics.
- [x] 11.7 Render graph palette and selection overlays outside the zoom transform with readable fixed viewport scale, content-fitting minimum width, maximum viewport dimensions, scrolling, and correct light/dark tokens.
- [x] 11.8 Add graph unit and Playwright tests for action exclusivity, active-draft Apply changes, row navigation, stable node dimensions, inspector editing, structured values, Advanced JSON fallback, menu dimensions at several zooms, keyboard flow, and accessibility.

## 12. Human runtime explanation and remaining layout fixes

- [x] 12.1 Redesign `PlanExplanation` into Result, Audio path, Why this route, Signal and processing, Transition, and collapsed Technical details sections using human names and presentation DTO data.
- [x] 12.2 Render missing dependencies, rejected alternatives, fallbacks, overrides, decoder format changes, channel adaptation, processor state, and reconciliation errors as actionable explanations rather than raw JSON alerts.
- [x] 12.3 Keep correlation IDs, runtime keys, stage documents, actions, and raw JSON in searchable/copyable collapsed technical details for debugging.
- [x] 12.4 Refactor Speaker test to keep selector, channel grid, and Stop area mounted while a reserved status region reports active/error/loading state; verify no channel button moves between states.
- [x] 12.5 Audit the remaining `apps/admin` pages for conditional alerts, full-screen spinners, action-order inconsistencies, raw JSON in primary workflows, overflow, unstable table actions, inaccessible labels, and responsive breakpoints; apply the shared patterns where the issue is observable.
- [x] 12.6 Add Playwright layout assertions and visual references for runtime explanation and speaker test inactive, starting, active, stopping, and failed states plus any additional audited fixes.

## 13. Documentation and acceptance

- [x] 13.1 Update backend API/OpenAPI documentation, runtime explanation documentation, volume semantics, system-control threat model, operator instructions, and deployment rollback notes.
- [x] 13.2 Update the UI README and reference-image README with navigation roles, dashboard/volume behavior, graph autosave status, inspector conventions, Advanced JSON policy, and visual review procedure.
- [x] 13.3 Run backend format/lint/type/test suites, migration checks, system API security tests, and orchestration recovery tests; fix all regressions.
- [x] 13.4 Run shared/admin type-check, lint, unit tests, production build, Playwright release tests, accessibility checks, and light/dark visual comparisons at desktop and narrow viewports; fix all regressions.
- [x] 13.5 Deploy to the Raspberry with actions initially unadvertised, validate telemetry overhead and audio-level reconciliation, then enable the helper and validate Open Cinema restart, orchestrator restart, and full reboot/reconnect.
- [x] 13.6 Complete end-user acceptance for dashboard daily operation, device/resource separation, global and device volume, graph row/action behavior, autosaved moves/values/edges, zoom-independent menus, human runtime explanation, and spatially stable speaker testing.
- [x] 13.7 Prevent fresh dashboard and graph event subscriptions from replaying retained transition history; add regression coverage and verify startup and first-node interaction timing on the Raspberry.
- [x] 13.8 Keep endpoint control tokens stable across unrelated runtime observations while rejecting recreated runtime targets; add regression coverage and verify a delayed live device-level write on the Raspberry.
- [x] 13.9 Restore the accepted TV/Bluetooth programme and speakers/headset priority graph, its disconnected logical endpoints, and required CamillaDSP profiles as a valid inactive published graph for UI acceptance without replacing active audio.
- [x] 13.10 Replace endpoint-selector candidate JSON with structured device, priority, eligibility, and ordering controls; remove the unsupported candidate-path socket; add regression coverage and deploy for acceptance.
- [x] 13.11 Audit every registered graph node; replace raw condition operators and the endpoint-reference, signal-contract, CamillaDSP, dynamic-group, and duplicate subgraph JSON shapes with focused Ant Design controls; add accessible hover descriptions, regression coverage, and deploy for acceptance.
