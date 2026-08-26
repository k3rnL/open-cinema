## Why

The accepted first orchestration release keeps PipeWire's Pulse protocol bridge
because `pcm-auto-decoder` and CamillaDSP 3 still use the PulseAudio client
protocol. PipeWire is already the real graph and WirePlumber is already the
session manager. Moving both managed processors to native PipeWire I/O removes
that transitional dependency and lets the decoder present one stable logical
output across PCM and encoded-content transitions.

## What Changes

- Replace the decoder's Pulse capture and separate PCM/decoded playback streams
  with native PipeWire capture and one stable adaptive PCM output carrying a
  configurable working signal contract.
- Report transport, encoded content, actual decoded-frame format, and emitted
  output format separately so runtime decisions never confuse programme content
  with the normalized PipeWire stream.
- Add safe PCM/encoded switching, 7.1 layouts, silence while classification is
  uncertain, and decoder/resampler reset when codec or decoded layout changes.
- Update the Open Cinema decoder driver, resolver facts, runtime correlation,
  explanations, and tests for the new native protocol and stable output.
- Upgrade CamillaDSP to version 4 or later with its native PipeWire backend,
  stable per-instance node properties, and WirePlumber-owned linking.
- Keep destination processing profiles selected by the desired route and output
  association by default; a content-format change only selects another profile
  when an explicit graph rule requests it.
- Run PCM, AC-3, E-AC-3, DTS, 2.0/5.1/7.1 transition, no-op reconciliation, and
  audio-gap tests before the deployment change removes `pipewire-pulse`.
- Keep WirePlumber responsible for target/default policy; the decoder does not
  create arbitrary session links, CamillaDSP autoconnect remains disabled, and
  neither processor becomes a session manager.

## Capabilities

### Modified Capabilities

- `adaptive-signal-processing`: the managed decoder exposes native PipeWire
  capture plus one stable adaptive output and distinguishes decoded content from
  the output working contract.
- `camilladsp-graph-processing`: managed CamillaDSP instances use the native
  PipeWire backend and remain stable across content-only format changes.
- `audio-reconciliation`: material format observations trigger resolution, but
  an unchanged effective plan does not produce unnecessary driver mutations.

## Impact

This coordinated local change affects `pcm-auto-decoder`, Open Cinema's decoder
and CamillaDSP drivers, resolver facts, the development environment, and
cross-repository tests. Raspberry Pi packaging, service ownership, compatibility
matrix changes, removal of PipeWire Pulse, and hardware/audio-gap acceptance are
recorded and completed in the separate `deploy-raspberry-audio-appliance`
change after local behavior is accepted.
