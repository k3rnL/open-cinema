## Purpose

Defines a first-party, multi-instance Spotify Connect integration whose librespot processes,
configuration, PipeWire streams, graph identity, health, and administration remain fully managed by
Open Cinema.

## ADDED Requirements

### Requirement: Librespot is delivered as an independently released first-party plugin
The integration SHALL be packaged under the stable plugin identity from the
`open-cinema-librespot` repository, SHALL satisfy the public plugin contract, and SHALL be available
from the first-party catalogue as immutable, digest-verified artifacts for every supported Linux
architecture.

#### Scenario: Administrator installs from the marketplace
- **WHEN** a compatible Open Cinema appliance installs the first-party librespot catalogue entry
- **THEN** the verified plugin package, bundled runtime asset, contract version, source commit, and supported platform are recorded before activation

#### Scenario: Runtime architecture has no artifact
- **WHEN** the catalogue has no compatible librespot plugin artifact for the appliance architecture
- **THEN** installation is unavailable with the missing platform identified and no source build is silently attempted on the appliance

### Requirement: Administrators can manage multiple independent instances
The plugin SHALL allow any supported number of librespot instances subject to appliance capacity.
Each instance SHALL have stable identity, unique Spotify Connect name, independent desired enabled
state, configuration, authentication/cache state, PipeWire correlation, health, and operations.

#### Scenario: Two instances are enabled
- **WHEN** an administrator creates and enables “Living room Spotify” and “Headphones Spotify”
- **THEN** both are independently discoverable and produce separately identifiable managed resources and logical audio inputs

#### Scenario: Instance identity fields conflict
- **WHEN** a new or edited instance would collide with another instance's Connect name, runtime correlation key, or fixed network binding
- **THEN** validation identifies the conflicting field before restarting either instance

#### Scenario: Referenced instance is deleted
- **WHEN** an administrator confirms deletion of an instance referenced by a saved graph
- **THEN** the graph remains preserved with an unavailable-instance diagnostic and unrelated instances continue operating

### Requirement: The dedicated administration page uses typed product UI
An enabled plugin SHALL contribute a Spotify Connect menu with an instance overview, create flow,
instance detail/settings, authentication state, audio status, health, diagnostics, and lifecycle
actions using the declarative Open Cinema UI contract.

#### Scenario: User creates an instance
- **WHEN** an administrator completes the guided instance form
- **THEN** required identity and routing settings are validated before one stable instance is created and its lifecycle progress is shown without raw JSON editing

#### Scenario: Instance is healthy and playing
- **WHEN** the plugin reports a connected client and active playback
- **THEN** the overview shows the instance, Spotify name, enabled/running state, playing state, source format, selected graph use, and current actions in a stable layout

### Requirement: Every upstream option is explicitly classified
The plugin SHALL maintain a versioned mapping for every option advertised by the pinned librespot
release. Each option SHALL be represented as user-configurable, represented by an equivalent safe
Open Cinema control, fixed and displayed as managed, or unavailable with a reason. Release
validation SHALL fail when the pinned binary adds, removes, or changes an option without updating
that mapping.

#### Scenario: Pinned option set is audited
- **WHEN** plugin CI builds or updates the supported librespot binary
- **THEN** its help output is compared with the committed option mapping and every difference requires an intentional contract change

#### Scenario: Managed option is inspected
- **WHEN** an administrator reviews backend, device, format, dither, mixer, cache path, help, or version behavior
- **THEN** the UI shows the effective Open Cinema-managed value and explanation rather than an editable arbitrary argument

#### Scenario: Unsupported option is inspected
- **WHEN** an administrator reviews deprecated password login, ALSA mixer ownership, raw passthrough, or arbitrary event-program execution
- **THEN** the UI identifies why the option is unavailable and does not pass it to the librespot process

