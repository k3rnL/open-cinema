## Context

See `proposal.md` for motivation and the delta specifications for behavior. The decoder currently opens Pulse capture plus separate PCM and decoded Pulse playback streams. Its status protocol reports the actual FFmpeg decoded frame, while its configured playback format can differ. The current decoder output-layout helper supports at most 5.1. Open Cinema correlates the separate stream names and selects CamillaDSP configurations whose channel count follows the transient content fixture. CamillaDSP 3 is deployed with Pulse buses even though version 4 provides native PipeWire filter nodes.

The desired graph already presents the decoder as one logical processor with one output. The runtime implementation should match that abstraction and should avoid reconfiguring the room processor during ordinary movie/menu format changes.

## Goals / Non-Goals

**Goals:**

- Provide native PipeWire capture and one stable adaptive output from the decoder.
- Preserve actual decoded-frame truth while separately describing normalized output.
- Keep content transitions bounded, silent while uncertain, and free of encoded noise on PCM paths.
- Use CamillaDSP 4 native PipeWire nodes with stable managed identities.
- Make ordinary 2.0/5.1/7.1 changes observation-only when the effective route and processor configuration are unchanged.

**Non-Goals:**

- Making the decoder a route or session-policy controller.
- Performing implicit lossy downmix in the decoder.
- Removing PipeWire Pulse from Raspberry Pi images before the separate deployment acceptance change passes.
- Adding multi-room or multi-instance capacity policy beyond the existing resource model.

## Decisions

### 1. One native capture stream and one native adaptive output stream

The decoder owns one PipeWire input stream with media category `Capture` and one output stream with media category `Playback`. Both carry stable Open Cinema instance, role, stream-role, and node-group properties. Neither sets a target or autoconnect policy. WirePlumber links their ports from the resolved plan.

The output stream has one configured PCM contract for its lifetime. PCM input is converted into that contract; decoded frames are resampled and position-mapped into it. Channels absent from the programme are zero-filled. A new graph plan may restart or reconfigure the instance with another working contract, but content detection alone does not change its ports.

**Alternative considered:** Keep separate PCM and decoded output streams and let reconciliation switch links. Rejected because it exposes an internal branch in the runtime graph, requires link mutation for every menu/movie transition, and creates additional race and audio-gap surfaces.

### 2. Use a version-2 status document with decoded and emitted descriptors

There is no compatibility requirement for existing local data or decoder protocol consumers. Protocol v2 therefore replaces the split playback identities with `capture` and `output` identities and adds an always-present emitted-output descriptor. `decoded` continues to describe actual FFmpeg frames before normalization. Sequence, lifecycle, mode, confidence, errors, and the local newline-delimited JSON event transport remain.

Open Cinema rejects unsupported protocol versions explicitly. It projects actual decoded content into signal facts and projects emitted output into managed-resource correlation and downstream negotiation. UI explanations show both when they differ.

### 3. Keep a stable configurable working layout

The decoder driver derives output rate and layout from the resolved node configuration. The first home-cinema default is F32 at 48 kHz with an explicit 7.1 position order: FL, FR, FC, LFE, SL, SR, RL, RR. Mono, stereo, 5.1 side, 5.1 rear, and 7.1 are supported. Position-preserving expansion is allowed; narrowing requires an explicit downstream mixer and is rejected by the decoder.

The decoder's PCM input carrier remains explicitly described and independently configurable for test fixtures. Native PipeWire negotiation must agree with the required carrier and output contracts before the process becomes ready.

### 4. Silence is the transition safety state

Unknown, detecting, rejected, unsupported, and mode-transition windows produce zero samples on the stable output. When a transition becomes stable, the worker flushes candidate bytes, FFmpeg decoder state, resampler state, and queued output from the previous mode before enabling new programme samples. Output production remains continuous from PipeWire's perspective.

The audio worker and PipeWire real-time callbacks communicate through bounded preallocated queues. Callbacks do not decode, allocate unbounded buffers, block on status clients, or perform graph policy. Overflow and underrun are observable counters/errors; playback underrun emits silence.

### 5. Reinitialize normalization on material decoded-frame changes

Codec changes recreate the codec context. A material decoded-frame rate, sample format, or channel-layout change recreates the resampler before the next emitted frame. Status publishes the observed descriptor independently of the stable emitted descriptor.

### 6. CamillaDSP 4 uses stable native nodes and a destination profile

Generated CamillaDSP configurations use `type: PipeWire`, required channel counts, stable per-instance `node_name` and `node_group_name`, descriptions, and `autoconnect_to: null`. Open Cinema continues to start, validate, control, observe, and stop instances; PipeWire runs their audio graph and WirePlumber owns links.

The capture descriptor is the stable working bus. The playback descriptor is selected from the destination profile and any explicit adaptation mixer. Programme channel count is available to graph conditions but does not select a headphone or room profile by itself.

### 7. Resolution events and driver mutations remain separate

Every stable material signal observation schedules resolution and updates explanation state. The reconciler compares the effective plan identity and action set with the applied plan. If route, links, resource allocations, processor configurations, and parameters are equivalent, it records a no-op outcome without suppressing audio or invoking drivers.

## Risks / Trade-offs

- **[Risk] PipeWire callbacks starve while decoding or resampling.** → Keep codec work off the callback thread, use bounded queues, report pressure, and measure under hardware acceptance.
- **[Risk] A fixed eight-channel bus consumes more DSP than current content needs.** → Make the working contract configurable and benchmark the default before deployment promotion.
- **[Risk] Channel positions are misinterpreted across FFmpeg, PipeWire, and CamillaDSP.** → Use explicit position tables and fixture tests for every supported layout; never rely on channel count alone where positions are available.
- **[Risk] A content transition produces a click or stale audio.** → Use silence as the transition state, flush old queues, and add captured gap/click acceptance fixtures.
- **[Trade-off] Protocol v2 intentionally breaks the provisional v1 parser.** → Upgrade the decoder and Open Cinema together; no legacy compatibility or migration path is maintained.

## Migration Plan

1. Add protocol-v2 fixtures and pure channel-mapping/transition tests.
2. Implement native capture/output streams and retain file I/O only as an offline test transport.
3. Update Open Cinema's parser, driver request generation, correlation, facts, and explanations.
4. Upgrade the CamillaDSP config generator and local runtime to version 4 native PipeWire.
5. Run local PipeWire fixtures for PCM and supported encoded codecs through the stable output and CamillaDSP nodes.
6. After local acceptance, update the separate Raspberry deployment change, remove both processors from the compatibility reason list, and run hardware/audio-gap acceptance before disabling PipeWire Pulse.

Rollback during local development installs the previous coordinated decoder/Open Cinema/CamillaDSP set and re-enables the existing Pulse compatibility path. Protocol participants are never rolled back independently.
