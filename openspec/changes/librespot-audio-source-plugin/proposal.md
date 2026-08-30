## Why

Open Cinema needs a first-party Spotify Connect source that can be configured like the rest of the
appliance, remain discoverable independently from graph activation, and participate in automatic
PipeWire routing. Building it as a separate plugin is also the acceptance case for the new
installable-plugin and declarative-UI contracts.

## What Changes

- Create the separate `open-cinema-librespot` repository and installable plugin distribution with
  its own tests, documentation, CI, platform artifacts, release workflow, and first-party catalogue
  entry.
- Let administrators create and manage multiple independently named librespot instances from a
  dedicated Spotify Connect menu rendered through the declarative plugin UI.
- Represent every enabled instance as a supervised long-lived managed audio source with health,
  start, stop, restart, logs/diagnostics, authentication state, and a stable correlated PipeWire
  PCM stream.
- Expose each instance as a durable logical input and graph source so route resolution can use its
  availability, session, playback, and active-signal facts in ordered selectors and fallbacks.
- Provide typed, grouped controls for every safe and meaningful option in the pinned librespot
  options contract. Open Cinema-owned transport, cache paths, and audio-session choices are shown
  as managed values; deprecated, unsafe, or incompatible choices are unavailable with an
  explanation rather than passed through as arbitrary arguments.
- Support Spotify Connect discovery by default, guided OAuth, and write-only access-token
  authentication without offering deprecated password login.
- Pin and audit the supported librespot release and build capabilities so upstream option or binary
  drift cannot silently change the plugin contract.

## Capabilities

### New Capabilities

- `librespot-managed-audio-source`: Multi-instance librespot configuration, authentication,
  supervision, option mapping, PipeWire publication, resource controls, health, UI, packaging, and
  release behavior.

### Modified Capabilities

- `desired-audio-graphs`: Desired graphs can reference a stable plugin-managed source instance as
  an audio-producing endpoint role without persisting its transient PipeWire identity.
- `audio-route-resolution`: Resolution consumes plugin-source availability and activity facts,
  correlates the chosen instance to one current PipeWire stream, and explains fallback decisions.
- `audio-endpoint-inventory`: A plugin-managed source has durable logical input identity in Devices
  while its supervised process group remains separately visible in Managed resources.

## Impact

This change depends on `extensible-plugin-platform` and primarily creates
`/home/edaniel/PyCharmProjects/open-cinema-librespot`. It also adds the first-party catalogue pin
and acceptance fixtures in Open Cinema, exercises the generic plugin UI in `open-cinema-ui`, and
adds Raspberry Pi installation and audio acceptance evidence. Runtime dependencies include a
pinned librespot build and a PipeWire bridge; the plugin does not add a PulseAudio backend or take
over WirePlumber session management.
