# Observation rollout acceptance — 2026-08-25

Status: **accepted for the experimental Raspberry Pi appliance**.

This acceptance covers rollout stage `observation` only. It does not authorize
shadow resolution, processor lifecycle management, or live graph mutation.

## Deployed policy

The Pi at `192.168.1.37` was deployed from
`deployment/rollout-stages.yml` with these effective flags:

| Flag | Value |
| --- | --- |
| orchestration API | `true` |
| runtime observation | `true` |
| shadow resolution | `false` |
| processor management | `false` |
| live reconciliation | `false` |

The Open Cinema API, orchestrator, Celery worker and scheduler, Redis,
PipeWire, WirePlumber, and PipeWire Pulse services were active. PipeWire and
WirePlumber ran in the headless `opencinema` user session.

## Runtime discovery

The orchestrator's bounded Redis projection was connected to PipeWire 1.4.2
and WirePlumber 0.5.8 with runtime generation 1 and sequence 2. It reported:

| Runtime object | Count |
| --- | ---: |
| devices | 20 |
| nodes | 4 |
| ports | 18 |
| links | 0 |
| endpoint candidates | 1 |

The discovered endpoint was the eight-channel
`WONDOM GAB8 Analog Surround 7.1` output. It was coherently reported as the
default output, suspended, unlinked, and without an active signal.

The management console returned HTTP 200 from `/admin/`. A normal authenticated
`admin` session returned HTTP 200 from both
`/api/audio/v1/runtime/snapshot` and `/api/audio/v1/endpoints`; the runtime was
available and the endpoint inventory contained the Wondom output.

## No-mutation proof

Two observations separated by ten seconds produced the same mutation state:

| Mutation evidence | Before | After |
| --- | ---: | ---: |
| PipeWire links | 0 | 0 |
| managed CamillaDSP/decoder instances | 0 | 0 |
| resolved plans | 0 | 0 |
| shadow comparisons | 0 | 0 |
| applied plan states | 0 | 0 |
| transition journals | 0 | 0 |

The database also contained no graph definitions, graph revisions,
activations, or managed adapters before advancing the rollout. The Pi reported
`throttled=0x0` during the acceptance check.

## Decision and rollback

Observation meets the stage success criteria: runtime discovery is healthy and
visible to the management console, while the controller creates no plans,
transitions, managed processors, or PipeWire links. The rollback remains the
`disabled` stage. The next stage may be selected only after shadow execution is
connected to the orchestrator and tests prove that it cannot emit driver
actions.
