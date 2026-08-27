# Adaptive Bluetooth routing acceptance — 2026-08-26

> **Status addendum (2026-08-27):** The
> [Open Cinema 0.3.2 closure](../../docs/release-readiness/2026-08-27-open-cinema-v0.3.2-closure.md)
> supersedes the pending physical-TV and final-supported-tier wording below.
> The owner subsequently accepted the complete TV, encoded processing,
> Bluetooth source, headset takeover, and fallback functional smoke; statistical
> timing and reliability benchmarks remain open.

Status: **accepted for the Bluetooth-source/headset portion of deployment tasks
8.2 and 9.6 on the experimental Raspberry Pi appliance**.

This acceptance proves automatic programme-source priority, headset takeover,
and headset-removal fallback through the desired processor graph without Save,
Apply, or any other graph edit. It does not yet accept the physical TV-input
part of the canonical scenario, so tasks 8.2 and 9.6 remain open.

## Fixture and desired graph

- Raspberry Pi 5 8 GB appliance using its onboard Bluetooth adapter.
- Debian 13, PipeWire 1.4.2, WirePlumber 0.5.8, and BlueZ 5.82.
- Dedicated lingering `opencinema` audio account; no graphical login session.
- Supported phone programme source, Bluetooth headset output, and eight-channel
  Wondom USB main-speaker output. Device addresses are deliberately omitted.
- One already-applied graph with ordered input and output selectors, the native
  single-output PCM auto decoder, and CamillaDSP 4 native PipeWire processing.

The input selector prefers the Bluetooth phone over the looping debug-file
fallback. The output selector prefers the Bluetooth headset over the main
speakers. The desired graph was not edited or reapplied during any transition.

## User-observed scenario

With the phone connected and playing music, Open Cinema automatically selected
the phone and played it through the main speakers. Turning on the headset stopped
the main-speaker output and moved the same programme audio to the headset.
Turning off the headset restored the programme audio to the main speakers.

The user repeated the directions after the reconciliation fixes and reported an
audible switch time of approximately four seconds for both headset connection
and removal. This is a manual wall-clock observation, not a captured p95 audible-
gap measurement; the latter remains part of task 8.5.

## Correlated runtime evidence

The successful takeover transition selected `Bluetooth programme source` and
`Bluetooth headset output` and completed in 4.592 seconds. The terminal fallback
transition selected the same programme source and `Main Speakers` and completed
in 6.078 seconds. Journal completion includes processor verification and cleanup,
so it is not equivalent to the user's approximately four-second audible gap.

After fallback, the applied state was `converged`, at transition generation 93,
with no last error. Its active graph still contained both managed processors and
the two ordered selectors, the current resolved plan contained no errors, and
the PipeWire runtime contained all 18 Open Cinema-owned links. The orchestrator,
decoder, and CamillaDSP services were active with zero systemd restarts and no
warning-level journal entries after the corrected deployment.

During headset removal, one obsolete headset-target transition encountered a
generation-scoped node that had already disappeared. The orchestrator abandoned
that stale intent and immediately converged the new main-speaker plan. The failed
attempt remains visible in the transition history as diagnostic evidence; it did
not leave an applied error or require user intervention.

## Corrections validated by this scenario

The final run includes three control-plane/runtime corrections found during the
interactive hardware test:

- the native decoder treats downstream PipeWire queue pressure during CamillaDSP
  reconfiguration as bounded backpressure rather than terminating its output;
- the orchestrator performs bounded immediate catch-up when the authoritative
  world advances during reconciliation; and
- steady-state processor readiness no longer creates its own runtime sequence
  churn, while material CamillaDSP channel changes require replacement PipeWire
  resources before routing resumes.

The complete Open Cinema suite passed 811 tests after these corrections. The Pi
decoder passed 31 unit tests plus its native contract and status-fixture tests,
and the coordinated deployment contract gate passed.

## Acceptance boundary

Accepted here:

- real Bluetooth phone audio through decoder and CamillaDSP to main speakers;
- automatic headset takeover without graph reapply;
- automatic headset removal/fallback without graph reapply; and
- approximately four-second audible switching in both directions for this
  manual run.

Still required before tasks 8.2 and 9.6 can close:

- connect the physical TV input (or the accepted final TV transport), verify it
  routes to the main speakers, and verify phone priority plus fallback to TV;
- repeat the complete scenario as the final supported-tier acceptance run; and
- retain the correlated UI status evidence required separately by task 9.7.
