## Context

See `proposal.md` for motivation and `specs/managed-audio-endpoint-adapters/spec.md` for observable behavior. The current ROC source and sink are PipeWire ROC modules loaded into a manually maintained interactive `pw-cli` process. The orchestrator is already the single long-lived controller, and WirePlumber inventory already observes the resulting `Audio/Source` and `Audio/Sink` nodes. Local probes confirm that the installed PipeWire tools can expose unconnected file playback and recording streams as source and sink endpoints by setting their media class and stable properties.

The first implementation must work locally without changing the deferred Raspberry Pi deployment change, preserve the existing management look and feel, and add no custom CSS.

## Goals / Non-Goals

**Goals:**

- Establish a reusable adapter-type boundary for resources that create endpoints, including future virtual or physical adapters.
- Persist desired adapter configuration while the orchestrator exclusively owns transient processes.
- Make ROC sender/receiver and looping PCM WAV source/recorder instances usable from the management UI and desired graphs.
- Preserve stable endpoint correlation across process and PipeWire restarts.
- Keep unsafe file and process parameters outside user-controlled command construction.

**Non-Goals:**

- Installing PipeWire ROC modules, firmware, codecs, or system services on the Raspberry Pi.
- Treating adapters as desired-graph processors or replacing logical endpoint binding.
- General arbitrary command execution or arbitrary filesystem access.
- Providing compressed-file decoding in the first driver; the initial debug source accepts PCM WAV and the type schema reports that constraint.
- Proving remote ROC receiver activity when the local module exposes no authoritative end-to-end status.

## Decisions

### Persist adapter definitions and observed lifecycle separately

Add a user-owned `ManagedAudioAdapter` desired resource with UUID identity, name, kind, schema version, configuration, enabled flag, restart generation, update version, and timestamps. Store orchestrator observations in a separate one-to-one runtime-state record containing lifecycle, health, PID, runtime generation, expected node name, correlated runtime key, retry data, progress, and last error.

Keeping observed writes out of the desired row prevents process polling from creating false optimistic-concurrency conflicts. A separate row also makes “configured but unavailable” explicit.

Alternative considered: model every adapter as a graph node. Rejected because an adapter creates an endpoint that graphs may reuse; its lifecycle and identity exist independently from any one graph revision.

### Use a backend adapter-type registry

Create a registry whose definitions provide kind, direction, schema version, JSON-style field schema, defaults, configuration validator, and driver factory. The API returns this catalogue and the UI renders forms from the same field metadata. The initial built-ins are `roc-receiver`, `roc-sender`, `debug-file-source`, and `debug-file-recorder`.

Alternative considered: four dedicated database models and UI forms. Rejected because future non-virtual adapters would repeat persistence, lifecycle, API, and UI code.

### Reconcile adapters inside the active orchestrator

An `AudioAdapterSupervisor` is created only by the active controller. On initial connection and every desired/runtime poll it loads visible enabled definitions, diffs a deterministic runtime fingerprint, and starts, restarts, observes, or stops exactly one owned runtime per adapter. It stops all owned children during controller shutdown. Unexpected exits use the existing bounded-backoff policy shape and persist their next retry time.

The web process only changes desired state and publishes the existing desired-state wake-up signal; it never launches audio processes. This preserves single-controller ownership.

Alternative considered: launching children in API requests. Rejected because web-worker restarts, multiple workers, and request timeouts would create unclear ownership and duplicates.

### Run ROC modules in supervised daemon-mode `pw-cli` children

For each ROC adapter, start one argument-vector-only process using `pw-cli --daemon load-module` with `libpipewire-module-roc-source` or `libpipewire-module-roc-sink`. The module lives in that child’s local PipeWire context and exports its endpoint to the main runtime. Terminating the child unloads only that adapter’s module.

Configuration generation uses a typed builder, never a shell. Stable properties include `node.name=open-cinema-adapter-<uuid>`, `node.description`, `node.virtual=true`, `node.network=true`, `open-cinema.owner=open-cinema.adapter-supervisor.v1`, `open-cinema.adapter.id=<uuid>`, and `open-cinema.adapter.kind=<kind>`.

Alternative considered: editing the global PipeWire configuration. Rejected for local iteration because it requires service restarts and makes per-instance start/stop and ownership harder.

### Keep one file-source node alive while looping PCM frames

Validate PCM WAV metadata with the standard WAV reader, then start `pw-cat` in playback mode with target `0`, explicit format/rate/channels/channel map, `media.class=Audio/Source`, and stable adapter properties. A bounded feeder thread repeatedly writes decoded PCM frames to the child stdin and seeks to the first data frame at EOF. Backpressure from `pw-cat` supplies audio pacing, and the PipeWire node does not disappear at loop boundaries.

The initial driver supports integer PCM widths representable by the installed tool and rejects unsupported encodings before process creation.

Alternative considered: repeatedly invoking `pw-play`. Rejected because the PipeWire node disappears briefly at every EOF and runtime identity churns unnecessarily.

### Record through an unconnected `pw-record` sink

Start `pw-record` with target `0`, explicit format/rate/channels/channel map, `media.class=Audio/Sink`, and stable adapter properties. The output is a PCM WAV below the configured media root. Stop sends an interrupt, waits for libsndfile to finalize the header, and escalates to termination only after a timeout. Existing files are preserved unless `replaceExisting` is explicitly set.

### Restrict files to an adapter media root

