## 1. Platform Dependency and Repository Setup

- [x] 1.1 Complete the `extensible-plugin-platform` SDK, managed-source capability, declarative page templates, plugin overlay, and development-catalogue path required by this change.
- [x] 1.2 Create `/home/edaniel/PyCharmProjects/open-cinema-librespot` as an independent Git repository with MIT license, README, changelog, editor/ignore files, and the same branch/version conventions as the other Open Cinema projects.
- [x] 1.3 Add `pyproject.toml`, package/version metadata starting at `0.1.0`, locked development dependencies, `open-cinema-plugin.toml`, and the `open_cinema.plugins` entry point for plugin ID `open-cinema.librespot`.
- [x] 1.4 Add package, tests, fixtures, scripts, documentation, runtime-assets, option-contract, and `.github/workflows` directories without importing code from an Open Cinema working tree at runtime.
- [x] 1.5 Add a local editable-plugin source entry and prove the source checkout passes the platform's manifest and contract validator before implementing live behavior.

## 2. Pinned Librespot Runtime Assets

- [x] 2.1 Pin librespot `v0.8.0`, its source commit/digest, Cargo lock inputs, Rust toolchain, TLS/discovery features, supported target triples, and build metadata in reviewable files.
- [x] 2.2 Add reproducible x86-64 Linux and ARM64 Linux build scripts for the minimal librespot executable with pipe output, soft volume, Rust TLS, and declared zeroconf capabilities.
- [x] 2.3 Build and package a small typed headless-OAuth helper against the same pinned upstream source, with machine-readable states and no human-log parsing contract.
- [x] 2.4 Package the binaries and capability manifest into correctly tagged platform wheels and expose verified asset paths only through the plugin runtime context.
- [x] 2.5 Add binary identity, architecture, feature, linkage, help-output, and smoke-start verification for source builds and built wheels.
- [x] 2.6 Prove production marketplace installation fails clearly when no compatible wheel exists and never starts an implicit Rust build on the Raspberry Pi.

## 3. Complete Option Contract

- [x] 3.1 Commit a machine-readable classification for every `librespot --help` option and generate a readable compatibility table covering configurable, equivalent, managed, and unavailable states.
- [x] 3.2 Add a CI audit that compares the pinned binary's normalized help output with the classification and fails on added, removed, renamed, retyped, or changed-choice options.
- [x] 3.3 Define the versioned instance JSON schema and defaults for identity, device type, bitrate, logging, proxy/AP, discovery, volume, normalisation, playback, cache, local files, automations, and activity hold.
- [x] 3.4 Add conditional and cross-field validation for authentication/cache prerequisites, normalisation method, numeric bounds, mutually exclusive logging, compiled zeroconf choices, ports/interfaces, proxy URLs, and unique instance identity.
- [x] 3.5 Implement deterministic typed argv/environment serialization with fixed `pipe`, stdout device, `F32`, no dither, `softvol`, no passthrough, no ALSA controls, no password, and no arbitrary extra arguments.
- [x] 3.6 Implement private per-instance audio/system cache paths, configurable cache controls, size observation, credential persistence warnings, and bounded cleanup.
- [x] 3.7 Implement ordered repeatable local-file directories restricted to configured media roots with accessibility checks and restart-required explanation.
- [x] 3.8 Add exhaustive table-driven tests proving every classified option yields the intended form field, managed value, unavailable reason, argv/environment value, or non-launch action without leaking secrets.

## 4. Plugin Capabilities and Multi-Instance Model

- [x] 4.1 Implement the composite plugin manifest and API/action, automation, managed-resource, managed-audio-source, graph-node, and declarative-UI capability contributions using only the public SDK.
- [x] 4.2 Implement generic namespaced instance create, list, detail, update, enable, disable, delete, and optimistic-concurrency behavior with stable UUIDs and independent desired state.
- [x] 4.3 Validate unique Connect names and runtime/network correlation fields while allowing independent authentication, cache, configuration, and resource generations.
- [x] 4.4 Implement explicit referenced-instance deletion diagnostics and confirmation while preserving desired graph references as unavailable.
- [x] 4.5 Add per-instance resource observation containing desired/observed state, child identity, generation, health, start time, restart/backoff, last error, versions, effective non-secret configuration, and supported actions.
- [x] 4.6 Add tests for two or more independent instances, isolated reconfigure/restart/failure, disabled state, deletion, plugin hot disable/re-enable, and aggregate plugin health.

