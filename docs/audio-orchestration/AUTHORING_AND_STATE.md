# Authoring desired audio behavior

Open Cinema saves intent, not a copy of the current PipeWire graph. A saved
graph may therefore reference a television, headset, processor, or subgraph
that is absent. Availability changes resolution state; it never deletes or
rewrites the saved graph.

## The four state planes

| Plane | Meaning | Durable | Owner |
| --- | --- | --- | --- |
| Desired | Published graph revision, activation parameters/scenes, logical endpoints, and temporary overrides | Yes | User/API |
| Resolved | Pure answer for one desired-state version and one coherent world version, including decisions and explanations | History is retained | Resolver |
| Applied | Last safely converged plan plus the durable transition journal and rollback state | Yes | Reconciler |
| Runtime | Current PipeWire/WirePlumber objects and processor observations using generation-scoped identities | No; bounded projections only | WirePlumber and processor drivers |

A `waiting`, `degraded`, `conflicted`, or `invalid` resolution is useful
diagnostic state, but it does not replace the last safe applied plan. A runtime
snapshot is observation, not desired configuration. Redis holds only lossy,
bounded projections and notifications; SQLite remains authoritative for
desired, resolved-history, and applied state.

Every plan exposes the desired revision and version, world generation and
sequence, transition generation, applied version, and a correlation ID. Use
those fields together; comparing a graph revision directly to a transient
PipeWire numeric ID is never valid.

## Graph authoring

A graph revision contains versioned metadata, typed parameters, nodes, edges,
conditions, and optional layout data. Node ports declare direction and a signal
contract: media kind, encoded or PCM content, format, rate, channel layout,
latency, codecs, and capabilities. Publication performs structural validation
without requiring referenced runtime endpoints to be connected.

Recommended authoring sequence:

1. Create logical input and output endpoints from stable observable evidence.
2. Define graph parameters for values that vary by room, instance, or scene.
3. Connect endpoint-reference, selector, processing, adapter, and output nodes.
4. Add conditions only from the published fact catalogue and choose an explicit
   unknown-result policy.
5. Validate or dry-run against a chosen world snapshot.
6. Publish an immutable revision, then atomically activate it with parameter and
   scene bindings.

Use an ordered selector for “headset if connected, otherwise speakers” or
“active Bluetooth programme, otherwise TV.” Priorities express policy; stable
declaration order or reference identity is the explicit tie-break. Fan-out and
mixing must be declared as such and cannot emerge accidentally from equal
selector priority.

## Reusable subgraphs and parameters

A subgraph declares public input/output ports, parameters, and mappings to its
internal nodes. A parent instance pins one published subgraph revision and
binds public ports and parameters. Expansion namespaces every internal node and
records whether a value came from a default, parent activation, instance
binding, scene, or temporary override.

Publishing rejects mutable or missing subgraph revisions and recursive cycles.
An upgrade is explicit: compare interfaces, dry-run all affected parents, then
publish parent revisions that pin the new subgraph revision. If a processor or
endpoint disappears, the pinned desired subgraph remains valid and resolves
again when the dependency returns.

## Logical endpoint selectors

Logical endpoints never persist PipeWire numeric object IDs. Prefer evidence in
this order:

1. Open Cinema managed identity;
2. hardware serial, Bluetooth address, or stable physical path;
3. route and profile identity;
4. stable node name;
5. descriptive properties only as constrained fallback evidence.

Selectors support exact, set-membership, and constrained safe-pattern
predicates. Candidate scoring is deterministic and explanations include
accepted/rejected evidence. Equal best matches remain explicitly ambiguous.
Choosing a runtime candidate in the UI derives a reviewable stable selector;
the selected generation-scoped runtime key is not stored as intent.

Tags and ordered groups express semantic policy such as `programme` or
`preferred-output`. They do not weaken selector identity and do not grant
ownership of external resources.

## Conditions and facts

Conditions are a bounded versioned JSON AST. Supported operations include
`all`, `any`, `not`, equality/inequality, numeric comparisons, membership,
existence, and stable duration. Evaluation is pure and three-valued: `true`,
`false`, or `unknown`. Every eligibility site must map `unknown` to eligible,
ineligible, waiting, or error explicitly.

Facts are namespaced and typed:

- `endpoint.*` for availability, active signal, capabilities, volume, and mute;
- `signal.*` for transport, content, codec, confidence, and actual decoded output;
- `processor.*` for health and declared processor observations;
- `parameter.*` and `mode.*` for activation, subgraph, and scene values;
- `resource.*` for bounded processor capacity;
- `override.*` for temporary control state and expiry.

Conditions cannot execute code, access arbitrary object attributes, or use
unbounded patterns. Unknown fact paths, type errors, excessive depth, excessive
node count, and oversized documents are publication errors with field paths.

## Processor contracts

Core adaptive decoder and CamillaDSP nodes, and processing-plugin nodes, expose
the same catalogue shape: typed ports, a serializable configuration schema,
resource needs, health/facts, pure validation/planning, and an idempotent driver
lifecycle. The decoder's observed output descriptor is authoritative; codec
names never substitute for actual sample rate or channel layout. CamillaDSP
profiles contain reusable processing only, while concrete buses and devices are
generated from the resolved plan.

Missing or unhealthy processors make the affected path waiting or degraded.
Their saved configuration remains opaque and intact. A plugin cannot register
an audio backend, discover the session independently, or take ownership of
endpoint routing.

## Reconciliation ownership

WirePlumber remains the only PipeWire session manager. Open Cinema normally
expresses one-to-one intent with configured defaults and per-stream
`target.object` metadata. Explicit links are restricted to declared fan-out,
mixer, or processor-internal shapes that metadata cannot express.

Only resources tagged with both the fixed Open Cinema owner and stable desired
ID may be cleaned up. External streams and links remain observable but are
never adopted, moved, or deleted unless the desired graph explicitly declares
the stream movable. Every mutation is fenced by a fresh runtime generation and
verified before the next transition phase.

See also [API_V1.md](API_V1.md), [DRIVER_ACTIONS.md](DRIVER_ACTIONS.md),
[ROUTING_MECHANISMS.md](ROUTING_MECHANISMS.md), and
[PLUGINS.md](PLUGINS.md).
