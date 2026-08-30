## Context

This change is the first external implementation of `extensible-plugin-platform`. It therefore
must not rely on a private frontend component, a bundled import fallback, direct Django model
registration, or a hand-written core API specific to librespot. The plugin will use the common
distribution manifest, declarative administration pages, generic namespaced storage, managed
resource/source capabilities, and graph catalogue contracts.

Librespot is a Spotify Connect receiver whose upstream options currently describe normal sound
backends rather than an Open Cinema-owned graph source. The pinned 0.8.0 release has no merged
native PipeWire backend. Its always-compiled `pipe` backend emits raw stereo 44.1-kHz audio to
stdout by default, which can feed a PipeWire playback stream. The upstream option reference and
binary help output are maintained separately, so the plugin needs a deliberate mapping rather than
blindly forwarding user strings.

References:

- https://github.com/librespot-org/librespot/wiki/Options
- https://github.com/librespot-org/librespot/wiki/Audio-Backends
- https://github.com/librespot-org/librespot/releases/tag/v0.8.0

See `proposal.md` for motivation and the delta specifications for externally visible behavior.

## Goals / Non-Goals

**Goals:**

- Prove that a separately released plugin can install, render an elegant UI, persist multiple
  instances, own long-lived resources, and contribute graph-resolvable sources without custom core
  feature code.
- Keep every enabled Spotify Connect identity discoverable even while no graph selects it.
- Produce one stable, low-overhead PCM contract per instance that core can route through the same
  selectors, processors, and outputs as TV, Bluetooth, ROC, or file sources.
- Account for the entire pinned librespot option surface and fail CI when upstream drift is not
  classified.
- Publish reproducible ARM64 Raspberry Pi and x86-64 Linux plugin artifacts.

**Non-Goals:**

- Reimplementing Spotify playback, metadata browsing, playlists, search, or a Spotify client UI.
- Supporting Spotify Free accounts or storing Spotify passwords.
- Letting librespot choose a physical sound device, PipeWire default, or global output.
- Encoded Ogg passthrough. The first contract is stable decoded PCM.
- A per-instance systemd unit or arbitrary root install hook. Supervision belongs to the generic
  managed-source runtime under the existing unprivileged orchestrator.
- Guaranteeing that every upstream compile-time backend is present. The UI reports choices omitted
  from the pinned build.
- Preserving plugin instance data before the first accepted release.

## Decisions

### 1. Create one external composite plugin repository

The new repository is `/home/edaniel/PyCharmProjects/open-cinema-librespot`, with distribution name
`open-cinema-librespot` and plugin ID `open-cinema.librespot`. It contains:

- `open-cinema-plugin.toml` and the `open_cinema.plugins` entry point;
- the Python plugin package and version;
- declarative UI/page, configuration, instance, resource, and graph-source descriptors;
- the pinned option classification and binary-capability manifests;
- process supervision, event relay, authentication, and diagnostics code;
- tests, fixtures, README, license, changelog, and GitHub workflows;
- packaged Linux runtime assets.

One distribution contributes API/action, automation, managed-resource, managed-audio-source,
desired-graph catalogue, and administration-UI capabilities. The main Open Cinema repository only
adds the signed/pinned first-party catalogue record and generic contract fixtures. The UI repository
receives no librespot-specific React code.

### 2. Pin librespot 0.8.0 and package the executable in platform wheels

The first release pins the upstream `v0.8.0` source/tag and exact Cargo lock inputs. CI builds a
minimal Linux executable with Rust TLS, the pipe backend, soft volume support, and the selected
zeroconf implementation. The pipe backend requires no audio-library dependency; `libmdns` is the
portable default discovery feature. Additional zeroconf variants are exposed only when a produced
artifact reports them.

The resulting binary and its build-capability manifest are included in platform-specific plugin
wheels for Linux x86-64 and ARM64. Marketplace installation therefore does not compile Rust on the
Raspberry Pi. The wheel reports plugin version, librespot version/source, target triple, feature
set, binary digest, and option-map version. A source-tree developer can run an explicit build task,
but production installation never silently falls back to a local Cargo build.

This was selected over downloading a binary during plugin start because the plugin overlay can
then verify and rollback one artifact. Distribution-package librespot was rejected because its
version and compile features vary by OS. Building a custom librespot player was rejected because
the official pipe contract already supplies the required stable PCM boundary.

### 3. Supervise librespot and a PipeWire bridge as one instance resource

For each desired enabled instance, the managed-source provider starts two child processes with
explicit argument arrays and no shell:

