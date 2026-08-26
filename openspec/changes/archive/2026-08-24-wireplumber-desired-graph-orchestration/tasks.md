## 1. Establish the implementation baseline and compatibility contract

- [x] 1.1 [cross-repo] Record the coordinated baseline commits for `open-cinema`, `wyreplumber`, `open-cinema-ui`, and `pcm-auto-decoder` in the change implementation notes.
- [x] 1.2 [cross-repo] Confirm the alpha legacy audio database has no user data requiring preservation and record that destructive removal is permitted instead of building a compatibility migration.
- [x] 1.5 [open-cinema] Add independently configurable feature flags for the v1 orchestration API, runtime observation, shadow resolution, processor management, and live reconciliation; verify every flag combination starts without mutating audio unexpectedly.
- [x] 1.6 [open-cinema] Add a persistent orchestration schema/version marker and verify startup refuses an unsupported future schema without changing stored data.
- [x] 1.7 [cross-repo] Create the canonical TV/Bluetooth/headset/decoder/CamillaDSP acceptance fixture, with expected desired graph, world snapshots, resolved plans, explanations, and final runtime assertions.
- [x] 1.8 [cross-repo] Document the local compatibility contract between the four applications, including how incompatible binding, protocol, or API versions are detected before activation.

## 2. Complete WyrePlumber runtime observation

- [x] 2.1 [wyreplumber] Define detached immutable Python value objects for devices, nodes, ports, links, metadata, parameters, routes, profiles, defaults, and connection health; add serialization round-trip tests.
- [x] 2.2 [wyreplumber] Implement a coherent full snapshot with a connection generation, monotonic snapshot sequence, capture time, and all supported object relationships; test that referenced objects belong to the same generation.
- [x] 2.3 [wyreplumber] Normalize typed SPA parameter values for volume, mute, audio formats, rates, channels, channel positions, routes, and profiles; add fixtures from supported WirePlumber versions.
- [x] 2.4 [wyreplumber] Add detached events for object add/remove/change, parameter change, metadata/default change, and connection lifecycle; test each event from a controlled PipeWire graph.
- [x] 2.5 [wyreplumber] Add a bounded thread-safe event queue with sequence numbers and explicit overflow/gap indication; stress-test overflow without executing application callbacks on the native event thread.
- [x] 2.6 [wyreplumber] Implement reconnect generation changes, initial-resnapshot signaling, and clean shutdown; test WirePlumber stop/start and verify no stale native proxy escapes.
- [x] 2.7 [wyreplumber] Document thread ownership, snapshot consistency, event ordering, lifetime rules, and recovery semantics as part of the public binding API.
- [x] 2.8 [wyreplumber] Publish or pin a tested WyrePlumber release and add a compatibility test that Open Cinema can fail clearly when the binding contract is too old or too new.

## 3. Add WyrePlumber runtime controls

- [x] 3.1 [wyreplumber] Implement typed read/write operations for volume and mute with observed-value confirmation and tests for writable, read-only, and disappeared nodes.
- [x] 3.2 [wyreplumber] Implement metadata operations for default nodes and stream targets, including clear operations and ownership properties; verify changes appear in a subsequent coherent snapshot.
- [x] 3.3 [wyreplumber] Implement supported profile and route selection operations with precondition and postcondition reporting; test unavailable routes and concurrent device removal.
- [x] 3.4 [wyreplumber] Implement creation, lookup, and removal of explicitly managed PipeWire links labeled with stable Open Cinema identifiers; verify unmanaged links are never removed.
- [x] 3.5 [wyreplumber] Serialize all mutating operations through the binding event-loop boundary and add concurrency tests covering snapshot reads during mutations.
- [x] 3.6 [wyreplumber] Return structured, classifiable control errors for missing objects, invalid parameters, permission failures, timeouts, disconnection, and unsupported operations.
- [x] 3.7 [wyreplumber] Add integration tests proving target/default metadata is sufficient for ordinary stream moves and identifying the graph shapes that require explicit links.

## 4. Introduce orchestration persistence and immutable graph revisions