Add `OPEN_CINEMA_AUDIO_ADAPTER_MEDIA_ROOT`, defaulting to `<project>/media/audio-adapters` for local development. Store relative paths only. Resolve and compare canonical paths against the canonical root before opening. Source paths must be existing regular `.wav` files; recorder parents must exist or be created under the root, and collision policy is explicit.

Alternative considered: accepting absolute server paths. Rejected because the management API must not become arbitrary file read/write access.

### Correlate through WirePlumber rather than child-reported numeric IDs

The expected node name and adapter properties are durable correlation keys. The supervisor compares them with detached WirePlumber snapshots and records the current runtime key when present. Endpoint inventory adds `managedAdapter` origin metadata but continues to present these nodes as bindable endpoint candidates. Processor exclusion remains unchanged.

Local process readiness and endpoint readiness are separate phases: `starting` means the child lives but the node has not yet appeared; `ready` requires a matching runtime node. ROC network activity is reported only when observable.

### Expose REST resources under the versioned audio API

Add:

- `GET /api/audio/v1/adapter-types`
- `GET|POST /api/audio/v1/adapters`
- `GET|PATCH|DELETE /api/audio/v1/adapters/{id}`
- `POST /api/audio/v1/adapters/{id}/restart`

PATCH, DELETE, and restart use `If-Match`. Delete first requires the adapter to be disabled, preventing accidental removal of a running resource. Responses include separate `desired` and `observed` documents.

### Add a management page using the existing component system

Add an “Endpoint adapters” navigation resource and page in `apps/admin`. Use Ant Design table, tags, alerts, descriptions, forms, inputs, selects, switches, modal, and confirmation components already used elsewhere. The page consumes adapter type schemas for form fields, shows desired/observed state separately, and links a ready runtime endpoint to device discovery. No stylesheet or project-specific CSS is added.

### Represent graph deactivation as versioned desired state

Keep each graph's activation row after deactivation and add an explicit enabled state. The row retains the last published revision as an internal correlation target, while API graph and activation representations expose no active revision when disabled. Both activation and deactivation advance the same monotonic desired-state version and require `If-Match`; reactivating may select the retained or another published revision.

Expose deactivation as `DELETE /api/audio/v1/graphs/{id}/activation`. The operation does not delete the activation resource, graph definition, drafts, or published revisions. The durable disabled row acts as a tombstone that the desired-state monitor can observe and schedule exactly like an activation change.

For a disabled activation, live reconciliation creates an immutable cleanup plan correlated with the retained revision and new desired-state version, journals removal of every Open Cinema managed link whose desired identity belongs to that graph, and leaves other graphs' links untouched. Successful cleanup clears the graph's current applied plan and marks its applied state idle; failures remain retryable and visible. Repeated deactivation of an already disabled graph is idempotent when the precondition matches.

Alternative considered: delete the activation row. Rejected because deletion resets the externally visible desired-state version to zero, weakens stale-write detection, and removes the durable state needed to retry cleanup after a controller or runtime restart.

### Keep Apply independent from draft creation

Treat Apply as activation of a published revision, not as an editing operation. In the graph editor, a displayed published top-level revision can be activated directly through the existing revision activation API while Start draft remains a separate action. In the graph list, load the latest published revision summary for each top-level graph and offer an Apply action only when one exists. Applying from the list never publishes or modifies a draft.

Both entry points use the graph's current desired-state version for optimistic concurrency, show activation/reconciliation progress, and refresh graph state after conflicts. Applying an already active revision is allowed as an explicit reconciliation request and advances desired state normally.

## Risks / Trade-offs

- [A child dies before its endpoint is observed] → Persist `starting`, verify through fresh runtime snapshots, and retry only after bounded timeout/backoff.
- [ROC UDP ports collide] → Validate distinct ranges in configuration, surface child exit details, and keep the adapter in explicit error/retry state.
- [A large or fast-looping file consumes memory] → Stream bounded chunks from disk; never load the whole file.
- [Stopping a recorder leaves a corrupt WAV] → Send interrupt and wait for graceful finalization before forced termination; expose forced-stop errors.
- [SQLite receives frequent progress updates] → Throttle recorder progress persistence and update only materially changed status.
- [Adapter nodes could be auto-routed by session policy] → Use target `0` for file streams and explicit virtual/network properties; do not alter defaults or create links in the adapter driver.
- [The installed PipeWire version differs on the appliance] → Type readiness checks report missing binaries/modules; package/version pinning remains a deployment-change task.
- [A ROC module process is alive while the remote path is silent] → Report local readiness separately from network activity and avoid claiming end-to-end delivery.
- [Graph deactivation races with a newer activation] → Require the shared activation `If-Match` version and advance it atomically before scheduling cleanup.
- [Cleanup is interrupted] → Persist the disabled activation and journal graph-owned link removals so later reconciliation safely retries without touching another graph's links.
- [List Apply accidentally publishes an unseen draft] → Resolve only published revision summaries and call revision activation directly; draft publication remains exclusive to the editor's draft Apply workflow.

## Migration Plan

1. Add the persistent adapter and runtime-state tables; no legacy data migration is required.
2. Add registry, validators, drivers, supervisor, and API behind the existing orchestration API gate.
3. Add shared client contracts and the management page.
4. Create managed ROC adapters equivalent to the current manual source and sink, verify their endpoints and round trip, then stop the manual `pw-cli` owner.
5. Add the graph activation enabled state with existing activation rows defaulted to enabled; no legacy-data transformation is required.
6. Roll back by disabling managed adapters and restarting the previous manual ROC command; database rows can remain inert.
