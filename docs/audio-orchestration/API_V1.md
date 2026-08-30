# Audio orchestration API v1

`/api/audio/v1/` is the stable HTTP boundary between Open Cinema's desired
audio model and its web clients. It deliberately keeps four representations
separate:

- desired resources are graph definitions, immutable published revisions,
  logical endpoint selectors, activations, and explicit overrides;
- resolved resources are immutable plans and explanations correlated with one
  desired-state version and one observed world version;
- runtime resources are current projections of transient PipeWire, processor,
  transition, and health state. Runtime keys are opaque and are never stored as
  durable endpoint identity.

The API is independently gated by
`OPEN_CINEMA_AUDIO_ORCHESTRATION_API`. When disabled, its routes remain
discoverable but return a `503 orchestration-api-disabled` problem. This does
not enable observation or any audio mutation flag.

## Contract discovery and version negotiation

Clients start with `GET /api/audio/v1/schema`. The response identifies API,
desired-graph, replay, and event schema versions and links to:

- `GET /api/audio/v1/schemas` for JSON Schema 2020-12 documents;
- `GET /api/audio/v1/openapi.json` for the OpenAPI 3.1 contract;
- `GET /api/audio/v1/node-types` for installed core, managed-processor, and
  processing-plugin node schemas.

Every response contains `Open-Cinema-API-Version: 1` and
`Open-Cinema-Schema-Version: 1`. A client may send
`Open-Cinema-API-Version: 1`; an unsupported value receives a 406 problem
instead of being interpreted as a compatible response.

Successful JSON uses
`application/vnd.open-cinema.audio+json;version=1` semantics. Errors use
`application/problem+json` and consistently include `type`, `title`, `status`,
`detail`, `code`, `instance`, and `apiVersion`. Validation details appear in
`errors` and optimistic conflicts also include `currentVersion`.

Collections accept `limit` and `offset`, with a maximum page size of 100, and
return an `items` array plus a pagination object. Resource-specific filters are
described by OpenAPI and rejected when their values are invalid.

## Optimistic writes

Mutable drafts, logical endpoints, and graph activations expose a numeric
version as an `ETag`. A modifying client must return that version in
`If-Match`, for example:

```http
If-Match: "3"
```

Missing preconditions return 428. A stale version returns 412 with the current
numeric version and makes no change. Publishing converts a draft to an
immutable revision. Published revisions can be compared, exported, resolved,
and activated, but never patched or discarded.

Graph and subgraph definitions share the same revision model. The
`/subgraphs` collection is a kind-constrained view of `/graphs`; a subgraph
cannot be activated as a top-level graph.

## Graph operations

The main operations are:

- `graphs`, `subgraphs`, and `graphs/{id}/revisions` for definitions and drafts;
- `revisions/{id}/validate` and `revisions/{id}/compare` for authoring feedback;
- `revisions/{id}/publish` and `revisions/{id}/activate` for explicit desired
  state changes;
- `revisions/{id}/export` and `graphs/import?dryRun=true` for portable bundles;
- `plans/dry-run` or `revisions/{id}/dry-run` for a complete resolver replay.

A dry run accepts the `open-cinema.resolver-replay/v1` document used by the
reproducible resolver fixtures. It invokes the side-effect-free resolver with
the installed node catalogue, reports the resolved document, explanation, and
version correlation, and explicitly reports `persisted: false` and
`audioMutated: false`.

## Endpoints and runtime inventory

Logical endpoints persist selectors, ordered tags and groups, policy metadata,
an optional explicit binding selector, and the last-known summary. Runtime
candidates are read separately from `/endpoint-candidates`.

`endpoints/{id}/candidates` explains each selector predicate, accepted and
rejected evidence, score, ambiguity, and the selected opaque runtime key.
`endpoints/selector-preview` performs the same calculation without changing
desired state. `endpoints/{id}/binding` turns an explicit runtime selection into
a reviewable durable selector; it never stores the numeric PipeWire node ID.
The response states that this is a persistent desired change and includes the
selector confidence, evidence, and warnings.

Normal authenticated users can see useful names, availability, capabilities,
route state, volume, mute, and matching evidence. Hardware addresses, serials,
object paths, sockets, credentials, and similar administrative properties are
recursively redacted. Only staff can download `/runtime/diagnostics`, which is
an explicitly administrative bundle.

## Persistent audio levels

`GET /levels/master` returns the persistent master output preference. Staff
clients update it with `PATCH /levels/master`, an `If-Match` header containing
the current `updateVersion`, and one or both of `level` (zero through one) and
`muted`. The response separates desired, effective, observed, applying, and
degraded state. Master level affects outputs only.

`GET` and `PATCH /endpoints/{logical-endpoint-id}/level` provide the same
optimistic contract for a logical endpoint. Outputs apply
`master level × device level`; either mute takes precedence. Inputs use only
their endpoint level and mute. The durable request always names the logical
endpoint. A client may return the displayed `runtimeVersion` when changing a
connected endpoint so a reconnect cannot redirect a stale gesture to a new or
ambiguous runtime candidate.