- [x] 4.1 [open-cinema] Add `GraphDefinition` with stable ID, name, kind, owner, labels, lifecycle timestamps, and authorization rules; add model and API permission tests.
- [x] 4.2 [open-cinema] Add immutable `GraphRevision` records with schema version, revision number, draft/published state, author, canonical content digest, validation summary, and uniqueness constraints.
- [x] 4.3 [open-cinema] Add `GraphActivation` with published-revision reference, graph parameter bindings, scene bindings, desired-state version, and atomic activation updates.
- [x] 4.4 [open-cinema] Add `LogicalEndpoint` with direction, selector, tags/groups, policy metadata, explicit binding, last-known summary, and optimistic update version.
- [x] 4.5 [open-cinema] Add expiring/cancellable `ManualOverride` records with typed scope, value, priority, creator, reason, start, and expiry.
- [x] 4.6 [open-cinema] Add immutable `ResolvedPlan`, `AppliedPlanState`, transition journal, and bounded `OrchestrationEvent` audit records with correlation identifiers.
- [x] 4.7 [open-cinema] Enable and test SQLite WAL, short transaction boundaries, and concurrent web/orchestrator access; document the measurement that would require PostgreSQL.
- [x] 4.8 [open-cinema] Add data-retention settings and cleanup jobs for plans, audits, diagnostics, and runtime projections without deleting desired revisions or current rollback state.
- [x] 4.9 [open-cinema] Add migrations, model factories, database constraints, and rollback-safe migration tests for every orchestration resource.

## 5. Define the desired-graph schema and node catalogue

- [x] 5.1 [open-cinema] Define the versioned canonical graph JSON schema covering metadata, parameters, public ports, nodes, edges, conditions, subgraph instances, and layout metadata.
- [x] 5.2 [open-cinema] Implement canonical normalization and digest generation so semantically equivalent documents have stable ordering and identical hashes; add property-based tests.
- [x] 5.3 [open-cinema] Implement import/export with schema-version checks, transactional creation, stable identifiers, and a dry-run validation mode.
- [x] 5.4 [open-cinema] Define core typed port and signal-contract vocabulary, including direction, media type, encoded/PCM distinction, rate, sample format, layout, latency, and optional capabilities.
- [x] 5.5 [open-cinema] Register built-in endpoint reference, ordered selector, fallback selector, exclusive choice, fan-out, mixer intent, conditional/bypass, subgraph instance, and explicit adapter node types.
- [x] 5.6 [open-cinema] Implement structural checks for node IDs, node-type availability, ports, edge direction, compatibility, duplicate edges, required connectivity, unsupported feedback cycles, and graph depth/size limits.
- [x] 5.7 [open-cinema] Implement typed graph parameter definitions, defaults, constraints, bindings, provenance, and validation for graph and subgraph instances.
- [x] 5.8 [open-cinema] Implement immutable published revisions, editable drafts, compare operations, optimistic publication, and atomic activation; test concurrent publication conflicts.
- [x] 5.9 [open-cinema] Preserve unknown plugin-node configuration as opaque data while marking the node unavailable; verify load/edit/export round trips do not lose fields.

## 6. Implement reusable parameterized subgraphs

- [x] 6.1 [open-cinema] Implement declared subgraph public inputs, outputs, parameters, and internal-to-public port mappings with schema validation.
- [x] 6.2 [open-cinema] Implement pinned subgraph revision references and reject mutable or missing revision targets during publication.
- [x] 6.3 [open-cinema] Implement recursive subgraph expansion with namespaced instance IDs, parameter provenance, public-port rewiring, cycle detection, and configurable maximum depth.
- [x] 6.4 [open-cinema] Add interface compatibility comparison for subgraph upgrades, reporting removed/changed ports, parameters, defaults, constraints, and affected parent bindings.
- [x] 6.5 [open-cinema] Add a dry-run subgraph upgrade operation that expands and validates every affected parent graph without changing pinned revisions.
- [x] 6.6 [open-cinema] Add unit and property tests for repeated instances, nested instances, independent overrides, diamond reuse, cycles, incompatible upgrades, and stable expanded digests.

## 7. Build logical endpoint inventory and deterministic matching