### Requirement: Safe playback, discovery, network, and cache options are typed
The plugin SHALL provide typed configuration and upstream-compatible validation for device name,
device type, bitrate, log level equivalent to quiet/verbose, proxy, AP port, disable discovery,
initial volume, zeroconf backend, zeroconf port, zeroconf interfaces, volume normalisation and all
normalisation parameters, volume control curve and range, autoplay, gapless behavior, audio-cache
enablement and size, credential-cache enablement, and repeatable local-file directories.

#### Scenario: Normalisation is enabled
- **WHEN** an administrator selects basic or dynamic normalisation
- **THEN** only the gain type, pregain, threshold, and method-appropriate attack, release, and knee controls are shown and validated

#### Scenario: Local media directories are configured
- **WHEN** an administrator adds one or more allowed local-file directories
- **THEN** their order and repetition are preserved, inaccessible or prohibited paths are rejected, and the UI explains that a resource restart is needed to rescan them

#### Scenario: Compiled choice is unavailable
- **WHEN** the pinned binary was not built with a selected zeroconf backend
- **THEN** that choice is disabled with its build-capability reason instead of producing a runtime launch failure

### Requirement: Open Cinema owns librespot audio transport choices
The plugin SHALL run librespot through a managed raw-PCM transport with an Open Cinema-selected
backend, internal device/pipe, software mixer, PCM format, and dithering policy. It SHALL NOT offer
direct ALSA, PulseAudio, JACK, GStreamer, hardware-mixer, or passthrough routing that bypasses the
desired graph and WirePlumber-controlled PipeWire session.

#### Scenario: Instance launches
- **WHEN** a valid enabled instance is reconciled
- **THEN** its effective backend, device, mixer, PCM format, and dither arguments exactly match the plugin's declared managed signal contract

#### Scenario: User needs a different physical output
- **WHEN** an administrator wants Spotify audio on a headset instead of speakers
- **THEN** the output is selected in the desired graph rather than by changing librespot's backend or device

### Requirement: Authentication supports discovery, OAuth, and access token
Each instance SHALL support discovery authentication as the default, a guided OAuth operation, and
a write-only streaming-scope access token. Deprecated password authentication SHALL NOT be
available. Username/cached-credential selection, OAuth port behavior, cache prerequisites, expiry,
and authentication failures SHALL be represented with typed state and help.

#### Scenario: Discovery-only instance is started
- **WHEN** an administrator enables a new instance without stored credentials
- **THEN** it appears as a Spotify Connect target and can receive credentials from a Spotify client without a password field

#### Scenario: Headless OAuth is completed
- **WHEN** the administrator starts OAuth, opens the presented authorization URL on another device, and submits the resulting callback when required
- **THEN** the operation validates and stores reusable credential state without exposing the credential material in the API or logs

#### Scenario: Access token is saved
- **WHEN** an administrator submits an access token
- **THEN** later forms report only that the secret exists and instance launch receives it without placing it in diagnostics or process listings

### Requirement: Event integration uses named automations rather than arbitrary programs
The upstream event-program and sink-event behavior SHALL be represented by an optional selection
of registered Open Cinema automation hooks and a typed sink-event toggle. The plugin SHALL emit a
bounded structured event document and SHALL NOT execute a user-provided executable path.

#### Scenario: Track event automation is configured
- **WHEN** librespot reports a supported playback event
- **THEN** the selected namespaced automation receives the instance ID, event type, bounded track/session metadata, and timestamp without a shell command

#### Scenario: Sink events are disabled
- **WHEN** no automation is selected or sink-event emission is off
- **THEN** the plugin does not expose an arbitrary `onevent` program or emit unrequested sink transitions

### Requirement: Enabled instances are long-lived managed resources
An enabled instance SHALL keep its supervised librespot and PipeWire bridge resource group running
independently from desired-graph activation so the Spotify Connect target and logical source remain
available. The plugin SHALL expose desired and observed process state, child identities, restart
count/backoff, start time, health, last error, and currently available start, stop, and restart
actions.