## 5. Librespot and PipeWire Process Supervision

- [x] 5.1 Implement explicit process-array construction for librespot and `pw-cat` with no shell, no user-controlled executable path, bounded environment, private working/cache directories, and separate stderr capture.
- [x] 5.2 Connect librespot binary stdout directly to the bridge stdin as binary audio while keeping logs and event messages on separate bounded channels.
- [x] 5.3 Launch the bridge as unlinked stereo 44.1-kHz F32 PCM with `target 0`, measured latency settings, `Music` role, and server-built provider/plugin/instance/generation properties.
- [x] 5.4 Implement one resource-generation supervisor that terminates/reaps both children when either fails, performs graceful then bounded forced stop, and never adopts unrelated processes by name.
- [x] 5.5 Implement bounded restart/backoff/cooldown, manual start/stop/restart, config-generation restart, plugin shutdown, and orchestrator recovery semantics.
- [x] 5.6 Observe bridge readiness and one exact fresh PipeWire correlation before reporting route availability; report missing, stale, mismatched, and duplicate streams distinctly.
- [x] 5.7 Add fake-binary tests for launch arguments, stdout backpressure, early bridge/librespot exit, stalled child, signal handling, restart storm, manual stop, reconfigure, shutdown, and secret/log redaction.
- [x] 5.8 Add a real PipeWire integration test proving the stream is unlinked by default, advertises the required properties and format, can be linked by core control, and is fully removed on stop.

## 6. Authentication and Event State

- [x] 6.1 Implement discovery authentication as the zero-secret default and report Connect readiness separately from client/session and playback state.
- [x] 6.2 Implement write-only access-token create/replace/remove/presence using the platform secret store and pass it through the environment without API, log, diagnostic, or command-line disclosure.
- [x] 6.3 Implement the guided OAuth operation state machine for authorization URL, callback submission, validation, credential-cache commit, timeout, cancellation, failure, retry, and redaction.
- [x] 6.4 Support optional username/cached-credential selection and actionable recovery when tokens expire or cached credentials are rejected.
- [x] 6.5 Add the fixed internal librespot event relay, generation-authenticated local transport, bounded event schema, event ordering, stale-generation rejection, and named automation dispatch.
- [x] 6.6 Combine playback events with fresh process/PipeWire state to publish session, playback, track-transition, active-signal, hold, stale, and error facts without leaving activity true indefinitely.
- [x] 6.7 Test discovery pairing, access-token redaction, OAuth success/failure/cancel, credential-cache settings, malicious callback text, stale events, sink-event selection, automation failure isolation, and activity hold.

## 7. Declarative Spotify Connect Administration UI

- [x] 7.1 Declare the Spotify Connect navigation entry, instance resource list, create flow, detail view, settings sections, status descriptions, diagnostics, and server-advertised actions without plugin-specific React or CSS.
- [x] 7.2 Design the overview to show Connect name, desired/running state, auth, session/playback, source format, PipeWire correlation, graph selection, health, and concise actions responsively.
- [x] 7.3 Implement the essential create path with name, device type, bitrate, discovery default, sensible cache/activity defaults, inline validation, and stable progress/status regions.
- [x] 7.4 Implement Identity/Auth, Audio/Volume, Discovery/Network, Normalisation/Playback, Cache/Local files, Automations, and Advanced tabs/sections with conditional typed fields and no raw JSON.
- [x] 7.5 Show access-token presence and OAuth actions safely; distinguish Spotify initial/remote volume from Open Cinema input trim; show managed and unavailable upstream options with explanations.
- [x] 7.6 Wire create/save/start/stop/restart/enable/disable/delete/OAuth actions to concurrency-safe operation descriptors with confirmations, duplicate-submit protection, reconnect behavior, and stale-action handling.
- [x] 7.7 Add platform-renderer fixtures and visual/component tests for empty, creating, healthy idle, playing, disabled, restarting, auth failed, stream ambiguous, multiple-instance, slow, and error states at supported widths.

## 8. Endpoint, Graph, and Resolver Integration

