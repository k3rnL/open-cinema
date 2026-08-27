# Interrupted transition recovery — 2026-08-25

Status: **accepted for the experimental limited-live Raspberry Pi appliance**.

This test exercised a controller process loss during a real 18-link graph Apply.
It is intentionally a power-loss-style controller-boundary test, not a claim
that the whole appliance was electrically disconnected. PipeWire, WirePlumber,
the processors, and the physical Wondom output remained running while only the
orchestrator was killed without cleanup.

## Test procedure

1. Disable graph `[private UUID redacted]` through the
   authenticated, versioned audio API at desired-state version 3.
2. Observe its 18 Open Cinema-owned links being removed and require the owned
   link count to reach zero.
3. Re-activate published revision
   `[private UUID redacted]` at desired-state version 4.
4. Poll PipeWire while the transition is running. At `19:46:35.933 UTC`, after
   two of the expected 18 links existed, send `SIGKILL` to only the main process
   of `open-cinema-orchestrator.service`.
5. Observe the runtime and database through systemd's automatic controller
   restart and the subsequent reconciliation.

## Evidence

| Check | Observation | Result |
| --- | --- | --- |
| Precondition | Deactivation removed links incrementally from 18 to 0 | passed |
| Real interrupted mutation | Apply created 2/18 links before controller PID `9947` was killed | passed |
| Connection-owned cleanup | The first post-kill PipeWire snapshot contained 0 Open Cinema-owned links | passed |
| Bounded service recovery | systemd recorded the signal failure, waited the configured 2 seconds, and started PID `11317` | passed |
| Fresh runtime evidence | Startup recovery used runtime generation 1, sequence 2 from the new native connection | passed |
| Interrupted journal | Generation 25 was recovered with its last started action marked `uncertain`, then terminally `cancelled` | passed |
| Safe cleanup proof | Recovery outcome was `interrupted-controller-boundary-clean` with `remainingOwnedLinkIds: []` | passed |
| Audit trail | A warning `transition-startup-recovery` event correlated journal generation 25 and its fresh runtime evidence | passed |
| Desired-state recovery | Generation 26 started from persisted activation version 5 and succeeded with 18 actions | passed |
| Final state | 18/18 owned links, `AppliedPlanState.status=converged`, and `last_error=null` | passed |

The interrupted journal contained two completed actions and a third action whose
outcome had not been persisted. On startup, the new controller first marked the
third action uncertain, checked the new PipeWire connection, and proved that no
resource owned by the dead connection remained. Only then did normal desired
state reconciliation rebuild the graph. This separates evidence about the old
transition from the new successful generation instead of silently overwriting
the interruption.

## Implementation completed for this acceptance

The existing journal store could identify incomplete transitions, but production
startup did not invoke it. `StartupTransitionRecovery` now runs after the first
authoritative runtime capture and before reconciliation. It terminally closes
interrupted journals, records the fresh runtime generation and sequence, checks
for graph-scoped owned links, updates an applying state to an explicit degraded
or failed state, and emits a correlated audit event. The ordinary reconciliation
loop can then create a separate generation from persisted desired state.

The accepted safety boundary relies on managed PipeWire links being owned by the
orchestrator's native connection. Killing that connection removes partial links;
the startup check fails closed if graph-scoped owned links unexpectedly remain.

After recovery, the independently tagged readiness play completed with
`ok=38`, `changed=0`, `unreachable=0`, and `failed=0`.