- [x] 7.1 [open-cinema] Map WyrePlumber snapshots into immutable runtime endpoint candidates without persisting PipeWire numeric IDs as durable identity.
- [x] 7.2 [open-cinema] Define safe selector predicates for exact, set, and constrained pattern matches across device, node, route, profile, direction, media class, and managed properties.
- [x] 7.3 [open-cinema] Implement ranked stable-identity evidence using managed ID, hardware serial/address/path, route/profile identity, stable node name, then descriptive fallback properties.
- [x] 7.4 [open-cinema] Implement deterministic candidate scoring and explicit ambiguity when equal best matches remain; include accepted and rejected evidence in diagnostics.
- [x] 7.5 [open-cinema] Derive a reviewable stable selector when a user explicitly binds an observed endpoint and reject selectors that depend only on transient numeric IDs.
- [x] 7.6 [open-cinema] Project discovered, route-available, selected, linked, active-signal, suspended, unavailable, ambiguous, and error states with last-seen data.
- [x] 7.7 [open-cinema] Project known formats, rates, channel layouts, profiles, routes, volume, mute, directions, and latency while preserving unknown values explicitly.
- [x] 7.8 [open-cinema] Implement endpoint tags and ordered groups used by desired graph selectors, with authorization and optimistic-update tests.
- [x] 7.9 [open-cinema] Reject delayed events from older runtime generations and trigger a full remap on overflow, sequence gap, or reconnect.
- [x] 7.10 [open-cinema] Add recorded-snapshot tests for USB, HDMI, ALSA, Bluetooth, headset, virtual processor, ambiguous, disconnected, and restarted endpoints.

## 8. Implement typed conditions and stable facts

- [x] 8.1 [open-cinema] Define the versioned JSON condition AST with `all`, `any`, `not`, equality, inequality, numeric comparison, membership, existence, and stable-duration operators.
- [x] 8.2 [open-cinema] Implement a namespaced fact catalogue for endpoints, signals, processors, graph parameters, modes, resources, and overrides with schema/type metadata.
- [x] 8.3 [open-cinema] Implement pure three-valued evaluation (`true`, `false`, `unknown`) and require each eligibility context to declare how unknown affects selection.
- [x] 8.4 [open-cinema] Reject unknown operators, unsafe patterns, invalid fact paths, type mismatches, excessive nesting, and oversized expressions with field-level explanations.
- [x] 8.5 [open-cinema] Implement stable-duration tracking from monotonic observations without embedding sleeps in graph nodes.
- [x] 8.6 [open-cinema] Add exhaustive truth-table, serialization, boundary, malformed-input, and deterministic-explanation tests for the condition engine.

## 9. Implement the pure deterministic resolver

- [x] 9.1 [open-cinema] Define immutable resolver inputs for graph revision, activation bindings, endpoint inventory, signal facts, processor health, overrides, resource policy, and world version.
- [x] 9.2 [open-cinema] Implement the pure resolution pipeline for subgraph expansion, parameter binding, endpoint matching, condition evaluation, path selection, signal negotiation, and resource allocation.
- [x] 9.3 [open-cinema] Implement deterministic priority, ordered fallback, exclusive selection, fan-out, and mix semantics with explicit secondary tie-breakers.
- [x] 9.4 [open-cinema] Apply scoped manual overrides as resolver inputs, including priority, expiry, cancellation, invalid targets, and persistent-versus-temporary behavior.
- [x] 9.5 [open-cinema] Produce canonical expanded graphs, selected/rejected paths, action intent, signal contracts, resource assignments, status, warnings/errors, and a structured explanation tree.
- [x] 9.6 [open-cinema] Distinguish `resolved`, `waiting`, `degraded`, `conflicted`, and `invalid` outcomes and document when each may remain the current plan.
- [x] 9.7 [open-cinema] Make equivalent resolver inputs yield identical plan digests and explanations across repeated processes; add randomized ordering tests.
- [x] 9.8 [open-cinema] Add snapshot fixture replay and a minimal reproducible bundle containing desired document, world state, policies, output plan, and version metadata.
- [x] 9.9 [open-cinema] Add property tests for unavailable endpoints, ambiguous candidates, competing priorities, fan-out resource conflicts, nested subgraphs, unknown facts, and expired overrides.
- [x] 9.10 [open-cinema] Implement shadow-resolution persistence and comparison without exposing any mutation action to runtime drivers.

