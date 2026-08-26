# Audio orchestration API v1

`/api/audio/v1/` is the stable HTTP boundary between Open Cinema's desired
audio model and its web clients. It deliberately keeps three representations
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

## Plans, health, and degraded operation

`plans/current`, `plans/history`, and `plans/{id}` expose desired revision,
desired-state version, runtime generation/sequence, resolver status, applied
transition state, and correlation ID together. Their documents remain resolved
state and do not masquerade as runtime snapshots.

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
`transition`, `endpoint`, `processor`, and `health`. Clients resume with
`Last-Event-ID` or `after`, and may filter kinds with `types`.

If retention has removed events after the requested cursor, the first data
event is `snapshot`. It has `replaceLocalState: true`, contains a consistent set
of current runtime projections, and advances the cursor to the newest retained
event. Otherwise retained events are replayed in sequence before live polling
continues. The stream sends keep-alives, disables reverse-proxy buffering, and
uses event sequence numbers as resumable IDs. `follow=false` is provided for
bounded diagnostics and contract tests.

The database remains authoritative. SSE and Redis notifications are hints;
clients recover by replacing runtime projections after a gap and ordinary
commands remain authenticated transactional HTTP requests.