```
librespot --backend pipe --format F32 --dither none --mixer softvol ...
    stdout ───────────────▶ pw-cat --playback - --target 0
                                      --rate 44100 --channels 2
                                      --channel-map stereo --format f32
                                      --properties <core-built-properties>
```

Librespot stderr and bridge stderr are captured separately with bounded structured tails. Audio
stdout is never decoded as text. The bridge uses an explicitly benchmarked low-latency quantum;
the effective requested value is reported but remains product-managed until measurements justify a
user setting. `--target 0` prevents PipeWire autoconnection. Core reconciliation later routes the
stream through the desired graph.

Both children belong to one supervisor generation. Unexpected exit of either terminates and reaps
the other, records exit/health facts, and applies bounded exponential restart with cooldown. Stop
uses graceful termination then bounded group kill. Reconfigure restarts only that instance. Plugin
or orchestrator shutdown stops every owned generation; no unrelated process is adopted by name.

Why not GStreamer: upstream explicitly notes possible extra latency and it adds a large plugin
dependency surface. Why not a FIFO: a stdout pipe gives the supervisor direct lifetime and
backpressure control and avoids stale filesystem endpoints. A future native PipeWire backend can
replace the bridge behind the same managed-source signal contract after acceptance.

### 4. Use fixed stereo 44.1-kHz F32 PCM as the public signal

Spotify/librespot produces stereo at 44.1 kHz. F32 avoids an unnecessary integer requantization
after librespot's floating-point mixer and normalisation, needs no dither, and is accepted by the
installed PipeWire CLI. The graph node therefore has one `audio` output with PCM, 44,100 Hz, F32,
two channels, and `FL,FR` positions.

Core may negotiate later conversion, resampling, channel mapping, decoder bypass, or CamillaDSP
profiles just as it does for another PCM source. Librespot never receives the chosen speakers or
headset and never switches backend on route changes. Encoded passthrough remains unavailable
because it would invalidate this stable node contract and would require track-boundary-aware Ogg
handling throughout the graph.

### 5. Correlate streams through immutable plugin instance properties

Every instance has an opaque UUID independent from its editable Spotify device name. The bridge
sets server-built PipeWire properties including provider ID, plugin ID, instance ID, process
generation, node name, description, `Music` role, media class/direction, format, and channel map.
WyrePlumber remains the observer and returns those properties in the versioned runtime snapshot.

The managed source produces a durable logical endpoint ID derived from provider and instance UUID.
Devices shows that endpoint and its unique candidate; Managed resources shows the two-process
resource generation. Resolution requires exact provider, plugin, instance, generation, direction,
and signal matches. Display-name similarity is never enough. Recreated PipeWire IDs bind to the
same endpoint, while duplicate claims become an ambiguity instead of an arbitrary winner.

### 6. Keep instance lifecycle independent from graph activation

The plugin reconciles enabled instance documents continuously. Graph apply does not start or stop
librespot. This preserves the device in Spotify Connect and lets a graph wait for activity. Plugin
enable starts all desired enabled instances; plugin disable stops them through the managed-source
contract. Instance start/stop/restart actions change or override only that instance's desired
resource state according to server-advertised semantics.

Most librespot CLI settings are not live-reconfigurable. Saving a changed effective launch setting
creates a new instance generation and reports a short source interruption. Pure routing metadata,
UI labels that do not affect the Connect identity, and automation selection can update without a
process restart when their provider contracts allow it.

### 7. Feed typed playback facts into normal resolver conditions

Each resource publishes:

- route availability and bridge correlation;
- authentication/credential presence;
- client/session connection;
- playback state (`unknown`, `idle`, `playing`, `paused`, `stopped`, `error`);
- active signal and transition timestamp;
- current track/session metadata when safely available;
- observation freshness and process generation.

A fixed internal event-relay executable is passed as librespot's event program. It converts the
known upstream environment into a bounded generation-tagged local message for the provider. The
user never controls the executable path. PipeWire node state supplies a second activity signal;
the provider combines both conservatively so a missing event cannot leave activity true forever.

Instance integration settings include an `activityHoldMs` bound to avoid route flapping on short
pauses and track transitions. A change to the stabilized activity fact schedules normal world-state
resolution. Thus a source selector can express “Spotify when active, otherwise TV,” while the
existing output selector independently expresses “headset when connected, otherwise speakers.”
The resolved explanation distinguishes unavailable, idle, held active, playing, stale, and
ambiguous states.

### 8. Map every upstream option deliberately

The repository contains a machine-readable mapping generated/checked against `librespot --help`.
The classification for 0.8.0 is:

| Upstream options | Open Cinema representation |
| --- | --- |
| `help`, `version` | Read-only help/version actions and diagnostics; never persisted as launch configuration. |
| `cache`, `system-cache` | Fixed per-instance private paths; their effective paths and use are visible. |
| `cache-size-limit`, `disable-audio-cache`, `disable-credential-cache` | Typed cache controls, with warnings when an authentication method needs persistent credentials. |
| `quiet`, `verbose` | One mutually exclusive log-level control. |
| `name`, `device-type`, `bitrate` | Typed essential playback identity fields. |
| `onevent`, `emit-sink-events` | Fixed internal event relay plus optional named Open Cinema automation and typed sink-event selection; no user executable. |
| `enable-oauth`, `oauth-port` | Guided headless OAuth action; port is managed as `0` for the callback-paste flow. |
| `access-token` | Write-only secret supplied through the process environment. |
| `username` | Optional cached-credential selector. |
| `password` | Unavailable because upstream deprecates/does not support password login. |
| `proxy`, `ap-port`, `disable-discovery` | Validated network/connection controls; credential-bearing proxy data is redacted. |
| `backend`, `device` | Fixed to `pipe` and the supervisor-owned stdout bridge. |
| `format`, `dither` | Fixed to `F32` and `none` to match the graph signal contract. |
| `mixer` | Fixed to `softvol`. |
| `alsa-mixer-control`, `alsa-mixer-device`, `alsa-mixer-index` | Unavailable because the plugin cannot own a hardware mixer. |
| `initial-volume`, `volume-ctrl`, `volume-range` | Typed librespot/Spotify volume behavior, labelled separately from PipeWire input trim. |
| `zeroconf-backend`, `zeroconf-port`, `zeroconf-interface` | Typed discovery controls filtered by binary features and host interfaces. |
| `enable-volume-normalisation`, `normalisation-method`, `normalisation-gain-type`, `normalisation-pregain`, `normalisation-threshold`, `normalisation-attack`, `normalisation-release`, `normalisation-knee` | A conditional typed normalisation section with upstream bounds/defaults. |
| `autoplay`, `disable-gapless` | Typed playback switches with positive UI wording and upstream semantics. |
| `passthrough` | Unavailable because the public source contract is decoded F32 PCM. |
| repeated `local-file-dir` | Ordered repeatable allowed-directory selector, validated against configured media roots. |

Defaults are copied from the pinned binary, not assumed from the wiki. Every argv value is produced
by typed serialization; there is no “extra arguments” text field. Managed and unavailable values
remain visible in an Advanced compatibility panel so “all options” does not turn the primary form
into clutter.

### 9. Support three authentication modes without plaintext disclosure

Discovery is the default: no credential fields are required and the user selects the instance in a
Spotify client. Access-token mode writes the token through core secret storage and provides it as a
`LIBRESPOT_ACCESS_TOKEN` environment value, avoiding normal command-line exposure. Credential and
system caches are private per-instance directories.

Guided OAuth runs a short-lived helper built against the pinned librespot OAuth library. It exposes
machine-readable states (authorization URL, waiting for callback, validating, succeeded, failed)
rather than parsing human logs. The headless flow uses port 0: the administrator opens the URL on
their Mac or phone and pastes the resulting callback URL when the browser cannot reach localhost.
The helper writes reusable credentials into the instance's system cache. OAuth operations are
single-use, bounded, cancellable before credential commit, and redact authorization codes.

Authentication settings show that Spotify Premium is an upstream requirement. Access-token expiry
or cached-credential failure degrades only the instance and offers discovery/OAuth recovery.

### 10. Use declarative list/detail/settings pages without plugin React code

The plugin contributes a top-level “Spotify Connect” navigation entry. Its overview uses the
resource-list template with status, Connect name, desired/running state, authentication, session,
playback, endpoint correlation, selected route, and inline safe actions. Creation uses a guided
flow with sensible defaults. Detail uses product tabs/sections:

- Overview and current playback;
- Identity and authentication;
- Audio and volume;
- Discovery and network;
- Normalisation and playback;
- Cache and local files;
- Automations;
- Advanced managed/unavailable options and diagnostics.

The essential path stays short: name, device type, bitrate, and discovery authentication are enough
to create a working instance. Conditional sections hide irrelevant normalisation or OAuth fields,
secrets show presence only, and the fixed action/status region does not move when validation or
process state changes. All data and actions use the generic plugin endpoints and operation
descriptors from the platform.

### 11. Publish a graph-source node backed by the logical endpoint

The plugin contributes `plugin.open-cinema.librespot.source` as an endpoint-role node with one PCM
output and a required `instanceId` field rendered as a live labelled instance selector. The saved
value is the stable instance UUID. Node summary shows instance name and current activity without
persisting runtime overlay data.