## 10. Model adaptive signals and negotiate processing contracts

- [x] 10.1 [open-cinema] Define versioned signal descriptors that separately represent transport, encoded content, actual decoded output, confidence, source, and observation time.
- [x] 10.2 [open-cinema] Implement contract propagation and negotiation for media kind, codec, sample format, rate, channel count/layout, and processor constraints.
- [x] 10.3 [open-cinema] Implement explicit PCM bypass, encoded decode, passthrough, silence, and error choices for adaptive decoder nodes.
- [x] 10.4 [open-cinema] Prefer observed decoded-frame output over codec maximum assumptions and expose disagreement between decoder and PipeWire observations as degraded health.
- [x] 10.5 [open-cinema] Add resource-policy allocation for decoder and CamillaDSP instances, including deterministic conflict and priority reporting.
- [x] 10.6 [open-cinema] Implement configurable minimum confidence, detection window, hysteresis, debounce, stable duration, and cooldown in world-state scheduling.
- [x] 10.8 [open-cinema] Add fixtures for plain PCM, detecting/unknown, AC-3, E-AC-3, DTS, codec change, stereo-in-codec, unsupported codec, false preamble, and status failure.

## 11. Add the singleton orchestration service

- [x] 11.1 [open-cinema] Add an `open-cinema-orchestrator` entry point that loads Django settings but runs separately from Gunicorn and Celery workers.
- [x] 11.2 [open-cinema] Enforce one active controller per runtime installation with a process/service-level lock and visible standby/failure diagnostics.
- [x] 11.3 [open-cinema] Own one long-lived WyrePlumber connection and maintain an immutable versioned in-memory world snapshot with bounded Redis projection.
- [x] 11.4 [open-cinema] Consume detached binding events, coalesce related changes, detect sequence gaps, and obtain a fresh snapshot after overflow or reconnect.
- [x] 11.5 [open-cinema] Add database desired-version polling plus lossy Redis wake-up notifications so missed notifications cannot strand newer intent.
- [x] 11.6 [open-cinema] Correlate desired revision, activation version, world version, resolved plan, transition generation, applied plan, and runtime snapshot.
- [x] 11.7 [open-cinema] Abort stale generations before unsafe mutations and schedule a superseding generation when observations change during resolution or apply.
- [x] 11.8 [open-cinema] Publish bounded runtime, plan, progress, processor, and health events to Redis without making Redis authoritative for desired state.
- [x] 11.9 [open-cinema] Implement graceful shutdown, reconnect backoff, readiness, liveness, and startup resnapshot behavior; test database, Redis, PipeWire, and WirePlumber restart combinations.

## 12. Implement action planning and continuous reconciliation

- [x] 12.1 [open-cinema] Define typed driver actions with stable identity, preconditions, idempotency key, timeout, verification, inverse/safe fallback, and classified failures.
- [x] 12.2 [open-cinema] Implement a pure diff from resolved intent plus observed managed state to ordered `prepare`, `suppress`, `configure`, `route`, `verify`, `unsuppress`, and `cleanup` phases.
- [x] 12.3 [open-cinema] Persist transition phase and action outcomes before audible or non-trivial mutations and recover an interrupted journal after process restart.
- [x] 12.4 [open-cinema] Coalesce bursts and serialize mutations per graph/resource scope while allowing unrelated read-only diagnostics.
- [x] 12.5 [open-cinema] Skip already-satisfied actions and safely retry uncertain outcomes without duplicating processor instances, metadata, or links.
- [x] 12.6 [open-cinema] Implement bounded exponential retry and distinguish transient, permanent, stale-precondition, dependency, and safety failures.
- [x] 12.7 [open-cinema] Implement transition suppression using mute/fade/pause capabilities and require processor/runtime verification before unsuppression.
- [x] 12.8 [open-cinema] Implement safe rollback or declared degraded fallback when prepare, configure, route, or verify fails.
- [x] 12.9 [open-cinema] Restore Open Cinema-owned drift, respect declared target/default policy for movable streams, and observe but never delete unmanaged resources.
- [x] 12.10 [open-cinema] Persist auditable trigger, input versions, decision, actions, timing, errors, and final convergence status for each reconciliation generation.
- [x] 12.11 [open-cinema] Add crash/restart, event-storm, duplicate-action, stale-plan, partial-transition, rollback, and convergence tests with fake drivers.

