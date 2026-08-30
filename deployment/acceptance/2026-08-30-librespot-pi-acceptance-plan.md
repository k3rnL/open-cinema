# Librespot Raspberry Pi acceptance plan — 2026-08-30

Status: **frozen before the first release-candidate appliance measurement**.

This plan accepts only the supported Raspberry Pi 5 8 GB appliance fixture and
the published `open-cinema-librespot` release selected by the first-party
catalogue. It does not extend support to another Pi tier, operating system, or
audio topology. The active graph and service state must be captured before each
disruptive case and restored exactly afterward.

## Measurement windows

- Sample process CPU, RSS, appliance temperature, throttling, and cache bytes
  once per second.
- Use a 30-second warm-up, two-minute idle window, five-minute playing window,
  and one ten-minute playing soak.
- Exercise five bounded instance starts and five bounded instance restarts.
- Exercise one and two simultaneous discovery instances. Each instance uses a
  64 MiB audio-cache limit during acceptance.
- Retain private raw observations on the appliance. Commit only aggregate,
  redacted results and detached digests.

## Frozen bounds

| Area | Acceptance bound |
| --- | --- |
| Thermal and power | Current throttling remains `0x0`; maximum temperature is 80 °C. Historical throttling bits are recorded separately. |
| One instance, idle | Librespot plus its PipeWire bridge use at most 10% p95 of one CPU core and 160 MiB maximum aggregate RSS. |
| One instance, playing | The process pair uses at most 30% p95 of one CPU core and 192 MiB maximum aggregate RSS. |
| Two instances, playing | Both process pairs together use at most 55% p95 of one CPU core and 384 MiB maximum aggregate RSS. |
| Cache | Each audio cache remains at or below 70 MiB with a configured 64 MiB limit; its system/credential cache remains below 16 MiB. Growth must level off after the configured audio limit is reached. |
| Start readiness | A requested start produces one fresh, uniquely correlated, route-available PipeWire source within 10 seconds in every repetition. |
| Restart recovery | A requested instance restart returns the same logical source through one fresh runtime generation within 15 seconds in every repetition. |
| Activity and fallback | Playing activity selects the Spotify source, and pause activity selects the configured fallback after the 1.5-second hold, within 5 seconds of the corresponding fresh event in every repetition. |
| PCM bridge | The source reports stereo F32 at 44.1 kHz and a requested/reported PipeWire latency no greater than 10 ms. This is a graph latency bound, not a physical speaker-latency claim. |
| Transition continuity | The control plane has no unresolved transition longer than 5 seconds and restores the expected exact owned topology. A physical audible-gap claim remains `not-measured` unless a calibrated capture is available. |
| Stability | During the ten-minute soak there are no unexpected child exits, restart attempts, duplicate correlated streams, PipeWire error increments, unbounded diagnostic growth, or loss of the selected route. |
| UI responsiveness | Authenticated dashboard and graph-detail API requests are at most 750 ms p95 on the LAN fixture; opening and selecting a graph node must not produce a browser long task over 200 ms. |

## Functional and security gates

Acceptance also requires:

- marketplace install, application restart, startup verification, rollback
  pointer, disable/re-enable, update, uninstall, and reinstall use the exact
  published wheel and digest;
- two Connect names remain independently discoverable with separate private
  data, process groups, endpoint identities, graph selection, and restart;
- a Spotify source starts unlinked and never creates an automatic physical
  output link;
- TV, Bluetooth programme input, ROC, CamillaDSP, main-speaker output, and
  headset-priority routing remain functional;
- no PulseAudio dependency, secret disclosure, user-controlled executable,
  shell command, or unrestricted filesystem path is introduced; and
- every failed case is reported as failed or unavailable. Bounds are not
  changed after observing a result.

## Evidence boundary

Listening reports are functional evidence only. Physical end-to-end latency
and audible-gap measurements require a calibrated capture and may not be
inferred from listener timing, PipeWire configuration, or control-plane event
timestamps. A missing calibrated fixture stays visible and does not invalidate
the independently measurable software and graph-latency results.
