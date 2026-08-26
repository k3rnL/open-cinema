## Why

Raspberry Pi hardware testing exposed a restart race in which managed processors reappeared with new PipeWire identifiers while only part of an eight-channel route was restored. Reconciliation eventually converged, but it could leave silence, expose a partial topology, flood CamillaDSP buffers, or stall until another runtime event, so the existing restart-safety contract is not yet met.

## What Changes

- Treat a managed processor topology as one verified transition group: suppress the affected path before mutation, wait for the processor's complete required port set, reconcile every required link, verify the resulting topology from a fresh runtime snapshot, and only then expose the path.
- Make runtime-generation changes and processor restarts invalidate stale observations and action preconditions without allowing a partially applied route to be reported active.
- Guarantee a bounded self-scheduled retry after catch-up exhaustion or a changing runtime, even when no further WirePlumber event arrives.
- Preserve idempotency when links already exist or disappear during a retry, and clean up only graph-owned links.
- Publish actionable waiting, degraded, and failure evidence for processor readiness, missing ports, incomplete links, retry exhaustion, and recovery.
- Add deterministic regression tests for eight-channel partial-link races, processor identifier replacement, continuously advancing snapshots, quiet runtimes after catch-up exhaustion, and service restart recovery.
- Re-run processor and orchestrator restart acceptance on the Raspberry Pi and record convergence time, audible gap, and processor warnings.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `audio-reconciliation`: strengthen ordered-transition, verification, retry, and lifecycle-reporting requirements so a processor route converges as a complete topology and cannot stall after runtime churn.
- `camilladsp-graph-processing`: strengthen restart and reconfiguration behavior so all declared channels are ready and linked before CamillaDSP output is exposed.

## Impact

This change affects the orchestrator reconciliation loop, action planning and execution, managed processor observation/lifecycle handling, runtime status evidence, and their unit/integration tests. It also affects Raspberry Pi acceptance evidence and deployment task status, but introduces no desired-graph schema or public API compatibility break.
