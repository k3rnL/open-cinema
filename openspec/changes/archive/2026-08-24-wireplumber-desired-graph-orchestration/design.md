## Context

See `proposal.md` for motivation and the capability specs for behavioral contracts.

Open Cinema currently has four overlapping representations of audio behavior:

1. `KnownAudioDevice` records populated through selectable audio backend plugins.
2. A generic Django-model `AudioPipeline` graph with concrete device foreign keys, slots, edges, validation, and one-shot Celery apply/unapply jobs.
3. A separate CamillaDSP pipeline/mixer/filter model and manager.
4. PulseAudio-specific processing nodes that create modules or spawn `pcm-auto-decoder` and persist runtime PIDs/module identifiers.

The current `pipewire` branch begins using WyrePlumber for discovery but still registers PulseAudio and ALSA as backends, uses PulseAudio for volume and module operations, and targets WyrePlumber properties that do not match its actual API. The WyrePlumber project can already enumerate nodes, ports, metadata, modules, and typed SPA parameters, but it lacks a complete event stream and managed-link API. The decoder can distinguish PCM, AC-3, E-AC-3, and DTS and can observe decoded formats, but it communicates these facts only through logs. The UI has a useful React Flow editor but its graph DTOs have drifted from the backend.

This change is accepted first as a locally runnable product across the four application repositories. Raspberry Pi packaging, Ansible, coordinated releases, target-hardware limits, and appliance rollout are deferred to `deploy-raspberry-audio-appliance`; the local architecture must expose the contracts that deployment will later consume without including deployment acceptance here.

## Goals / Non-Goals

**Goals:**

- Preserve the product concept of persistent desired graphs, reusable subgraphs, and plugin-provided processing nodes.
- Establish one owner for each layer: Open Cinema for durable intent and product policy; WirePlumber for live session policy and PipeWire graph mechanics; processors for media transformation.
- Resolve desired intent continuously against transient endpoints, signal formats, processor health, and user overrides.
- Make decisions deterministic, explainable, versioned, testable, and safe to reconcile repeatedly.
- Preserve the existing `apps/admin` end-user management shell and its direct-manipulation graph workflow while adding simple rule-oriented configuration and advanced desired-graph features from the same underlying model.
- Treat endpoint references, routing/control nodes, subgraph instances, and processors as visibly and behaviorally distinct graph concepts.
- Remove the unused alpha audio models and competing runtime directly; no local
  device, pipeline, or CamillaDSP data requires preservation.

**Non-Goals:**

- Replacing WirePlumber with a custom PipeWire session manager.
- Reimplementing Bluetooth, ALSA, profile, route, or default-node policy already provided by WirePlumber.
- Making the desired graph a one-to-one persisted copy of every live PipeWire node, monitor port, or application stream.
- Requiring a native PipeWire rewrite of `pcm-auto-decoder` in the first migration stage.
- Building a general-purpose arbitrary-code rules language or permitting untrusted expressions.
- Requiring PostgreSQL for local acceptance; the architecture must keep desired-state storage portable while acknowledging SQLite concurrency limits.
- Implementing or accepting Raspberry Pi/Ansible deployment, hardware-specific defaults, release rollout, or appliance rollback.
- Building the future on-box external-display UI in `apps/ui`.

## Decisions

### 1. Layer product policy above WirePlumber session policy

Open Cinema will decide persistent intent, priorities, fallbacks, processing selection, scenes, and manual overrides. It will express routine runtime choices through WirePlumber defaults, target metadata, node properties, and managed processor nodes. WirePlumber will continue selecting/linking concrete runtime objects, maintaining routes, moving streams, and reacting to device lifecycle.

Open Cinema will create explicit raw links only for graph shapes that cannot be represented through standard target/default/filter policy, such as a direct source-endpoint to sink-endpoint appliance bridge, controlled fan-out, mixers, and fully managed processor internals. A direct bridge has no movable application stream on which target metadata could operate. Every explicit link will be labeled and reconciled as an Open Cinema-owned resource.

**Why:** This avoids two independent controllers continually correcting each other while retaining the dynamic session behavior and hardware support that motivated the WirePlumber migration.

**Alternatives considered:**

- Keep audio backend plugins and add PipeWire as another backend: rejected because PipeWire is the common runtime rather than one interchangeable hardware API.
- Disable WirePlumber policy and implement all links in Open Cinema: rejected because it recreates a session manager and loses established route/profile/Bluetooth behavior.
- Put all product rules in WirePlumber Lua: rejected because it splits durable user configuration and explanations across Python, Lua, and deployment files and makes web-driven changes harder to version.

