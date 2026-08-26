## 1. Protocol-v2 and Signal Contracts

- [x] 1.1 [pcm-auto-decoder] Replace the split PCM/decoded stream identity document with stable native capture and adaptive-output identities.
- [x] 1.2 [pcm-auto-decoder] Add the emitted output descriptor to every protocol-v2 status and event document while retaining actual decoded-frame descriptors separately.
- [x] 1.3 [pcm-auto-decoder] Define explicit mono, stereo, 5.1-side, 5.1-rear, and 7.1 position tables and reject ambiguous or unsupported configured layouts.
- [x] 1.4 [pcm-auto-decoder] Update complete JSON/status socket fixtures for starting, detecting, PCM, AC-3, E-AC-3, DTS, 5.1, 7.1, unsupported, and failed states.
- [x] 1.5 [open-cinema] Replace the protocol-v1 parser and test fixtures with strict protocol-v2 parsing for capture/output identities and decoded/emitted descriptors.

## 2. Native PipeWire Decoder I/O

- [x] 2.1 [pcm-auto-decoder] Add the supported PipeWire Rust bindings and remove PulseAudio runtime dependencies from the release binary.
- [x] 2.2 [pcm-auto-decoder] Implement one native capture stream with stable Open Cinema instance, role, stream-role, and node-group properties and no target/autoconnect selection.
- [x] 2.3 [pcm-auto-decoder] Implement one native adaptive output stream with the configured emitted PCM contract and the same stable instance correlation properties.
- [x] 2.4 [pcm-auto-decoder] Connect PipeWire callbacks to bounded preallocated capture/output queues so codec work and status broadcasting stay off the real-time callback path.
- [x] 2.5 [pcm-auto-decoder] Emit silence on playback underrun and expose bounded overflow/underrun diagnostics without blocking PipeWire callbacks.
- [x] 2.6 [pcm-auto-decoder] Keep file capture/output as an explicit offline fixture transport without creating multiple live output contracts.
- [x] 2.7 [pcm-auto-decoder] Cover native stream negotiation, state, disconnect, incompatible-format, and bounded queue failure behavior.

## 3. Stable Adaptive Output

- [x] 3.1 [pcm-auto-decoder] Replace separate PCM and decoded sinks with one adaptive output sink configured from a single working rate, format, and layout.
- [x] 3.2 [pcm-auto-decoder] Convert confirmed PCM input into the emitted working contract with position-preserving expansion and zero-filled absent channels.
- [x] 3.3 [pcm-auto-decoder] Convert decoded frames into the same working contract while reporting the pre-normalization decoded descriptor.
- [x] 3.4 [pcm-auto-decoder] Add 7.1 FFmpeg layout support and reject narrowing that lacks an explicit downstream adaptation policy.
- [x] 3.5 [pcm-auto-decoder] Recreate decoder and resampler state when codec, decoded rate, sample format, or channel layout changes materially.
- [x] 3.6 [pcm-auto-decoder] Flush stale candidate, codec, resampler, and queued output state during stable mode transitions.
- [x] 3.7 [pcm-auto-decoder] Continuously emit silence while the signal is unknown, detecting, rejected, unsupported, or transitioning.
- [x] 3.8 [pcm-auto-decoder] Add a deterministic PCM→AC-3 5.1→PCM→DTS 7.1 scenario that asserts one output identity, position-preserving mapping, silent transition windows, and no encoded bytes on PCM output.

## 4. Open Cinema Decoder Integration

- [x] 4.1 [open-cinema] Replace split decoder stream request/configuration fields with one native capture and one adaptive output contract.
- [x] 4.2 [open-cinema] Generate stable decoder and CamillaDSP node/group/property identities and match runtime objects through WyrePlumber without persisting PipeWire numeric IDs.
- [x] 4.3 [open-cinema] Update decoder prepare, activate, observe, reconfigure, suppress, and stop behavior for protocol v2 and the single output.
- [x] 4.4 [open-cinema] Validate that the observed native capture/output contracts agree with the driver request before reporting the decoder ready.
- [x] 4.5 [open-cinema] Keep the desired decoder graph node as one logical output and add schema-driven working-layout/rate parameters and validation.
- [x] 4.6 [open-cinema] Project transport, encoded codec, actual decoded format, emitted working format, mode decision, and contract disagreements into distinct runtime facts and API explanation fields; defer richer UI presentation.
- [x] 4.7 [open-cinema] Replace content-channel-count profile selection fixtures with destination-profile and stable-working-bus fixtures.

## 5. No-op Resolution and Safe Reconciliation

- [x] 5.1 [open-cinema] Resolve material signal changes using the emitted working descriptor, record an effective-plan no-op for 5.1 movie→stereo menu→7.1 movie when route/profile/resources/links stay equivalent, and prove an explicit content rule still performs the safe processor transition.

## 6. CamillaDSP 4 Native PipeWire

- [x] 6.1 [open-cinema] Extend CamillaDSP endpoint/config validation from v3 Pulse/ALSA backends to the version-4 native PipeWire backend.
- [x] 6.2 [open-cinema] Generate stable per-instance capture/playback `node_name`, description, shared `node_group_name`, and `autoconnect_to: null` fields.
- [x] 6.3 [open-cinema] Use the decoder emitted working descriptor for CamillaDSP capture and the destination profile/adaptation for playback.
- [x] 6.4 [open-cinema] Update structural, engine-validation, driver lifecycle, restart-correlation, stable-profile, and explicit-mixer tests for native PipeWire.
- [x] 6.5 [open-cinema] Update local runtime configuration and documentation to require CamillaDSP 4+ with the native PipeWire feature and no Pulse buses.
- [x] 6.6 [open-cinema] Update Python control-client compatibility or isolate version-specific control behavior behind the existing CamillaDSP driver contract.

## 7. Local Integrated Verification

- [x] 7.1 [pcm-auto-decoder] Run formatting, unit, fixture, status-socket, and native PipeWire integration tests with no Pulse server.
- [x] 7.2 [open-cinema] Run focused decoder, signal, resolver, reconciler, CamillaDSP, API, and driver tests.
- [x] 7.3 [open-cinema] Run the complete backend test suite and strict OpenSpec validation.
- [x] 7.4 [local runtime] Run one representative stereo PCM→AC-3 5.1→stereo PCM→DTS scenario through decoder→CamillaDSP with stable WirePlumber-matched nodes, and pair the live DTS layout available from the fixture encoder with deterministic 7.1 mapping coverage and summarized transition/error evidence.
- [x] 7.6 [planning] Update `deploy-raspberry-audio-appliance` with the accepted versions, artifacts, service-session ownership, readiness probes, compatibility-bridge removal, and deferred Pi acceptance tasks without marking hardware work complete.