## 13. Connect reconciliation to WirePlumber safely

- [x] 13.1 [open-cinema] Implement a WirePlumber driver adapter over the released WyrePlumber snapshot/control contracts with no native proxy retained outside the binding.
- [x] 13.2 [open-cinema] Implement confirmed volume/mute actions against logical endpoints and report unsupported or read-only controls without corrupting desired state.
- [x] 13.3 [open-cinema] Implement default-node and per-stream target actions as the first-choice ordinary routing mechanism.
- [x] 13.4 [open-cinema] Implement profile/route actions with endpoint-generation preconditions and post-change inventory verification.
- [x] 13.5 [open-cinema] Implement explicit managed-link actions only for planned shapes that target/default metadata cannot represent—including graph-owned endpoint bridges, fan-out, mixers, and processor internals—tagging every owned link and refusing destructive operations on unmanaged links.
- [x] 13.6 [cross-repo] Evaluate the canonical graph, direct endpoint bridge, and fan-out/mixer cases and record which first-release routes require raw managed links versus target/default metadata.
- [x] 13.7 [open-cinema] Add integration tests for headset connect/disconnect, Bluetooth source arrival, stream movement, default changes, volume/mute, PipeWire restart, and external unmanaged streams.

## 14. Formalize application and audio-processing plugins

- [x] 14.1 [open-cinema] Define explicit `ApplicationPlugin` and `ProcessingPlugin` manifests, registries, lifecycle, version compatibility, and Python package entry points.
- [x] 14.2 [open-cinema] Define processing node-type schema registration with identifiers, versions, display metadata, editable fields, ports, signal constraints, and configuration migrations.
- [x] 14.3 [open-cinema] Define side-effect-free plugin validation/planning hooks and typed reconciliation driver hooks for prepare, observe, activate, reconfigure, deactivate, and cleanup.
- [x] 14.4 [open-cinema] Isolate plugin import, schema, validation, planning, and driver failures so unaffected runtime observation and plugins remain operational.
- [x] 14.5 [open-cinema] Reject attempts to register device discovery, volume/mute ownership, session observation, or selectable audio backends and emit ownership diagnostics.
- [x] 14.6 [open-cinema] Expose plugin/node-type availability, health, configuration version, and incompatibility details through the orchestration catalogue and plan explanations.
- [x] 14.7 [open-cinema] Migrate bundled general plugins to the explicit application contract and verify their routes/models/automations work independently of audio processing.
- [x] 14.8 [open-cinema] Add contract tests for duplicate IDs, missing plugin, failed import, schema migration, opaque configuration preservation, driver timeout, and idempotent retry.

## 15. Add the pcm-auto-decoder status and management contract

- [x] 15.1 [pcm-auto-decoder] Specify a versioned newline-delimited JSON Unix-socket protocol with instance ID, sequence, timestamp, lifecycle, mode, transport, codec, decoded descriptor, confidence, and structured errors.
- [x] 15.2 [pcm-auto-decoder] Implement complete status request/response so a newly connected client can recover after missed events.
- [x] 15.3 [pcm-auto-decoder] Emit structured state only after configured detection confidence/hysteresis and include detecting/unknown rather than assuming PCM before classification.
- [x] 15.4 [pcm-auto-decoder] Report actual decoded sample rate, sample format, channels, and layout from produced frames and add codec fixture tests.
- [x] 15.5 [pcm-auto-decoder] Add managed PipeWire/Pulse stream properties or stable names that correlate capture/playback streams to the decoder instance.
- [x] 15.6 [pcm-auto-decoder] Add protocol compatibility, reconnect, sequence-gap, malformed-client, slow-client, socket cleanup, and graceful-shutdown tests.
- [x] 15.8 [open-cinema] Implement the decoder driver to prepare configuration, start/stop instances, consume status, resync, observe health, correlate streams, and clean up only owned resources.
- [x] 15.9 [open-cinema] Implement a development subprocess decoder driver with the identical protocol and contract tests against both drivers.
- [x] 15.10 [cross-repo] Document the native PipeWire I/O decision criteria and keep libpulse through PipeWire Pulse compatibility until a separately tested migration is justified.

