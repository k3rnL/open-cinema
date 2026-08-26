# Canonical orchestration acceptance scenario

This fixture is the cross-repository behavioral contract for the first Open
Cinema orchestration release. `desired_graph.json` is persistent intent;
`cases.json` supplies immutable world snapshots and the expected resolved plan,
explanation, and final runtime assertions for each important transition.

The cases establish these invariants:

1. TV PCM uses the main speakers through the room CamillaDSP profile.
2. An active Bluetooth programme source wins over TV and still uses the main
   speakers.
3. An available headset wins over the main speakers and selects the explicit
   stereo/headphone processing policy.
4. Removing that headset restores the main-speaker fallback from the unchanged
   desired graph.
5. IEC-61937 AC-3 from TV enables decoding and uses the actual decoded 5.1
   contract for room processing.

The documents contain only stable logical and managed identifiers. PipeWire
numeric object IDs appear only inside the per-case runtime observation and are
never referenced by the desired graph.

`routing_mechanisms.json` records the cross-repository decision that every
canonical one-to-one stage uses WirePlumber default/target metadata, while
declared fan-out, mixer, and otherwise unrepresentable processor internals use
the strictly owned explicit-link escape hatch.
