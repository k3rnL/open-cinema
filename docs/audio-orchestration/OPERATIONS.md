# Audio orchestration operations

Operate the appliance from correlated desired, resolved, applied, and runtime
state. Do not repair an incident by editing PipeWire links manually and then
persisting their numeric IDs: those objects are transient and WirePlumber owns
the session.

## Normal diagnostic path

1. Read `/api/audio/v1/runtime/readiness` to distinguish desired editing,
   observation, processor, and live-control availability.
2. Read `/api/audio/v1/plans/current`, then its explanation and correlation ID.
3. Compare desired revision/version, world generation/sequence, transition, and
   applied-plan fields using the correlation rules in `STATE_CORRELATION.md`.
4. Inspect the bounded runtime snapshot and endpoint candidate explanations.
5. Follow the same correlation ID through durable audit events and transition
   journal entries.
6. Only staff should download runtime diagnostics; stable serials, Bluetooth
   addresses, paths, and other sensitive properties are recursively redacted in
   ordinary API/event output.

The important plan states are:

- `resolved`: complete and eligible to apply;
- `waiting`: a dependency or fact is absent, so no new action is run;
- `degraded`: a declared fallback or reduced route is in use;
- `conflicted`: deterministic selection requires user intent;
- `invalid`: the desired revision itself must be corrected.

The last safe applied plan remains authoritative while a newer result is not
safe to apply. Never interpret “latest resolution” as “currently audible.”

## Contract-gated activation and shadow diagnostics

The appliance runs one accepted full-runtime profile and reconciles every
active graph. A changed coordinated candidate starts in a diagnosable non-live
state: API, runtime observation, and shadow comparison remain available, while
processor management and live reconciliation are disabled. The deployment
contract gate enables mutation only after every installed component probe
passes. A failed probe retains diagnostics and the rollback boundary without
rewriting graph revisions.

The application-level feature flags remain safety primitives for development
and fault tests, but appliance deployment does not expose a stage selector or a
per-graph scope. The mutation gate still requires runtime observation, shadow
resolution, processor management, and live reconciliation together, so partial
flag combinations remain non-mutating.

Shadow comparison records old/new status and digest, selected endpoints,
action-intent delta, and explanation delta without invoking a driver. A mismatch
is an investigation result, not permission to apply.

## Dependency incidents

| Symptom | Expected safe behavior | Operator action |
| --- | --- | --- |
| PipeWire/WirePlumber unavailable | Readiness false, reconnect with bounded backoff, fresh generation/snapshot before work | Inspect the user services and socket; do not reuse old runtime IDs |
| Redis unavailable | Degraded but database polling and in-memory runtime observation continue | Restore Redis; clients replace projections after a gap |
| SQLite busy/unavailable | Pause desired scheduling and report unready; no driver call in a DB transaction | Remove external long transactions and inspect lock timing |
| CamillaDSP control/configuration failure | Keep suppression or roll back the prior verified config | Inspect generated config and engine `--check`; do not unsuppress manually |
| Processor process healthy but audio silent after restart | Keep programme ingress suppressed unless every required current-generation port/link is verified; publish missing channel/link evidence | Inspect `processor-topology-transition` events and the applied-plan `lastError`; do not add links manually |
| Decoder status socket failure | Processor degraded/waiting with an explicit status error | Inspect the instance unit/socket and protocol version; next bounded observation reconnects |
| Orchestrator crash | Recover open journal entries by observing before retry | Restart the dedicated service and inspect recovery directives |

Event loss, queue overflow, sequence gaps, and generation changes always require
a coherent resnapshot. A stale plan may be stored for diagnosis but cannot cross
the unsafe-mutation fence.

## Local safety bounds

The application uses conservative finite defaults. They are application
settings, not Raspberry Pi tuning; hardware-specific adjustment belongs to the
separate deployment change.

