# Processor-management rollout acceptance — 2026-08-25

Status: **accepted for the experimental Raspberry Pi appliance**.

This acceptance covers rollout stage `processor-management` with one managed
CamillaDSP instance and one managed adaptive-decoder instance. Ordinary endpoint
routing and live reconciliation remain disabled and unaccepted.

## Deployed policy and readiness

The Pi at `192.168.1.37` was deployed with these effective flags:

| Flag | Value |
| --- | --- |
| orchestration API | `true` |
| runtime observation | `true` |
| shadow resolution | `true` |
| processor management | `true` |
| live reconciliation | `false` |

The complete playbook finished with `ok=182`, `changed=5`, `failed=0`. The
readiness role also passed as an independent tagged run with `ok=37`,
`changed=0`, `failed=0`. Open Cinema, the orchestrator, nginx, CamillaDSP, and
the decoder were all active after the final run.

The local Open Cinema suite passed after the processor-stage implementation:
**766 tests**. This includes the native processor drivers, rollout feature
gates, stable processor resource discovery, suspended-node availability,
deployment policy, and the stage probe.

## Managed processor contracts

The gated `probe_managed_processors` command exercised the production systemd,
CamillaDSP control, decoder status, and WyrePlumber link adapters as the
unprivileged `opencinema` service user.

| Instance | Accepted evidence |
| --- | --- |
| `decoder-0` | process active; lifecycle `ready`; status channel connected; protocol v2; single FLOAT32LE, 48 kHz, eight-channel adaptive output |
| `camilladsp-0` | native PipeWire configuration valid; control connected; engine reached `running`; requested and active configuration digest `5784c4b14629d3afa4ddc00186bafeefe9b293aa70ed3be6ef39c255dfda71da` |

The probe created eight processor-internal managed links from the decoder output
to the CamillaDSP capture, one per channel. CamillaDSP reached its readiness
contract once that clocked internal chain existed. The links are deliberately
owned by the probe's short-lived WyrePlumber connection and disappear when it
closes; `linksRetainedAfterProbe` is therefore `false`. Persistent internal
links belong to the long-lived orchestrator and are deferred to limited-live
stage 9.5.

PipeWire normally suspends unlinked native streams. Suspended processor nodes
remain stable, matchable resources whose links will wake them, so the runtime
projection now reports this idle condition as available rather than degraded.
The management projection reported both configured processors healthy after
the final run.

## Independent restart and rematching proof

Both units were restarted through systemd as `opencinema`, exercising the
narrow processor-only polkit authorization. Each subsequent probe rediscovered
the streams by stable node name and group, recreated only its eight temporary
owned links, and returned both processors to their readiness contracts.

| Checkpoint | Decoder capture/output IDs | CamillaDSP playback/capture IDs |
| --- | --- | --- |
| before restart | `135` / `139` | `99` / `103` |
| after decoder-only restart | `139` / `122` | `99` / `103` |
| after CamillaDSP-only restart | `139` / `122` | `154` / `105` |

The numeric runtime IDs changed only for the restarted processor. Stable names
remained `open-cinema.decoder.decoder-0.{capture,output}` and
`opencinema.camilladsp.0.{playback,capture}`. The final UI projections used the
new runtime keys while retaining the same four stable processor resource keys.

The deployed polkit rule grants only start, stop, and restart for
`camilladsp@*.service` and `pcm-auto-decoder@*.service`; it does not grant unit
enablement or arbitrary service management.

## Routing and binding confinement

After every probe connection closed and after both restarts:

| Mutation evidence | Result |
| --- | ---: |
| retained PipeWire links | 0 |
| applied plan states | 0 |
| transition journals | 0 |
| physical endpoint candidates | 1 |

The only physical endpoint candidate remained
`alsa_output.usb-Kencent_WONDOM_GAB8_5000000001-01.analog-surround-71`.
`Main Speakers` retained its exact Wondom selector and the deliberately absent
`Shadow programme input` retained no explicit binding. Managed processor nodes
did not appear as physical endpoint candidates.

## Failure action and rollback proof

The first processor-stage attempt exposed an incorrect pyCamillaDSP enum-state
mapping and could not prove CamillaDSP readiness. The managed probe instances
were cleaned up, the inventory was returned to `shadow`, and the rollback
playbook passed with no processor unit left active. After correcting and testing
the mapping and clocked probe chain, the appliance was advanced again and
accepted.

The current rollback target remains `shadow`. Limited live reconciliation is
not authorized until one long-lived orchestrator-owned input → decoder →
CamillaDSP → output chain passes safe transition, recovery, and audible checks.