The resolver obtains the logical endpoint and managed-source facts from core; it does not call the
librespot process during pure planning. A reference to a disabled, removed, stale, unhealthy, or
ambiguous instance remains structurally valid but runtime-unavailable. The node can feed an ordered
source selector, decoder bypass/PCM path, CamillaDSP, and normal endpoint outputs using existing
typed ports.

An acceptance fixture provides the intended policy shape:

```
TV input ───────────────┐                    ┌─ headset (when available)
Spotify (when active) ──┴─ source selector ─┴─ main speakers (fallback)
```

The fixture is an example, not an implicit global policy installed by the plugin.

### 12. Keep source volume and Spotify volume semantically separate

Librespot initial volume, remote Spotify volume, curve, and range affect samples before the bridge.
If the observed PipeWire stream exposes writable volume/mute, the Devices control is labelled as
Open Cinema input trim/mute and uses the core endpoint control token. The plugin detail shows both
concepts separately and never fabricates synchronization between them.

### 13. Release through the same repository discipline as other components

Pull requests run Python formatting/static checks, manifest and option-map validation, SDK contract
tests, fake-process supervision tests, UI-descriptor fixtures, package build, and an x86-64
PipeWire integration test. Release tags must match package/runtime metadata. The release workflow
builds Linux x86-64 and ARM64 wheels, verifies the embedded binary on the target architecture,
publishes checksums/provenance and GitHub assets, then smoke-installs the published bytes against a
supported Open Cinema contract fixture.

The first-party catalogue is updated only after published artifact verification. README and release
notes state the supported Open Cinema/plugin contract, librespot source/features, architecture,
development commands, authentication methods, option differences, installation, graph use,
troubleshooting, and rollback.

## Risks / Trade-offs

- [Spotify changes authentication or Connect behavior outside the plugin release] -> Pin librespot,
  expose clear auth health, keep discovery as the simplest path, and test with a real Premium
  account during hardware acceptance.
- [The stdout consumer dies or blocks] -> Supervise both processes as one generation, bound
  shutdown/restart, preserve backpressure, and test bridge death and stalled-pipe behavior.
- [A false playback event steals routing from TV] -> Combine generation-tagged events with fresh
  PipeWire state, expire stale activity, use a configurable hold interval, and explain the fact used.
- [Multiple instances increase memory/network/cache use] -> Report per-instance resources, cap
  restart storms and caches, expose capacity diagnostics, and benchmark the supported Raspberry Pi.
- [Headless OAuth upstream internals change] -> Build the typed helper against the same pinned
  source and fail the option/auth contract tests before release.
- [F32 uses twice the bandwidth of S16] -> Local 44.1-kHz stereo bandwidth remains small, and F32
  avoids extra quantization before DSP; benchmark CPU and latency on the Pi.
- [Generic UI templates miss a needed interaction] -> Express OAuth and resource progress through
  platform guided-action primitives; feed reusable gaps into the platform contract rather than add
  librespot React code.
- [PipeWire CLI behavior changes] -> Declare the required CLI capability, test the exact command
  against the deployed PipeWire version, and keep a future native bridge behind the same source
  contract.

## Migration Plan

1. Complete and validate `extensible-plugin-platform`, including the managed-source, declarative
   page, plugin overlay, SDK, and first-party catalogue contracts.
2. Create `open-cinema-librespot` with the manifest, package skeleton, fake runtime, option map, CI,
   and contract tests before adding live Spotify behavior.
3. Add multi-instance storage/descriptors, declarative pages, authentication, supervision, bridge,
   events, health, and graph-source contribution behind a development catalogue entry.
4. Build and smoke-test pinned x86-64 and ARM64 artifacts, then publish the first plugin release and
   replace the development entry with immutable artifact URLs and digests.
5. Install from the marketplace on the Raspberry Pi, create one discovery instance, and validate
   Connect visibility, PipeWire correlation, Devices/Managed resources, volume/mute semantics, and
   manual graph routing.
6. Validate multiple instances and the TV/Spotify active-source plus headset/speakers priority
   graph, including pause, disconnect, process crash, restart, plugin disable, and appliance reboot.
7. Record CPU, memory, thermal, cache, latency, transition-gap, restart, and recovery evidence;
   update documentation and close the release only after published-artifact verification.

Rollback deactivates or uninstalls the plugin through the plugin platform, restores the previous
plugin overlay generation when needed, and leaves desired graphs loadable with unavailable source
references. The existing TV/Bluetooth/ROC inputs and active output fallback remain core-owned and
can be applied independently. No pre-release librespot plugin data requires migration.