### 2. Run orchestration in a dedicated singleton service

A dedicated `open-cinema-orchestrator` process will own the long-lived WyrePlumber connection, event consumption, world snapshot, resolver scheduling, processor drivers, and reconciliation loop. It will load Django settings/models but will not run inside Gunicorn workers or ordinary Celery workers.

The web API will persist desired changes transactionally and publish a lightweight wake-up notification. The database remains authoritative; notifications may be lost because the orchestrator also checks monotonic desired-state versions. Redis will carry wake-ups, ephemeral runtime snapshots, event fan-out, and UI updates. Celery remains available for unrelated background jobs and bounded offline work but is not the live graph authority.

**Why:** Gunicorn may have multiple workers and Celery may retry tasks on different processes, while the WirePlumber binding owns a dedicated event loop and runtime object lifetimes. A singleton controller gives mutations, ordering, and recovery one owner.

**Alternatives considered:**

- Reconcile entirely through Celery tasks: rejected because concurrent tasks and retry timing make live graph ownership ambiguous.
- Embed the connection in every API worker: rejected because it duplicates snapshots, subscriptions, and mutations.

### 3. Store immutable graph documents with normalized surrounding resources

The desired graph model will use immutable versioned JSON graph documents surrounded by normalized Django resources:

- `GraphDefinition`: stable identity, name, kind (`graph` or `subgraph`), ownership, labels.
- `GraphRevision`: immutable schema-versioned document, revision number, draft/published state, creator, timestamps, validation summary, content digest.
- `GraphActivation`: selects the published revision and parameter/scene bindings to reconcile.
- `LogicalEndpoint`: stable user-facing input/output identity, selector document, tags, direction, policy metadata, and last-known summary.
- `ManualOverride`: typed scope, value, priority, creation, expiry, and cancellation.
- `ResolvedPlan`: immutable result with desired revision, world version, expanded graph, selected paths, signal contracts, action intent, explanations, and status.
- `AppliedPlanState`: current/previous applied plan, transition phase, correlation ID, and convergence status.
- `OrchestrationEvent`: structured audit record.

Runtime PipeWire snapshots are ephemeral and versioned in the orchestrator/Redis; selected endpoint projections, health summaries, plans, and audit events are persisted. Raw high-frequency runtime events are retained only according to a bounded diagnostics policy.

**Why:** JSON documents fit plugin-defined nodes, nested graphs, immutable revisions, export/import, and whole-document validation better than Django multi-table inheritance. Normalized endpoint/activation/override/plan records retain queryability and referential intent.

**Alternatives considered:**

- Extend the current polymorphic Django node tables: rejected because each plugin field requires migrations, concrete inheritance complicates serialization, and immutable subgraph versions are awkward.
- Store everything including endpoints and status in one JSON graph: rejected because endpoint identity, matching, health, and overrides have lifecycles shared across graphs.

### 4. Use a versioned desired-graph document schema

Each graph document will contain:

- `schemaVersion`, graph kind, nodes, edges, declared parameters, public ports, and metadata.
- Node instance ID, registered node-type ID/version, configuration, parameter bindings, optional activation expression, and layout metadata.
- Edge source/target node and public port names plus optional activation expression and policy metadata.
- Subgraph instance references pinned to a definition/revision and parameter/public-port bindings.
- Endpoint reference nodes that point to logical endpoint IDs or endpoint-group selectors, never PipeWire numeric IDs.

Core built-in node types will cover endpoint references, exclusive selectors, fallback selectors, fan-out, mixer intent, conditional/bypass choice, subgraph instances, and explicit format adapters. Built-in and plugin-provided processors contribute additional node types.

The catalogue and editor distinguish four roles:

- **Endpoint references** select durable input or output intent and resolve to transient runtime candidates.
- **Processors** consume audio, transform or inspect it, and emit audio through typed ports. A processor may own a program such as CamillaDSP or `pcm-auto-decoder`, correlate that program's PipeWire nodes, and expose configuration, resource, lifecycle, and health state.
- **Routing/control nodes** express selection, fallback, fan-out, mixing, adaptation, or conditional behavior without masquerading as physical endpoints.
- **Subgraph instances** package any compatible combination of the preceding roles behind declared public ports and parameters.

A managed processor's PipeWire-facing nodes remain runtime implementation resources. They do not become user-configured logical hardware endpoints merely because they appear in the observed graph.

