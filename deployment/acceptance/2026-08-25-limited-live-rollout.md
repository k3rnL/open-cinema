# Limited-live rollout acceptance — 2026-08-25

> **Status addendum (2026-08-27):** The
> [Open Cinema 0.3.2 closure](../../docs/release-readiness/2026-08-27-open-cinema-v0.3.2-closure.md)
> records the later full-runtime deployment, complete functional
> TV/Bluetooth/headset smoke, immutable release promotion, protected rollback,
> and no-op reapply. The exact limited-live checkpoint below remains historical
> staged-rollout evidence.

Status: **accepted for the experimental Raspberry Pi appliance**.

This acceptance covers rollout stage `limited-live` for one explicitly
allowlisted graph. It does not accept the full TV/Bluetooth/headset scenario,
the `full` rollout stage, or supported-release promotion.

## Controlled scope

The deployed environment enables live reconciliation and contains this exact
allowlist:

```text
OPEN_CINEMA_AUDIO_LIVE_RECONCILIATION=true
OPEN_CINEMA_AUDIO_LIVE_GRAPH_ALLOWLIST=[graph identifier redacted]
```

The accepted graph is `Limited live processor acceptance`, revision
`[revision identifier redacted]`. Its route is:

```text
managed looping WAV source
  -> adaptive PCM/encoded decoder (`decoder-0`)
  -> native-PipeWire CamillaDSP (`camilladsp-0`)
  -> Wondom GAB8 7.1 output
```

The source is a managed adapter whose appliance identifier is redacted.
It loops `debug-loop.wav`, remains `ready`/`healthy`, and exposes the stable
node name
`open-cinema-adapter-[identifier redacted]`.
The CamillaDSP profile is an immutable FLOAT32LE, 48 kHz, 7.1 passthrough
profile. The decoder accepts a stereo S16LE 48 kHz carrier and emits the stable
FLOAT32LE 48 kHz 7.1 working bus.

The obsolete `Shadow rollout probe` remains saved for inspection but is
disabled. Its original unavailable input selector was restored after the
allowlist confinement test.

## Deployment and resolver evidence

The full stage-changing playbook completed with `ok=182`, `changed=8`, and
`failed=0`. Subsequent application/readiness deployments completed with
`ok=73`, `failed=0`, including the explicit live mutation-scope assertion.

Before live mutation, the acceptance graph resolved in shadow mode with:

- exactly two matched endpoint bindings;
- all three route edges selected;
- `decoder:0` and `camilladsp:0` allocated;
- zero warnings and zero errors; and
- a current-plan policy permitting actions.

The shadow run exposed and prompted correction of graph isolation: an
unavailable endpoint saved for an unrelated graph previously degraded every
graph owned by the same user. Unrelated endpoints remain available as condition
facts and tag/group selector candidates, but no longer contribute bindings,
diagnostics, or actions unless the expanded graph references them.

## Live topology and channel semantics

The final PipeWire graph contains exactly 18 Open Cinema-owned active links:

| Edge | Links | Accepted channels |
| --- | ---: | --- |
| source → decoder | 2 | `FL`, `FR` |
| decoder → CamillaDSP | 8 | `FL`, `FR`, `FC`, `LFE`, `SL`, `SR`, `RL`, `RR` |
| CamillaDSP → Wondom | 8 | `FL`, `FR`, `FC`, `LFE`, `SL`, `SR`, `RL`, `RR` |

CamillaDSP's PipeWire ports report `UNK` channel labels. Initial live evidence
showed that an alphabetical fallback could preserve passthrough sound while
silently changing the channel index seen by channel-specific DSP filters. Live
planning now maps CamillaDSP `input_1..8` and `output_1..8` through the decoder's
declared layout. For example, `FL` maps to index 1, `FC` to index 3, `SL` to
index 5, and `RL` to index 7 before the labelled Wondom ports are selected.

The decoder reported a transition from unknown input to PCM. The adapter loop
counter advanced continuously, CamillaDSP reached its running/readiness
contract, and both processor runtime projections remained healthy.

## Restart, concurrency, and recovery

The first restart with corrected channel identities exposed a normal
optimistic-concurrency race: CamillaDSP state changes advanced the PipeWire
sequence between link actions. Action 9 was rejected as `stale_sequence`; the
failed transition and failed recovery were preserved in journal generation 2.

