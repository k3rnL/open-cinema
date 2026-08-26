# Routing mechanism evaluation

## Decision

The first release uses WirePlumber policy metadata for every ordinary
one-to-one route. It creates raw PipeWire links only when the resolved graph
contains a declared advanced shape that default or `target.object` metadata
cannot express. This keeps Open Cinema responsible for durable product policy
without becoming a second session manager.

The machine-readable decision record is
`tests/fixtures/orchestration/canonical/routing_mechanisms.json`. It is checked
against the canonical desired graph and all canonical cases by the backend test
suite.

## Canonical TV, Bluetooth, decoder, CamillaDSP, and output path

| Stage | First-choice mechanism | Why no raw link is needed |
| --- | --- | --- |
| Selected TV/Bluetooth source to decoder | Set the managed decoder capture stream's target to the selected `Audio/Source` | This is one current stream choosing one source endpoint. |
| Decoder output to CamillaDSP input | Set the decoder playback stream's target to the prepared CamillaDSP input node | The stage is a one-to-one processor hand-off. |
| CamillaDSP output to main speakers/headset | Set the CamillaDSP playback stream's target to the selected `Audio/Sink` | Headset arrival/removal changes the target; WirePlumber owns link movement and device lifecycle. |
| Other playback streams declared `follow-default` | Set the configured `Audio/Sink` default and clear their explicit targets | They retain normal WirePlumber session behavior when the preferred output changes. |

This applies to all four canonical cases: TV PCM to room, Bluetooth to room,
headset override, and decoded AC-3 to room. PCM bypass versus decoding and the
selected CamillaDSP profile change processor configuration, not the routing
mechanism. None of those cases requires an Open Cinema-owned raw link.

The default is useful for ordinary unpinned streams; explicit per-stream target
metadata is preferable for the managed decoder/CamillaDSP chain because it
changes only that planned stream. External streams remain observed and are
moved only when their declared policy permits default or explicit targeting.

## Shapes requiring the explicit-link escape hatch

| Shape | First-release decision | Boundary |
| --- | --- | --- |
| Controlled fan-out | Raw managed links are required | One `target.object` cannot express simultaneous independently verified destinations. Use a declared fan-out/adapter processor if branch signal contracts differ. |
| Several sources mixed into one output | A managed mixer plus raw managed internal links is required | Metadata chooses a destination but does not define mixing, gains, or source combination. |
| Fixed processor-internal/channel topology | Raw managed links are conditional | Use them only when the prepared processor's fixed ports or channel wiring cannot be expressed as ordinary stream targets. The processor plan must enumerate the topology. |

Every raw link is limited to `fan-out`, `mixer`, or `processor-internal` action
shape, uses the fixed `open-cinema.orchestrator` owner, and carries a stable
desired-link tag. An existing unmanaged link is never adopted merely because
its endpoints happen to match.

## Cross-repository evidence and remaining proof

WyrePlumber's real-policy integration test already proves that a default routes
an ordinary playback stream and `target.object` moves it while the resulting
links remain WirePlumber-owned. Its managed-link tests prove the ownership
conflict and safe-removal boundary. The canonical Open Cinema fixture supplies
the product cases, while the existing UI graph remains desired intent rather
than exposing PipeWire link mechanics to normal users.

The binding evidence currently covers ordinary playback. Task 13.7 must still
exercise capture-stream targeting and the complete decoder/CamillaDSP chain in
the Open Cinema integration boundary. Raspberry Pi switching timings remain the
explicitly deferred hardware task 10.7 and do not affect which mechanism owns
each route.
