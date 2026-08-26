# CamillaDSP Raspberry Pi capacity benchmark

Status: **hardware measurement pending**. The first-release deployment default
remains one managed instance until this procedure is run on every supported Pi
tier. Local/container timings are useful regression data but are not accepted as
appliance capacity measurements.

## Matrix

Run on the Raspberry Pi models and OS images listed in
`deployment/SUPPORTED_PLATFORMS.md`, using the exact coordinated PipeWire,
WirePlumber, CamillaDSP, decoder, and Open Cinema versions from
`deployment/compatibility.yml`.

Measure these workloads for one and two concurrent instances:

1. stereo 48 kHz passthrough;
2. stereo 48 kHz room-filter profile;
3. 5.1 48 kHz room-filter profile;
4. 5.1-to-stereo headset transition;
5. repeated stereo/5.1 reconfiguration under normal endpoint events.

Use representative production FIR lengths and IIR counts. Record the profile
digest and generated config digest with every sample.

## Measurements

- per-process and total CPU percentage at idle, median, p95, and maximum;
- resident memory per instance and whole-appliance available memory;
- capture-to-playback latency and xrun/drop counts;
- prepare, suppress, configure, route, verify, and unsuppress durations;
- audible gap duration, clipping, and pop/click observations;
- recovery time after CamillaDSP, PipeWire, and WirePlumber restart;
- temperature, throttling state, and clock frequency.

Collect at least ten minutes of steady state per workload and 100 format/layout
transitions. Preserve raw samples rather than only summary values.

## Acceptance record

For each Pi tier, record:

- hardware model, memory, power supply, cooling, kernel, and audio interface;
- coordinated component versions and commit IDs;
- exact configs and invocation;
- raw metric artifact paths and checksums;
- pass/fail against the agreed CPU, memory, latency, gap, and xrun limits;
- selected default instance count and rationale.

Only after this report is reviewed should task 16.9 be marked complete or
`camilladsp.instance_count` be raised above one for a supported production tier.

## Preliminary Raspberry Pi 5 observation — 2026-08-26

This is an interactive hardware observation, not the ten-minute/100-transition
acceptance run required above.

- Raspberry Pi 5 Model B Rev 1.1, 27 W supply and active fan;
- kernel `6.18.39+rpt-rpi-2712`, PipeWire 1.4.2, and CamillaDSP 4.1.3;
- TV IEC-61937/DTS input decoded to a stable 48 kHz, eight-channel float bus;
- WONDOM GAB8 eight-channel USB playback;
- CamillaDSP passthrough at 1024 frames had clearly visible lip-sync latency;
- bypassing CamillaDSP made the latency subjectively disappear;
- 256-frame and 128-frame CamillaDSP passthrough were both subjectively
  synchronized, with 128 frames selected for the active passthrough and headset
  profile revisions;
- at 128 frames, `pw-top` showed about 33 microseconds of CamillaDSP work per
  2.67 millisecond period and no steady-state CamillaDSP warnings during the
  short observation window;
- the Pi reported `throttled=0x0` and 48.8 degrees Celsius during the check.

Restart and link-attachment testing produced transient CamillaDSP queue-full
warnings. Open Cinema also needed multiple reconciliation catch-up passes before
all eight output links converged. The full benchmark must therefore measure both
steady state and restart/transition behavior; the short result does not yet
establish 128 frames as safe for production-length FIR filters.

### Corrected processor restart observation

After deploying `harden-processor-restart-reconciliation`, the same active
two-channel input → eight-channel decoder → eight-channel CamillaDSP → GAB8
graph was exercised with four restart boundaries. Recovery was sampled from the
PipeWire registry every 250 ms and required exactly 18 unique Open Cinema-owned
links: 8 DSP-to-output, 8 decoder-to-DSP, and 2 programme-ingress links.

| Restart boundary | Exact topology recovery | Minimum observed owned links | Result |
| --- | ---: | ---: | --- |
| CamillaDSP | 14.086 s | 0 | Passed |
| Decoder | 10.654 s | 8 | Passed |
| Orchestrator, including 6.547 s graceful service restart | 15.088 s | 0 | Passed after one classified early resource-readiness retry |
| CamillaDSP and decoder together | 13.226 s | 0 | Passed |

Every processor rebuild established all eight DSP-to-output links first, all
eight decoder-to-DSP links second, and the two programme-ingress links last.
Each transition then published `complete-topology-ready`, and the final applied
state was `converged` with no last error. No queue-full, drop, overrun, underrun,
xrun, panic, catch-up exhaustion, or graph-reconciliation failure matched the
combined processor/orchestrator journal window. The listener confirmed that
programme audio recovered automatically. The audible disturbance was difficult
to time but felt much shorter than the registry convergence interval—roughly
0.5 to 1 second—and included a brief noise burst. Automatic topology and audio
recovery are therefore accepted for these four cases. The short noise artifact
is retained as a follow-up quality issue rather than being treated as silent or
omitted from the acceptance evidence.

The post-test snapshot reported:

- CamillaDSP: 2.6% CPU and 16,736 KiB RSS;
- decoder: 2.5% CPU and 37,872 KiB RSS;
- Pi temperature: 46.1 degrees Celsius with `throttled=0x0`;
- 6,374 MiB memory available from 8,062 MiB total;
- ARM clock: approximately 1.6 GHz.

These are short point observations, not percentile measurements, so the
ten-minute workload and 100-transition capacity benchmark above remains open.