Disconnected preferences remain stored and are reconciled when a matching
device returns. `capabilities.volume.writable` and
`capabilities.mute.writable` describe confirmed runtime controls independently;
unknown or read-only values stay visible but cannot be mutated. Every accepted
write emits an intent/audit event, and convergence is reported through the
runtime projection and `volume` SSE event kind.

## Managed resources

`GET /runtime/resources` correlates managed adapter definitions, processor
health, and their PipeWire-facing projections into stable presentation rows.
Each row contains desired lifecycle, observed lifecycle and health, version,
mode/profile, freshness, technical correlations, and server-provided action
descriptors. Clients execute only an action whose `available` flag, `href`,
`method`, and update version were returned by the server.

ROC and debug-file adapters currently advertise the existing safe restart
operation. CamillaDSP and the adaptive decoder remain read-only until their
supervisor exposes an equivalent stable restart intent. A resource appearing
in runtime data is not by itself permission to synthesize a control URL.

## Plans, health, and degraded operation

`plans/current`, `plans/history`, and `plans/{id}` expose desired revision,
desired-state version, runtime generation/sequence, resolver status, applied
transition state, and correlation ID together. Their documents remain resolved
state and do not masquerade as runtime snapshots.

The technical resolver explanation remains intact. Its versioned
`explanation.presentation` companion is the human contract: a headline and
summary, ordered route segments, winning trigger/reason, rejected alternatives,
signal changes, processors, overrides, transition state, actionable errors,
and references back to technical stages. User interfaces should render this
presentation first and keep the technical document available for debugging. An
older plan without `presentation` is valid and should receive a clear fallback,
not client-side interpretation of arbitrary resolver internals.

`runtime/snapshot` may be filtered by projection type, subject, or world
generation. Separate resource and processor-health projections keep ordinary
views small. `runtime/readiness` always remains available while the API is
enabled. It reports whether desired editing, diagnostics, and live controls are
available, including every feature or health blocker. An absent WirePlumber or
processor projection is a visible degraded result rather than a reason to hide
desired graphs.

## Manual overrides

`overrides` creates and lists validated endpoint, scene, volume, mute, route,
and graph-parameter overrides. They have creator, priority, reason, start,
optional expiry, and cancellation state. Every representation includes:

```json
{
  "mutationKind": "temporaryOverride",
  "persistentDesiredChange": false
}
```

This prevents a temporary control from being confused with editing and
publishing a desired graph. A creator or staff member cancels an override with
`POST /overrides/{id}/cancel`; cancellation is idempotent and remains audited.

## Server-Sent Events

`GET /events` is an SSE stream. Its event kinds are `runtime`, `plan`,
`transition`, `endpoint`, `processor`, `health`, `volume`,
`managed-resource`, `operation`, and `explanation`. Clients resume with
`Last-Event-ID` or `after`, and may filter kinds with `types`.

A fresh stream without `Last-Event-ID` or `after` starts at the current event
tail and emits one `snapshot` with reason `initial-sync`; it never replays the
retained audit history into a newly opened page. If retention has removed events
after an explicitly requested cursor, the first data event is instead a
`snapshot` with reason `event-gap`. Both snapshots have
`replaceLocalState: true`, contain a consistent set of current runtime
projections, and advance the cursor to the newest retained event. Otherwise an
explicitly resumed stream replays retained events in sequence before live
polling continues. The stream sends keep-alives, disables reverse-proxy
buffering, and uses event sequence numbers as resumable IDs. `follow=false` is
provided for bounded diagnostics and contract tests.

The database remains authoritative. SSE and Redis notifications are hints;
clients recover by replacing runtime projections after a gap and ordinary
commands remain authenticated transactional HTTP requests.

## Appliance system API

Host observation and control are intentionally outside the audio namespace at
`/api/system/v1`. It uses the same authentication, CSRF, version-header,
problem-document, schema, and OpenAPI conventions.

- `GET /overview` returns independently fault-tolerant host identity, OS,
  kernel, boot, uptime, storage, CPU/memory summary, and optional Raspberry
  temperature/throttling fields with observation timestamps.
- `GET /metrics` returns a current CPU and memory sample for bounded client-side
  history; the server does not persist a metrics time series.
- `GET /components` returns the fixed component registry, versions, health,
  freshness, and capability action descriptors.
- `GET /actions` exposes appliance actions; `POST /actions/reboot` and
  `POST /components/{id}/actions/restart` require staff, CSRF, and the current
  signed action token.
- `GET /operations/{id}` reports the accepted operation and reconnect outcome.

Unsupported probes fail independently and are represented as unavailable
fields. No endpoint accepts a command, path, systemd unit, or arbitrary
component identifier from the client. See
[System controls and threat model](SYSTEM_CONTROL.md) for deployment and
operator details.
