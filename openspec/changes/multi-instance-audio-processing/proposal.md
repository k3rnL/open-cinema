## Why

V1 has typed resource allocation and stable per-instance processor identities,
but its production default is intentionally conservative until Raspberry Pi
capacity and transition behavior are measured. Concurrent rooms, parallel
outputs, or overlapping decoder/CamillaDSP chains require an explicit resource
and performance design rather than merely raising an instance count.

## What Changes

- Benchmark one and multiple decoder/CamillaDSP instances on every supported
  Raspberry Pi tier, including CPU, memory, latency, audio gaps, and thermal
  behavior.
- Define per-processor capacity, exclusivity, sharing, idle reuse, priority,
  preemption, and safe reconfiguration policies from those measurements.
- Extend allocation and lifecycle reconciliation for concurrent graphs while
  preserving deterministic winners and stable instance identities.
- Add per-instance observability, limits, UI explanations, and deployment
  readiness/capacity checks.
- Retain a single-instance default on tiers that cannot satisfy the measured
  acceptance thresholds.

## Capabilities

### Modified Capabilities

- `audio-route-resolution`: measured multi-resource allocation and conflict
  policy.
- `camilladsp-graph-processing`: concurrent stable instances and explicit
  reconfiguration/capacity semantics.
- `audio-reconciliation`: fair serialized mutation across shared and independent
  processor scopes.
- `raspberry-audio-deployment`: tier-specific accepted instance limits and
  readiness checks.

## Impact

This change affects Open Cinema allocation/reconciliation, CamillaDSP and
decoder instance management, UI diagnostics, deployment defaults, and physical
Raspberry Pi benchmarks. It does not belong in the first-release acceptance
critical path.