- [x] 8.1 Publish one durable logical input per instance with provider/instance identity, last-seen state, route availability, activity facts, and separately correlated managed-resource reference.
- [x] 8.2 Expose standard PipeWire input trim and mute only when the unique observed stream advertises fresh writable controls, independently from librespot volume configuration.
- [x] 8.3 Register `plugin.open-cinema.librespot.source` as an endpoint-role node with one F32/44.1-kHz/stereo output and a labelled live `instanceId` selector.
- [x] 8.4 Preserve structurally valid graph nodes for disabled, missing, deleted, unhealthy, stale, or ambiguous instances and provide clear unavailable diagnostics without runtime IDs in saved documents.
- [x] 8.5 Add detached resolver facts and explanations for route-available versus idle, playing, held active, stale, failed, and ambiguous states and resolve a selected instance to exactly one world-generation stream.
- [x] 8.6 Trigger world-state resolution on stabilized source activity/correlation changes without coupling graph apply/deactivate to librespot process lifecycle.
- [x] 8.7 Add graph catalogue, serialization, resolver, explanation, endpoint inventory, level/mute, and runtime-recreation tests for one and multiple instances.
- [x] 8.8 Add an example/acceptance graph fixture for TV fallback versus active Spotify input and headset priority versus main-speaker output, without installing it as an implicit global policy.

## 9. Repository CI and Release Pipeline

- [x] 9.1 Add pull-request CI for supported Python, formatting/lint/type checks, unit tests, option audit, manifest/SDK contract tests, package metadata, source build, and wheel inspection.
- [x] 9.2 Add x86-64 PipeWire integration CI with fake Spotify playback input and verify format, correlation, unlinked startup, routing, cleanup, and bounded resource use.
- [x] 9.3 Add a tag-driven release workflow that validates version agreement and clean history, builds x86-64 and ARM64 wheels, verifies embedded binaries, produces digests/provenance, and publishes immutable GitHub release assets.
- [ ] 9.4 Smoke-install downloaded release wheels into clean supported Open Cinema contract fixtures and prove runtime/plugin/librespot versions and option maps match the tag and artifact metadata.
- [ ] 9.5 Add the verified release to Open Cinema's hard-coded first-party catalogue with immutable URLs, architecture selectors, digests, compatibility, permissions, capabilities, and documentation links.
- [ ] 9.6 Exercise marketplace install/update/disable/uninstall/reinstall and failed-artifact rollback using the published bytes rather than a local worktree.

## 10. Documentation and Local Acceptance

- [x] 10.1 Write the plugin README with architecture, supported platforms/contracts, librespot pin/features, installation, development, validation, option table, authentication, multi-instance use, graph routing, troubleshooting, security, and release conventions.
- [x] 10.2 Document administrator workflows for discovery, headless OAuth, access token, cache/local files, volume distinctions, managed/unavailable options, resource actions, graph activity conditions, disable, uninstall, and rollback.
- [x] 10.3 Update Open Cinema plugin/catalogue and managed-source documentation with the librespot example while keeping the generic contract free of librespot-specific assumptions.
- [x] 10.4 Validate locally on the development server with one and two instances, a real Spotify client, live PipeWire observation, UI forms/actions, endpoint controls, manual routing, process crash, and plugin restart.

## 11. Raspberry Pi Hardware Acceptance and Closure

- [ ] 11.1 Install the published ARM64 wheel from the marketplace on the Raspberry Pi and record verified plugin/librespot identities, install/restart operation, Connect discovery, service readiness, and rollback generation.
- [ ] 11.2 Validate one discovery instance end to end through the desired graph, CamillaDSP path, main speakers, headset switching, pause/resume, reconnect, instance restart, plugin disable/re-enable, and appliance reboot.
- [ ] 11.3 Validate two simultaneous instances for unique discovery, independent auth/cache/process/endpoint identity, separate graph selection, isolated failure/restart, and declared capacity limits.
- [ ] 11.4 Measure idle and playing CPU, memory, temperature, cache growth, startup time, PCM bridge latency, transition gaps, activity/fallback delay, restart recovery, and long-run stability against explicit acceptance bounds.
- [ ] 11.5 Verify no automatic physical output link, no PulseAudio dependency, no secret disclosure, no arbitrary command/path execution, and no regression to TV/Bluetooth/ROC routing or dashboard/graph UI responsiveness.
- [ ] 11.6 Resolve acceptance findings, rerun repository and appliance gates, update README/changelog/version as required, publish the accepted release, pin the final catalogue entry, and record release/rollback evidence before archiving.