## 16. Integrate CamillaDSP as a managed processor

- [x] 16.1 [open-cinema] Add immutable/versioned `CamillaDSPProfile` resources for filters, mixers, pipelines, device-independent parameters, and declared signal contracts.
- [x] 16.2 [open-cinema] Implement generation of concrete CamillaDSP configuration from profile, resolved endpoints, signal descriptor, graph parameters, and channel adaptation.
- [x] 16.3 [open-cinema] Validate generated configurations structurally and through CamillaDSP before they are eligible for an applied plan.
- [x] 16.5 [open-cinema] Implement the CamillaDSP driver for prepare, validation, activate, observe, safe reconfigure, deactivate, and owned cleanup with idempotency.
- [x] 16.6 [open-cinema] Expose connection, engine state, active configuration digest, input/output descriptor, warnings, readiness, and last failure as processor facts.
- [x] 16.7 [open-cinema] Coordinate CamillaDSP rate/layout changes with suppress, configure, verify, route, and unsuppress phases.
- [x] 16.8 [open-cinema] Add configurable runtime resource policy for one or more instances and deterministic resolution of incompatible concurrent requests without embedding appliance-specific limits.
- [x] 16.10 [open-cinema] Add contract/integration tests for stereo, 5.1, headset profile, bypass, invalid configuration, control disconnect, restart, resource conflict, and rollback.

## 17. Expose versioned orchestration APIs and live events

- [x] 17.1 [open-cinema] Publish `/api/audio/v1` schema metadata and consistent problem responses, authorization, pagination, filtering, and optimistic precondition conventions.
- [x] 17.2 [open-cinema] Add graph/subgraph definition, revision, validate, compare, publish, activate, import, export, and dry-run resolution endpoints.
- [x] 17.3 [open-cinema] Add the node-type catalogue endpoint with core/plugin schemas, availability, version, ports, signal constraints, and UI metadata.
- [x] 17.4 [open-cinema] Add endpoint inventory, candidate explanation, explicit binding, selector preview, group/tag, capability, and last-known endpoints.
- [x] 17.5 [open-cinema] Add current/history/dry-run plan endpoints with structured explanations and desired/world/resolved/applied/runtime version correlation.
- [x] 17.6 [open-cinema] Add filtered runtime snapshot, managed-resource, processor health, orchestration readiness, and diagnostic-bundle endpoints.
- [x] 17.7 [open-cinema] Add create/list/cancel endpoints for typed expiring manual overrides and clearly distinguish persistent desired changes.
- [x] 17.8 [open-cinema] Add resumable Server-Sent Events for runtime, plan, transition, endpoint, processor, and health updates with snapshot recovery after gaps.
- [x] 17.9 [open-cinema] Apply authorization and redaction so normal users see useful routing state while administrative properties and diagnostic exports remain restricted.
- [x] 17.10 [open-cinema] Generate and validate OpenAPI/JSON schemas and add API contract tests for supported versions, conflicts, unavailable runtime, reconnect, and future-version rejection.

## 18. Rebuild the web experience on the shared model