| Boundary | Environment setting(s) | Local default |
| --- | --- | --- |
| Desired graph | `OPEN_CINEMA_AUDIO_GRAPH_MAX_NODES`, `_MAX_EDGES`, `_MAX_PATH_DEPTH`, `_MAX_DOCUMENT_BYTES` | 256 nodes, 1024 edges, depth 64, 1 MiB |
| Nested subgraphs | `OPEN_CINEMA_AUDIO_SUBGRAPH_MAX_DEPTH` | 8 |
| Conditions | `OPEN_CINEMA_AUDIO_CONDITION_MAX_DEPTH`, `_MAX_NODES`, `_MAX_GROUP_ARGUMENTS`, `_MAX_MEMBERSHIP_VALUES`, `_MAX_DOCUMENT_BYTES` | depth 16, 128 expressions, width 32, membership 64, 32 KiB |
| Reconciliation queue | `OPEN_CINEMA_AUDIO_RECONCILIATION_MAX_PENDING_GRAPHS`, `_MAX_CAUSES` | 256 graphs, 32 coalesced causes per graph |
| Runtime catch-up | `OPEN_CINEMA_AUDIO_RECONCILIATION_CATCHUP_MAX_PASSES`, `_RETRY_INITIAL_SECONDS`, `_RETRY_MAX_SECONDS`, `_RETRY_MULTIPLIER` | 8 immediate passes, 0.1–2 second bounded delayed backoff, multiplier 2 |
| Redis event hints | `OPEN_CINEMA_REDIS_EVENT_MAX_ENTRIES`, `_MAX_BYTES`, `_TTL_SECONDS` | 2000 entries, 64 KiB each, 1 hour |
| Redis runtime projection | `OPEN_CINEMA_RUNTIME_REDIS_MAX_BYTES`, `_MAX_ENDPOINTS`, `_TTL_SECONDS` | 256 KiB, 256 endpoints, 30 seconds |
| Diagnostics | `OPEN_CINEMA_AUDIO_DIAGNOSTIC_RETENTION_HOURS`, `_RETENTION_BATCH_SIZE` | 24 hours, 1000 rows per delete batch |
| Driver execution | `OPEN_CINEMA_AUDIO_ACTION_MAX_TIMEOUT_SECONDS`, `_MAX_ATTEMPTS`, `_MAX_RETRY_DELAY_SECONDS` | 30 seconds, 5 attempts, 30-second delay ceiling |

Invalid or unbounded values fail validation. Oversized desired input is rejected;
event bursts coalesce by graph and overflow explicitly; Redis projections are
truncated without becoming authoritative; driver calls and retries cannot exceed
the global ceilings.

For processor restart diagnosis, correlate the `processor-topology-transition`
phases in order: `preparing-processors`,
`processor-runtime-resources-ready`, `verifying-downstream-topology`,
`downstream-topology-ready`, `activating-programme-ingress`,
`verifying-complete-topology`, and `complete-topology-ready`. A terminal
`safely-suppressed` event includes the exact missing/mismatched channels and the
graph-scoped cleanup result. `reconciliation-catchup-retry-scheduled` indicates
that progress will resume from the event-loop deadline without requiring a new
runtime event.

## Backups, upgrade, and rollback

Deployment preflight validates the platform and all component contract ranges
before activation. Immediately before the destructive schema migration,
Ansible creates one operational rollback bundle containing the SQLite database,
managed processor configuration, exact migration plan, and coordinated
component versions. This bundle is not a legacy-data migration path.

After the new release passes end-of-play readiness, deployment keeps exactly
that one pre-deployment bundle, removes older successful-release bundles, and
records the closed previous window plus the currently open rollback boundary.
A failed migration or failed readiness never prunes rollback data.

To roll back:

1. stop Open Cinema, the orchestrator, Celery, and managed processor instances;
2. read the selected bundle manifest and deploy those exact coordinated
   component versions;
3. restore its database and owned processor configuration;
4. start PipeWire/WirePlumber, dependencies, web application, orchestrator, and
   processors in deployment order;
5. run the complete readiness role before enabling live reconciliation.

The rollback window closes when the next coordinated release succeeds and
replaces the retained bundle. The root rollback-window record is the durable
operator evidence of that boundary.

## Hardware acceptance

Before live reconciliation becomes the default, run the hardware inventory with
required HDMI, USB/S/PDIF, Bluetooth programme-source, and Bluetooth headset
node patterns enabled. Exercise cold boot, WirePlumber/PipeWire restart,
headset connect/remove, Bluetooth source priority, all supported encoded
formats, CamillaDSP profile changes, and rollback.

Record reconcile latency, audible switch gap, CPU, memory, SQLite wait time,
event throughput, and retained-history growth for each supported Raspberry Pi
tier. Conservative software bounds exist now, but final appliance values must
come from these measurements.

See [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md) for the current release gates
and `deployment/README.md` for installation and service commands.