The backend owns canonical validation and normalization. UI layout remains non-semantic except where a graph explicitly models ordering.

### 5. Represent conditions as a safe typed expression AST

Conditions will use versioned JSON expressions rather than Python, JavaScript, or Lua source. Initial operators will include `all`, `any`, `not`, equality/inequality, numeric comparison, membership, existence, and stable-duration checks. Facts will come from a namespaced catalogue such as:

- `endpoint.<id>.availability`
- `endpoint.<id>.activeSignal`
- `signal.<node>.content.codec`
- `processor.<node>.health`
- `parameter.<name>`
- `mode.<name>`
- `override.<scope>`

Unknown facts use explicit three-valued evaluation (`true`, `false`, `unknown`). Each selector/branch declares how `unknown` affects eligibility. Stable-duration, debounce, and cooldown are evaluated by the resolver scheduler rather than arbitrary sleeps in graph nodes.

**Why:** A constrained AST is serializable, explainable, safe, migratable, and testable. Arbitrary scripts would make validation and deterministic explanations unreliable.

### 6. Resolve in pure deterministic stages

The resolver will be a side-effect-free library. Given one graph revision, parameter bindings, endpoint inventory snapshot, processor/signal facts, overrides, and resource policy, it will:

1. Load and recursively expand pinned subgraph revisions with cycle and depth checks.
2. Resolve parameter defaults and bindings with provenance.
3. Match logical endpoint references to eligible runtime candidates.
4. Evaluate node/edge conditions using the typed fact snapshot.
5. Resolve selectors, fallbacks, exclusive groups, fan-out, and mix requirements deterministically.
6. Propagate and negotiate signal contracts across processors and endpoints.
7. Enforce resource constraints such as available decoder/CamillaDSP instances.
8. Produce a canonical expanded resolved graph, action intent, status, warnings/errors, and an explanation tree.

Canonical sorting and explicit secondary tie-breaks ensure equivalent input produces the same plan digest. The resolver never reads the database, calls WirePlumber, starts processes, or configures CamillaDSP directly.

**Why:** Pure resolution allows exhaustive unit/property tests, dry-run comparison, reproducible bug reports, and safe shadow operation.

### 7. Treat desired, resolved, applied, and runtime state as separate versions

The orchestrator will correlate:

- Desired graph revision and activation version.
- World snapshot version.
- Resolved plan ID/digest.
- Applied plan ID/digest and transition generation.
- Latest observed runtime snapshot version.

New observations received during resolution or transition schedule the next generation. An older generation may finish only if its preconditions remain valid; otherwise it aborts before unsafe mutation or completes and is immediately superseded. API responses expose these versions so the UI can distinguish editing, resolving, applying, converged, and drifted states.

### 8. Reconcile through an action plan and driver interfaces

The planner converts resolved intent plus observed managed state into idempotent actions grouped into ordered phases:

1. `prepare`: create or locate processor resources and validate configs.
2. `suppress`: mute/fade/pause affected paths when required.
3. `configure`: apply decoder/CamillaDSP and format settings.
4. `route`: update default/target metadata and managed links.
5. `verify`: re-observe required nodes, parameters, links, and processor readiness.
6. `unsuppress`: restore intended mute/volume/fade state.
7. `cleanup`: remove obsolete Open Cinema-owned resources.

Drivers implement typed actions for WirePlumber, CamillaDSP, decoder processes, and future processors. Each action declares identity, preconditions, idempotency key, timeout, verification, inverse/safe fallback, and error classification. A transition journal persists phase and results before proceeding to irreversible or audible changes.

External drift is handled by ownership policy:

- Managed resources are restored to the resolved plan.
- User-movable application streams follow declared default/target policy.
- Unmanaged resources are observed but not deleted.
- A manual override becomes desired input rather than unexplained drift.

### 9. Extend WyrePlumber around snapshots, events, and managed control

WyrePlumber will remain a separate project and expose:

- Coherent snapshots for devices, nodes, ports, links, metadata, profiles/routes where available, parameters, and defaults.
- A bounded thread-safe event queue or subscription API for add/remove/change events without exposing unsafe GObject lifetimes across threads.
- Stable Python value objects detached from native proxies for events/snapshots.
- Runtime controls for writable parameters, metadata/default/target changes, and explicitly managed links.
- Connection generation, sequence numbers, overflow/gap indication, reconnect behavior, and clean shutdown.

The preferred Python integration is event consumption by the dedicated orchestrator thread/process. Callbacks from the native WirePlumber thread will enqueue detached event data while holding the GIL only for bounded conversion; application code will not execute inside the native callback.

