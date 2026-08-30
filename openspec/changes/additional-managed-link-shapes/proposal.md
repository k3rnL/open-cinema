## Why

V1 intentionally uses WirePlumber target/default metadata for ordinary routes
and permits explicit owned links only for graph shapes that metadata cannot
express. Fan-out, mixers, channel-specific processor internals, and future
clock/latency adapters need separate acceptance so they do not expand Open
Cinema into a competing session manager by accident.

## What Changes

- Specify each additional topology shape and prove why metadata or a standard
  PipeWire filter node cannot represent it.
- Add typed graph nodes, port/channel contracts, planner actions, resource
  ownership, fresh-generation preconditions, verification, inverse, and safe
  fallback for accepted shapes.
- Extend WyrePlumber managed-link controls only where the detached runtime
  contract lacks necessary port/link detail.
- Add UI authoring and explanations that clearly distinguish policy intent from
  low-level managed topology.
- Add native/container tests proving unmanaged links are never adopted or
  deleted during creation, drift repair, or cleanup.

## Capabilities

### Modified Capabilities

- `desired-audio-graphs`: additional explicit advanced topology node shapes.
- `audio-route-resolution`: deterministic planning and signal negotiation for
  accepted fan-out/mixer/internal-link cases.
- `audio-reconciliation`: owned-link lifecycle and safe transition behavior for
  those cases.
- `wireplumber-runtime-control`: only the extra typed managed-link operations
  required by the accepted shapes.

## Impact

This change affects Open Cinema graph/resolver/reconciler code, WyrePlumber,
the advanced admin UI, and container/hardware acceptance. It does not alter
ordinary one-to-one routing and must not introduce generic “link anything”
session ownership.
