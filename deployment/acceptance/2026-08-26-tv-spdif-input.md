# Physical TV SPDIF/I2S acceptance — 2026-08-26

> **Status addendum (2026-08-27):** The
> [Open Cinema 0.3.2 closure](../../docs/release-readiness/2026-08-27-open-cinema-v0.3.2-closure.md)
> records the later owner-accepted TV/encoded/CamillaDSP and complete
> TV/Bluetooth/headset functional smoke. The pending-scenario wording below is
> retained as the point-in-time boundary; quantitative characterization still
> remains separate and open.

Status: **physical input and managed processing path accepted; final subjective
lip-sync and complete TV/Bluetooth priority scenario pending**.

## Fixture and route

- Raspberry Pi 5 8 GB appliance with the external SPDIF-to-I2S board exposed as
  ALSA `I2Sout` capture device 1.
- WirePlumber selects the device's Pro Audio profile and publishes its stereo
  capture node as `TV SPDIF input`; no PulseAudio compatibility module is used.
- The already-applied desired graph resolves the physical TV input through the
  native single-output PCM auto decoder and CamillaDSP 4 to the eight-channel
  Wondom main-speaker output.
- The user heard live TV PCM and then heard a movie using a supported encoded
  format. Unsupported input formats remain part of the explicit decoder matrix
  work in task 8.3.

## Latency diagnosis and correction

The user reported approximately two seconds of end-to-end A/V delay, which was
not present in the previous PulseAudio-based experiment. An aligned four-channel
PipeWire monitor captured the raw TV input on channels 1–2 and CamillaDSP
playback on channels 3–4 without modifying the audible route.

The initial correlated capture placed the processed signal approximately 620 ms
behind the raw input before the USB/ALSA sink. Three decoder behaviors contributed
or could retain avoidable delay:

- the legacy 64-block PCM confirmation window accidentally counted live
  PipeWire callback blocks and therefore represented about 1.365 seconds at the
  observed 1,024-frame graph quantum;
- startup PCM and rejected candidates were replayed after detection, permanently
  placing audio behind a live video source; and
- the native output callback filled the complete mapped PipeWire buffer capacity
  rather than only `spa_io_position.clock.duration` for the current graph cycle.
  This caused simultaneous output queue overflows and underruns in bursts.

The decoder now uses a 250 ms frame-counted detection window, requests a managed
512-frame PipeWire latency, discards old PCM confirmation/rejected-candidate
bytes instead of replaying them, and writes exactly the current PipeWire graph
cycle. Its bounded output queue remains four blocks; with correct cycle handling
that queue no longer drops steady-state audio.

## Objective post-fix result

The final 8.021-second aligned PCM capture contained 385,024 frames. Its raw and
processed stereo RMS levels were 0.02838 and 0.02859 respectively. One-millisecond
energy-envelope correlation found a 64 ms raw-input-to-CamillaDSP-output delay
at correlation 0.9998. The earliest correlation above 0.8 was 63 ms.

After decoder restart and graph convergence, a five-second steady observation
recorded no increase in output queue overflow or underrun counters. All three
managed services were active, applied desired version 13 was converged with no
last error, and the coordinated readiness rerun reported one active and one
converged graph with zero unfinished transitions.

The first aggregate readiness invocation raced the active transition by about a
second and stopped with an `applying` result. No rollback was applied. The graph
then converged normally and the readiness-only rerun passed (`ok=91`, `failed=0`).

## Verification

- PCM auto decoder on the Pi: 34 unit tests, one native PipeWire contract test,
  and one status-fixture integration test passed; `cargo fmt --check` passed.
- Focused Open Cinema decoder/processor-controller suite: 28 tests passed.
- The final coordinated candidate contract probe passed on PipeWire 1.4.2 and
  WirePlumber 0.5.8.

## Remaining acceptance boundary

Before closing tasks 8.2, 8.3, 8.5, or 9.6, retain the user's final subjective
lip-sync result, exercise phone priority over the live TV source plus fallback to
TV, run the declared supported and unsupported codec-transition matrix, and
capture the complete scenario's audible gaps and timing distribution.