#### Scenario: No graph currently selects Spotify
- **WHEN** an instance is enabled but no active route selects it
- **THEN** its Connect target and unlinked PipeWire source remain available without sending audio directly to a physical sink

#### Scenario: One child process exits
- **WHEN** librespot or its PipeWire bridge exits unexpectedly
- **THEN** the whole instance resource becomes degraded or failed, bounded group restart policy is applied, and no duplicate surviving child is adopted as healthy

#### Scenario: Configuration changes
- **WHEN** an administrator saves a valid option that librespot cannot reconfigure live
- **THEN** only that managed instance is restarted and Open Cinema reports the expected brief source interruption

### Requirement: Each instance publishes one stable PCM source contract
The plugin SHALL publish one stereo 44.1-kHz PCM source per running instance with a fixed declared
sample format, channel map, media role, plugin ID, instance ID, and generation correlation
properties. The PipeWire stream SHALL not auto-connect to a sink; final links and targets remain
owned by Open Cinema reconciliation.

#### Scenario: PipeWire recreates the stream
- **WHEN** an instance restarts and receives new PipeWire object IDs
- **THEN** core observation correlates the new stream to the same plugin instance and logical input without changing saved graph references

#### Scenario: Correlation is ambiguous
- **WHEN** zero or multiple live streams claim the same instance correlation identity
- **THEN** the source is unavailable or ambiguous with diagnostics and the resolver does not select an arbitrary stream

### Requirement: Playback and activity facts are observable
The plugin SHALL expose route availability, authentication state, client/session connection,
playback state, active signal, track transition when available, and observation freshness for each
instance. Activity transitions SHALL trigger a fresh world snapshot and SHALL support a bounded
configurable hold interval to prevent rapid route flapping.

#### Scenario: Spotify begins playing
- **WHEN** a healthy idle instance changes to active playback
- **THEN** its active-signal fact becomes eligible after the configured transition policy and route resolution is scheduled

#### Scenario: Spotify pauses
- **WHEN** playback becomes paused or stopped
- **THEN** active signal clears after the configured hold interval while route availability and Spotify discovery remain intact

#### Scenario: State observation becomes stale
- **WHEN** neither process nor playback state can be confirmed within the freshness bound
- **THEN** activity-dependent selection treats the fact as unknown or ineligible rather than assuming audio is playing

### Requirement: Source level and mute remain explicit
The logical input SHALL expose current PipeWire level and mute controls only when its unique stream
candidate advertises writable values. Librespot initial volume and Spotify-client volume behavior
SHALL remain separately labelled from Open Cinema's PipeWire input trim to avoid presenting two
controls as one value.

#### Scenario: User changes input trim
- **WHEN** the correlated PipeWire source has writable level and mute controls
- **THEN** Devices applies the standard logical-endpoint mutation and the Spotify initial-volume setting remains unchanged

### Requirement: Health and diagnostics are safe and actionable
The plugin SHALL report pinned librespot and plugin versions, effective non-secret options,
authentication presence/state, process and bridge health, PipeWire correlation, activity
freshness, cache use, restart history, and bounded recent diagnostics. Secrets, callback codes,
credential cache contents, and proxy credentials SHALL be redacted.

#### Scenario: Librespot rejects an option
- **WHEN** the pinned process exits because an effective argument is invalid
- **THEN** the instance identifies the mapped field and process stage where possible without displaying secrets or an unbounded raw log

### Requirement: Published artifacts and documentation are reproducible
The plugin repository SHALL test source and wheel contract validation, supported Open Cinema
versions, process supervision with fakes, PipeWire integration, and Linux x86-64 and ARM64
artifacts. A release SHALL pin the librespot source/release, build features, plugin SDK, artifact
digests, and option mapping and SHALL document installation, authentication, configuration,
development, validation, release, troubleshooting, and graph use.

#### Scenario: Release candidate is built
- **WHEN** CI builds a tagged plugin version
- **THEN** every published platform artifact reports matching plugin/librespot identities, passes the contract and option audit, and is traceable to the tagged source commit