The WirePlumber adapter now handles only this specific race with bounded retry:
it recaptures the runtime, revalidates all generation-scoped node and port
identities, and uses a distinct native request ID for at most four attempts.
Generation changes, disappeared identities, ownership conflicts, dependency
failures, and other safety failures remain terminal.

After redeployment, connection-owned partial links disappeared with the old
orchestrator connection. The new orchestrator rematched stable processor
identities and recreated all 18 links. Applied state recovered from `failed` to
`converged`; subsequent restart journal generations completed successfully with
18 actions and no last error.

## Disable and reapply proof

The graph was disabled through the authenticated versioned API:

| Checkpoint | Desired-state version | Owned links | Applied state |
| --- | ---: | ---: | --- |
| before disable | 1 | 18 | `converged` |
| after disable | 2 | 0 | `idle` |
| after reapply | 3 | 18 | `converged` |

The unapply transition and reapply transition both completed successfully with
their own journals. Unapply removed only the 18 links tagged for this graph;
reapply reused the same published graph and stable logical/processor identities.

## Headless reboot proof

The first active-graph reboot correctly started the service user's headless
PipeWire session and the orchestrator, but intentionally did not mutate the
graph because `Main Speakers` no longer matched. The saved explicit binding
contained `api.alsa.path=surround71:0`; Linux assigned the same USB interface
card index 2 after reboot, producing `surround71:2`. The Wondom serial, USB bus
ID, PipeWire object path, and node name were unchanged. This demonstrated that
the numeric ALSA card index is discovery state rather than durable endpoint
identity.

Generated reviewable endpoint bindings no longer include `api.alsa.path`. The
real Wondom binding was regenerated from the current inventory and now uses
only its direction, media class, serial, USB bus ID, and stable PipeWire object
path. A regression test changes both `hw:N` and `surround71:N` while requiring
the generated binding to remain identical.

The repeat test rebooted between two distinct redacted boot identities with the
graph active. No graphical
login, Apply request, processor start, or post-boot service restart was used.
Systemd monotonic activation timestamps recorded this order:

| Resource | Active after kernel boot |
| --- | ---: |
| `user@999.service` (PipeWire/WirePlumber session) | 7.495 s |
| `open-cinema-orchestrator.service` | 14.015 s |
| `pcm-auto-decoder@decoder-0.service` | 15.080 s |
| `camilladsp@camilladsp-0.service` | 15.216 s |

The state-based poll observed the owned topology progress from 0 to 4, then 12,
then all 18 links. Applied state finished `converged` with no last error;
transition journal generation 8 finished `succeeded`/`completed` with 18
entries; and the looping source finished `ready`/`healthy`. The final topology
again contained 2 source-to-decoder, 8 decoder-to-DSP, and 8 DSP-to-Wondom
channel links. This accepts ordered, headless active-graph reboot recovery.

## Allowlist confinement

Limited-live now fails closed at both deployment and runtime boundaries:

- Ansible requires one or more exact graph UUIDs for `limited-live`.
- `full` requires the explicit `*` wildcard.
- non-live stages require an empty list.
- the orchestrator does not schedule a live generation for an active graph
  outside the configured list.

For the live negative test, the non-allowlisted saved graph was temporarily
given the healthy debug input and activated. Its desired-state version advanced
to 4, but it created zero links; the accepted graph remained the sole owner of
exactly 18 links. The test graph was then disabled at version 5 and its original
selector restored.

## Automated verification and remaining boundary

The final local Open Cinema suite passed with **778 tests**. Focused tests cover
graph isolation, natural-index channel mapping, bounded stale-sequence retry,
allowlist scheduling, rollout-policy enforcement, ALSA card-index churn, live
reconciliation, unapply, and restart recovery. `git diff --check` and Ansible
syntax checking also passed.

The current rollback stage is `processor-management`: set the local inventory
back to that stage and redeploy. Restarting the orchestrator closes its
WirePlumber connection, which removes the live connection-owned links; the
processor-management flags then prevent their recreation.

Task 9.6 remains open. Bluetooth programme input, headset takeover/fallback,
automatic format changes, hardware listening measurements, performance limits,
and the end-user management-console acceptance are not claimed by this report.