The existing typed SPA object API will supply volume, mute, format, channel, and parameter values. Open Cinema will pin a released or exact tested WyrePlumber version rather than a stale development commit.

### 10. Match logical endpoints using ranked stable properties

Selectors are property predicates, but endpoint binding will provide recommended stable-property ranks:

1. User-assigned Open Cinema property or managed resource ID.
2. Hardware/device serial, BlueZ address, ALSA path, or equivalent stable device identity.
3. Route/profile plus device identity.
4. Stable node name within a known device.
5. Descriptive properties only as a last resort.

Matching returns candidate scores and evidence. Equal best candidates produce ambiguity. The UI can bind a candidate and preview the derived selector before saving. Runtime numeric IDs and object serials may appear in observations but are not durable selectors unless explicitly scoped to a runtime-only override.

### 11. Replace audio backend plugins with processing and application plugin contracts

The existing plugin loader will be separated into explicit contracts:

- `ApplicationPlugin`: optional routes, models, automations, and non-runtime integrations.
- `ProcessingPlugin`: node-type definitions, schemas, resolver validation/contract hooks, and one or more reconciliation drivers.

Plugins will register through an explicit registry/manifest and Python package entry point for external packages, with bundled plugins supported through the same interface. Import side effects and `__init_subclass__` alone will not be the authoritative registry.

A processing plugin cannot provide device discovery or replace the WirePlumber runtime. Plugin node configurations are schema-versioned JSON. Missing plugins preserve opaque node documents and make them unavailable rather than making graphs unreadable.

### 12. Integrate CamillaDSP as a processor profile and driver

CamillaDSP processing is represented by reusable `CamillaDSPProfile` resources. A CamillaDSP graph node references a profile and declares input/output signal contracts and resource requirements. During planning, the driver builds the concrete configuration using resolved endpoints, signal descriptor, graph parameters, filters, mixers, and target layout.

The driver validates configuration through CamillaDSP before transition, labels/stably identifies its PipeWire-facing streams, applies configuration through its control API, and reports readiness/active profile. A runtime resource policy declares available instances without hard-coding a particular local or future appliance limit into graph semantics.

The unused direct CamillaDSP models and APIs are deleted rather than carried
through a compatibility or conversion layer.

### 13. Give `pcm-auto-decoder` a versioned Unix-socket protocol

The decoder will remain a per-managed-node process initially and add a newline-delimited JSON protocol over a Unix domain socket. Messages include protocol version, instance ID, monotonically increasing sequence, timestamp, lifecycle, detection mode, transport descriptor, content codec, actual decoded descriptor, confidence, and structured errors. A status request returns the complete latest state so missed events can be recovered.

The processor driver will prepare configuration, start/stop a local managed instance, connect to its status socket, correlate its PipeWire streams through managed properties/names, and clean up only its own files/resources. Environment-specific service management uses the same driver contract and is defined by the separate deployment change.

The current libpulse path can connect to a local PipeWire Pulse compatibility service during development. Native PipeWire I/O remains a separate optimization; production compatibility-service configuration belongs to the deployment change and does not alter the processor contract.

### 14. Introduce versioned orchestration APIs

New endpoints will live under `/api/audio/v1/` and use shared DTO schemas:

- `graphs`, `graphs/{id}/revisions`, validation, publish, activation, export/import.
- `subgraphs` through the same definition/revision model.
- `node-types` processing/core schema catalogue.
- `endpoints`, matching candidates, binding, groups, and capabilities.
- `plans/current`, history, explanation, and dry-run resolution.
- `runtime/snapshot`, managed resources, and health.
- `overrides` with expiry/cancel.
- `events` using Server-Sent Events initially, with snapshot version and resumption token.

SSE is selected over WebSockets initially because updates are predominantly server-to-client and commands remain ordinary transactional HTTP calls. The API accepts optimistic revision preconditions for graph publication. Runtime snapshots may be filtered to keep the normal UI small.

The old `/api/devices`, pipeline, backend-preference, and direct CamillaDSP
endpoints are removed outright. No compatibility adapter or tombstone is
needed because there are no external users or stored configurations to retain.

### 15. Evolve the existing management console instead of replacing it

`open-cinema-ui/apps/admin` remains the complete user-facing management console. Its application shell, navigation, dashboard direction, device-discovery workflow, and React Flow editing foundation are preserved and adapted to `/api/audio/v1`. The name `admin` does not imply Django's staff-oriented admin application. `open-cinema-ui/apps/ui` returns to a minimal placeholder for the future display rendered on the physical home-cinema box.

