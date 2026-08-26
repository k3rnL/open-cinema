# Speaker channel tester hardware acceptance — 2026-08-26

Decision: the Raspberry Pi speaker-channel diagnostic is accepted as working
for continued appliance development.

Accepted evidence:

- the management UI discovered the live WONDOM GAB8 multichannel PCM sink and
  exposed its observed PipeWire channel positions;
- individual channel buttons generated a bounded test signal without editing or
  reapplying the active desired graph;
- the user exercised and accepted the explicit Stop control;
- finite playback expiry, exclusivity, stale-process protection, and inactive
  state cleanup remain covered by the backend and frontend regression suites;
- initial unexpected speaker identities were traced to physical amplifier
  wiring and conflicting external documentation rather than to the generated
  channel samples;
- the physical wiring was corrected using the labels printed on the bottom of
  the GAB8 board, after which programme voices and the tested channels behaved as
  expected.

The diagnostic intentionally does not persist a channel remapping. The accepted
physical mapping is the current wiring validated against the GAB8 board
silkscreen and the PipeWire channel labels shown by the tester.