- [x] 18.1 [open-cinema-ui] Create the shared TypeScript orchestration DTO package from verified server schemas and fail clearly on unsupported API/schema versions.
- [x] 18.2 [open-cinema-ui] Add client state stores that keep desired revision, resolved plan, applied transition, and observed runtime representations separate and version correlated.
- [x] 18.3 [open-cinema-ui] Before another UI code edit, run and visually inspect the accepted pre-change `apps/admin` dashboard, navigation, device discovery, graph list, canvas, representative nodes, editing states, validation failures, errors, and Save/Apply feedback; capture reference views and record the reusable components and interaction patterns.
- [x] 18.4 [open-cinema-ui] Restore the product boundary: keep the full end-user management console, dashboard, navigation, and audio workflows in `apps/admin`, and return `apps/ui` to a minimal independent placeholder for the future on-box display.
- [x] 18.5 [open-cinema-ui] Restore and adapt the existing graph editor foundation—canvas, nodes, ports, inline fields, selection, toolbar, auto-layout, validation, and error presentation—to the v1 desired-graph DTOs instead of replacing it with a new editor experience.
- [x] 18.6 [open-cinema-ui] Use the existing Ant Design/Refine theme and layout primitives plus established graph styling for every revised view; add no project-specific CSS stylesheet or handcrafted CSS rule and verify light/dark theme consistency where already supported.
- [x] 18.7 [open-cinema-ui] Add distinct input, output, processor, routing/control, and subgraph palette categories, rendering CamillaDSP, adaptive decoder, and plugin processors with typed ports, schema fields, lifecycle, health, signal, profile/mode, and resource status.
- [x] 18.8 [open-cinema-ui] Integrate reusable CamillaDSP profile selection and editing into processor-node workflows without restoring the removed parallel CamillaDSP pipeline persistence model.
- [x] 18.9 [open-cinema-ui] Restore the dedicated device discovery/inventory workflow with connected and known-unavailable logical endpoints, capabilities, last seen, matching evidence, ambiguity, selector preview, binding, refresh, and separately identified managed processor resources.
- [x] 18.10 [open-cinema-ui] Implement Save so it persists graph content and layout only as a draft, reports field/node/edge/graph validation without activating audio, and handles optimistic conflicts while preserving the user's edits.
- [x] 18.11 [open-cinema-ui] Implement Apply as the explicit save, canonical validation, immutable publish, atomic activation, and reconciliation-following workflow; preserve the previous active revision on failure and present progress and errors using the established UI patterns.
- [x] 18.12 [open-cinema-ui] Implement SSE subscription, resumption, event-gap detection, full-snapshot recovery, and offline/degraded indicators without blocking draft editing.
- [x] 18.13 [open-cinema-ui] Add the optional readable `WHEN / THEN / OTHERWISE` rule view for priorities, fallbacks, scenes, and temporary/manual choices, round-tripping the same desired graph as the advanced editor.
- [x] 18.14 [open-cinema-ui] Add explanations showing triggers, winning/rejected alternatives, missing endpoints, signal/processor decisions, overrides, apply progress, and errors in the management console.
- [x] 18.15 [open-cinema-ui] Add subgraph create/insert, public interface, parameter binding, collapse/expand, pinned version, compatibility preview, and explicit upgrade workflows to the preserved graph experience.
- [x] 18.16 [open-cinema-ui] Overlay resolved selections, applied transition, processor health, and observed runtime status on the desired graph with a legend that prevents the representations being confused.
- [x] 18.17 [open-cinema-ui] Add component, schema-contract, Save/Apply, state-recovery, accessibility, and browser end-to-end tests plus reference-view visual review for discovery and simple/advanced graph workflows; fail review if the established look and feel regresses or custom CSS is introduced.

## 19. Delete unused legacy audio state and competing backends

- [x] 19.1 [cross-repo] Record the owner decision that no legacy audio data or external client requires preservation, compatibility, analysis, conversion, or rollback support.
- [x] 19.2 [open-cinema] Add one destructive schema migration deleting legacy device and backend-preference tables.
- [x] 19.3 [open-cinema] Delete legacy `AudioPipeline` graph, node, slot, edge, layout, job, and event models and tables.
- [x] 19.4 [open-cinema] Delete direct CamillaDSP pipeline, mixer, and filter models and tables while retaining v1 immutable CamillaDSP profiles.
- [x] 19.5 [open-cinema] Delete legacy decoder PID, Pulse module, pipe, tunnel, and runtime-state models and tables without copying transient identifiers.
- [x] 19.6 [open-cinema] Delete the migration analyser, conversion service, review endpoints, reports, fixtures, and compatibility tombstones.
- [x] 19.7 [open-cinema] Delete legacy device, pipeline, backend-preference, and direct CamillaDSP APIs and mutation managers.
- [x] 19.8 [open-cinema] Delete ALSA/PulseAudio/PipeWire backend implementations, backend iteration, discovery/apply Celery jobs, Pulse module lifecycle, and their Python dependencies.
- [x] 19.9 [open-cinema-ui] Delete only obsolete backend selectors, removed API adapters, legacy persistence DTOs/hooks, and migration-review UI; preserve or restore the dashboard, device discovery, graph editor components, processor/profile workflows, validation, errors, and Save/Apply experience on v1 contracts.
- [x] 19.10 [open-cinema] Delete the deprecated plugin shim while retaining explicit application and processing plugin entry-point contracts.
- [x] 19.11 [cross-repo] Verify source, generated schemas, routes, and production dependencies contain no competing backend or removed-model references.
- [x] 19.12 [cross-repo] Verify a fresh database migration, application plugins, processing plugins, v1 API, retained management workflows, and `apps/ui` placeholder after destructive legacy-data removal.