The shared TypeScript package owns generated or manually verified DTOs for the `/api/audio/v1` contract. Existing UI components are adapted at their data boundary: obsolete backend selection, legacy API calls, and removed persistence DTOs are deleted, while the graph canvas, node cards, inline controls, toolbars, navigation, validation presentation, and device-discovery experience remain the visual and interaction foundation.

Before changing UI code, implementation runs the current `apps/admin` application and records reference views of the dashboard, inventory, graph list, graph canvas, representative nodes, selection/editing states, validation failures, and Save/Apply feedback. New work uses Ant Design/Refine components, their existing theme and layout facilities, and the graph library's established styling. It adds no Open Cinema-specific CSS stylesheet or handcrafted CSS rule; unavoidable vendor stylesheet imports remain vendor-owned. Visual comparison against the reference is part of acceptance, not a cleanup after functional implementation.

The editor provides explicit palette categories for inputs, outputs, processors, routing/control nodes, and reusable subgraphs. CamillaDSP and the adaptive decoder appear as insertable processor nodes, with their typed ports, schema-driven configuration, selected profile or mode, resource assignment, lifecycle, health, and resolved/runtime status visible without presenting them as hardware endpoints. Plugin processors use the same catalogue-driven UI.

The management console retains two deliberate commands:

- **Save** persists the current draft and its layout/configuration without publishing, activating, or changing live audio.
- **Apply** saves the current draft, requests canonical backend validation, publishes an immutable revision, activates it atomically, and follows reconciliation progress. Validation or activation failure leaves the draft available, keeps the previous active revision unchanged, and renders field, node, edge, and runtime errors in the established UI.

The device inventory remains a dedicated management workflow. It shows currently observed and known-unavailable logical endpoints, their candidates, capabilities, last-seen information, binding evidence, and runtime state. Managed processor ports may be diagnosed separately but are not offered as physical endpoint identities.

The optional rule-oriented projection presents scenes and readable `WHEN / THEN / OTHERWISE` behavior for common cases. It compiles to the same desired graph and does not replace advanced editing. The React Flow editor adds reusable subgraph instances, parameters, conditional branches, selectors, mixers/fan-out, and desired/resolved/runtime overlays while preserving its direct-manipulation design.

### 16. Test at three boundaries

Testing will be structured as:

- Pure unit/property tests: graph schema, subgraph expansion, conditions, endpoint matching, signal negotiation, deterministic resolution, action diffing.
- Contract tests: processing plugin schemas/drivers, decoder socket protocol, CamillaDSP configuration driver, API DTOs.
- Container/integration tests: PipeWire/WirePlumber events, defaults/targets, parameters, links, endpoint connect/disconnect, orchestrator restart/recovery, and end-to-end rule examples.

Recorded sanitized runtime snapshots and desired graph fixtures will make resolver failures reproducible without audio hardware. A canonical acceptance scenario covers TV-to-speakers fallback, Bluetooth input preference, headset output override, decoder format switching, and output-specific CamillaDSP selection.

## Risks / Trade-offs

- **[Risk] The local change spans four application repositories.** → Use versioned contracts, land read-only WyrePlumber/decoder capabilities first, pin compatible development revisions, and gate live reconciliation behind staged feature flags.
- **[Risk] WirePlumber APIs differ between supported development environments.** → Fail clearly on an incompatible WyrePlumber contract and isolate version-specific behavior in the binding; the production version matrix belongs to the deployment change.
- **[Risk] SQLite concurrency between Gunicorn, orchestrator, and Celery may produce lock contention.** → Keep live snapshots in memory/Redis, use short transactions and immutable append-style records, enable/test WAL where supported, and retain a documented PostgreSQL migration path if measurements require it.
- **[Risk] Event loss could produce an incorrect world model.** → Version connections/events, bound queues, signal overflow/gaps, periodically resnapshot, and always resnapshot after reconnect.
- **[Risk] Automatic routing can flap or surprise users.** → Require deterministic priorities, stable-duration conditions, debounce/cooldown, visible explanations, manual locks, and auditable transitions.
- **[Risk] Audio transitions can produce pops, silence, or format mismatches.** → Model transition phases explicitly, validate processors first, suppress affected output, verify before unsuppressing, and define safe fallback per graph.
- **[Risk] Plugin code can block or mutate runtime outside reconciliation.** → Narrow plugin contracts, execute lifecycle through drivers with timeouts, classify failures, and prohibit backend/session registration.
- **[Risk] JSON graph documents are less directly queryable than normalized nodes.** → Keep definition identity, revisions, activations, endpoints, plans, and audit records normalized; validate/index selected JSON fields only when proven necessary.
- **[Risk] Subgraph upgrades can create hidden incompatibilities.** → Pin immutable versions, validate public interface and parameter bindings, preview upgrades, and never update instances automatically.
- **[Risk] Decoder status may disagree with PipeWire-observed streams.** → Correlate by managed instance ID, retain both observations, prefer actual decoded-frame facts for content/output descriptors, and expose disagreement as degraded health.
- **[Risk] A single CamillaDSP instance may limit concurrent routes.** → Make resource capacity explicit in planning and surface conflicts; allow future multi-instance deployment without changing desired-graph semantics.
- **[Trade-off] Standard target/default metadata cannot express every arbitrary graph.** → Prefer it for ordinary routing and add explicit managed links only for clearly owned advanced routes.