## 20. Validate local product behavior and safety

- [x] 20.1 [cross-repo] Run the canonical local scenario proving TV routes to main speakers by default, Bluetooth programme audio takes the intended source priority, and headset availability moves all configured audio to the headset.
- [x] 20.2 [cross-repo] Extend the canonical scenario to prove headset removal restores the correct previous/fallback output without editing or reapplying the desired graph.
- [x] 20.3 [cross-repo] Prove decoder PCM/AC-3/E-AC-3/DTS changes select or bypass decoding and choose output-compatible CamillaDSP profiles from actual decoded descriptors.
- [x] 20.4 [cross-repo] Prove desired subgraphs remain saved and structurally valid while endpoints/processors are absent and reconcile automatically when dependencies return.
- [x] 20.5 [cross-repo] Prove manual endpoint/scene/volume/mute overrides display scope and expiry, win according to policy, and revert deterministically when cancelled or expired.
- [x] 20.6 [cross-repo] Test event loss, queue overflow, Redis outage, database contention, WirePlumber restart, PipeWire restart, orchestrator crash, CamillaDSP failure, and decoder status failure with bounded recovery in the local integration environment.
- [x] 20.7 [cross-repo] Verify no unmanaged PipeWire resource is deleted, no stale plan overrides a newer generation, and failed transitions remain muted or use the graph's declared safe fallback.
- [x] 20.8 [cross-repo] Run authorization, untrusted JSON/schema, Unix-socket permission, plugin failure, sensitive-property redaction, and denial-of-service boundary tests.
- [x] 20.9 [cross-repo] Maintain a local integration environment with isolated PipeWire/WirePlumber, Redis, CamillaDSP or a contract fake, decoder fixtures, and no dependency on the developer's host audio session.
- [x] 20.10 [open-cinema] Set and enforce conservative configurable graph-size, subgraph-depth, condition-depth, event-queue, snapshot, diagnostic-retention, action-timeout, and retry bounds using local stress tests; leave hardware tuning to the deployment change.
- [x] 20.11 [cross-repo] Run explicit user acceptance of `apps/admin` dashboard/navigation, discovery, processor insertion and editing, Save/Apply, validation/errors, rule view, graph view, live overlays, and visual fidelity before declaring the local product complete.
- [x] 20.12 [cross-repo] Replace the prior acceptance report with a local-product report linking each non-deployment requirement to an automated test, visual check, or explicitly accepted limitation.

## 21. Document and close the local change

- [x] 21.1 [cross-repo] Document desired versus resolved versus applied versus runtime state, graph/subgraph authoring, endpoint selectors, condition facts, processor contracts, and reconciliation ownership.
- [x] 21.2 [cross-repo] Document movable-stream target/default routing versus explicitly managed endpoint bridges and advanced links so future contributors do not recreate a competing session manager.
- [x] 21.3 [cross-repo] Document plugin authoring for application and processing plugins, including schemas, migrations, pure planning, driver idempotency, health, timeouts, and prohibited backend ownership.
- [x] 21.4 [cross-repo] Document local operational diagnostics, plan explanations, audit correlation, and safe-mode/shadow-mode use.
- [x] 21.5 [cross-repo] Verify removed backend models, APIs, jobs, dependencies, flags, and adapters have no remaining references while every retained management workflow uses only v1 contracts.
- [x] 21.6 [cross-repo] Create follow-up changes for deferred native decoder PipeWire I/O, additional managed-link shapes, and multi-instance scaling that are not required for local acceptance.
- [x] 21.7 [cross-repo] Mark the local orchestration change complete only after the reopened UI tasks and explicit user acceptance pass; then provide its stable contracts as the prerequisite baseline for `deploy-raspberry-audio-appliance`.