## Migration Plan

### Phase 0: Baseline and safety

1. Confirm that the alpha database contains no device, pipeline, or CamillaDSP
   configuration that requires preservation, then permit a destructive schema
   reset for those models.
2. Add feature flags for new orchestration APIs, read-only runtime observation, shadow resolution, and live reconciliation.
3. Define supported WirePlumber/WyrePlumber versions and create end-to-end acceptance fixtures.

### Phase 1: Runtime observation without control

1. Extend and release WyrePlumber snapshots/events and fix typed property usage.
2. Add the singleton orchestrator and runtime health/snapshot APIs.
3. Build logical endpoint inventory/matching and UI diagnostics from
   WirePlumber runtime projections.

### Phase 2: Desired model and shadow resolver

1. Add graph definition/revision, endpoint, activation, override, plan, and audit models.
2. Implement schema validation, subgraph expansion, parameter binding, condition evaluation, endpoint matching, and deterministic resolution.
3. Run resolution in shadow mode, compare explanations against expected behavior, and make no audio mutations.

### Phase 3: Processor contracts

1. Introduce explicit processing/application plugin registries.
2. Add decoder status protocol and driver.
3. Add CamillaDSP profiles and implement the CamillaDSP driver.
4. Correlate processor streams with the runtime snapshot.

### Phase 4: Controlled reconciliation

1. Implement action diffing, journal, WirePlumber target/default controls, transition suppression, verification, retries, and rollback.
2. Enable live control for a limited acceptance graph and then the complete TV/Bluetooth/headset scenario.
3. Add explicit managed-link support only for scenarios that require it.

### Phase 5: Management UI evolution and legacy deletion

1. Restore the existing `apps/admin` shell, dashboard, discovery, graph editor, Save/Apply, validation, and error workflows on versioned shared DTOs.
2. Add first-class processor nodes, optional simple rules, subgraphs, explanations, and runtime overlays without moving the management experience into `apps/ui`.
3. Delete the unused legacy device, backend-preference, AudioPipeline,
   CamillaDSP, decoder-state, and Pulse module tables in one schema migration.
4. Delete obsolete backend implementations, mutation APIs, jobs, dependencies,
   and DTOs while retaining and adapting the useful management workflows and components.

### Phase 6: Complete local acceptance

1. Verify the canonical TV/Bluetooth/headset scenario, adaptive decoder behavior, CamillaDSP processing, and automatic reconciliation locally.
2. Verify no old backend, model, API, job, or dependency remains and no retained UI workflow calls a removed API.
3. Obtain explicit acceptance of the management console, including processor insertion, discovery, Save/Apply, validation, errors, and both graph projections.
4. Document the local plugin contracts and acceptance results, then hand the stable contracts to `deploy-raspberry-audio-appliance`.

### Rollback

- During local implementation, the orchestrator can remain read-only or shadow-only while the web API and desired-state editing continue operating.
- The deleted alpha audio records have no supported rollback path because they
  contain no user data. Local database snapshots may still be used while testing new desired state.

## Open Questions

- Which additional advanced graph cases require raw managed links in the local milestone versus a later milestone? Ordinary movable-stream output switching will use target/default metadata first; a graph-owned endpoint-to-endpoint appliance bridge uses explicit managed links because it has no movable stream.
- When should `pcm-auto-decoder` move from PipeWire Pulse compatibility to native PipeWire I/O? The processor and status contracts intentionally make this implementation choice deferrable.
