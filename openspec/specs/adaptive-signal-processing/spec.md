# Adaptive Signal Processing Specification

## Purpose

TBD: Describe the adaptive signal-processing capability and its user-visible contract after archive.

## Requirements

### Requirement: Decoder exposes one stable adaptive output
The managed decoder SHALL expose one stable logical and native PipeWire PCM output for PCM bypass and every supported decoded codec rather than separate PCM and decoded outputs.

#### Scenario: Movie returns to a PCM menu
- **WHEN** a stable encoded programme changes to stable PCM content
- **THEN** the decoder changes its internal mode while retaining the same managed output identity and output port contract

#### Scenario: Codec changes
- **WHEN** the input changes from one supported encoded codec to another
- **THEN** the decoder resets codec-specific state and continues through the same managed output identity

### Requirement: Decoder distinguishes observed and emitted formats
The decoder status interface SHALL report the carrier transport, encoded content, actual decoded-frame format, and emitted output format as separate structured values.

#### Scenario: Five-one content on a seven-one working bus
- **WHEN** the decoder observes six-channel decoded frames and emits an eight-channel configured working contract
- **THEN** status reports the six-channel decoded format and eight-channel emitted format without treating either as the other

#### Scenario: Plain stereo PCM
- **WHEN** the input is confirmed two-channel PCM
- **THEN** status reports PCM content, no decoded-frame descriptor, and the configured emitted output descriptor

### Requirement: Working output contract is stable and configurable
The desired decoder node SHALL declare a working output sample rate and channel layout that remain stable across content changes until graph intent or downstream requirements change them.

#### Scenario: Two to six to eight channel content
- **WHEN** confirmed content changes successively between stereo, 5.1, and 7.1 while the configured working layout remains 7.1
- **THEN** the physical output contract remains eight-channel PCM and missing programme channels are silent

#### Scenario: Content exceeds working layout
- **WHEN** decoded content cannot be represented by the configured working layout without dropping or combining channels
- **THEN** the decoder reports an explicit incompatible-output error and does not silently discard channels

### Requirement: Native streams are externally routable managed resources
The decoder SHALL publish stable per-instance PipeWire node, stream, and group properties that Open Cinema can correlate without runtime numeric identifiers, and SHALL not select arbitrary targets itself.

#### Scenario: Decoder restarts
- **WHEN** a managed decoder process restarts and receives new PipeWire numeric identifiers
- **THEN** Open Cinema rematches its capture and adaptive output by stable instance properties

#### Scenario: No route is active
- **WHEN** the decoder is ready but no desired route links its ports
- **THEN** its native streams remain unconnected rather than autoconnecting to session defaults

### Requirement: Uncertain transitions are silent and bounded
The decoder SHALL emit silence while classification is unknown or changing and SHALL apply configurable confidence and stability controls before emitting the new PCM or decoded programme.

#### Scenario: Encoded framing disappears
- **WHEN** IEC-61937 framing disappears but the PCM classification window is incomplete
- **THEN** encoded bytes are not emitted as PCM and the adaptive output contains silence

#### Scenario: Classification stabilizes
- **WHEN** the configured confirmation and stability conditions are satisfied
- **THEN** the decoder flushes stale mode state and begins emitting the newly selected content through the existing output contract

### Requirement: Decoder supports home-cinema channel layouts
The decoder SHALL support mono, stereo, 5.1 side, 5.1 rear, and 7.1 channel layouts with explicit positions for observed decoded content and configured emitted output.

#### Scenario: Seven-one decoded frames
- **WHEN** a supported codec produces a 7.1 decoded frame
- **THEN** all eight channel positions are reported and can be represented on a compatible working output

### Requirement: Signal descriptors separate transport, content, and decoded output
The system SHALL represent transport format, encoded-content format, and decoded or processor-output format as distinct structured values with confidence and observation time.

#### Scenario: AC-3 over SPDIF
- **WHEN** two-channel S16LE IEC-61937 transport containing AC-3 is detected and decoded to six-channel PCM
- **THEN** the signal descriptor records the transport, AC-3 content codec, and decoded PCM layout separately

#### Scenario: Plain PCM
- **WHEN** no encoded framing is detected with sufficient confidence
- **THEN** the descriptor identifies PCM content and does not invent an encoded codec

### Requirement: Decoder reports structured state
The decoder SHALL expose a versioned local status and event interface containing lifecycle, mode, detected framing, codec, decoded rate, format, channels, channel layout, confidence, and errors.

#### Scenario: Codec changes
- **WHEN** the decoder changes from AC-3 to DTS
- **THEN** it emits a structured event that identifies both the new codec and the current decoded-output contract

#### Scenario: Decoder starts before input
- **WHEN** the decoder is ready but has not classified enough input
- **THEN** status reports unknown or detecting mode rather than PCM by default

### Requirement: Format observations trigger resolution
The system SHALL treat material changes to the active signal descriptor as world-state changes that can select, bypass, or reconfigure processing branches.

#### Scenario: PCM changes to IEC-61937
- **WHEN** a stable PCM input becomes an encoded IEC-61937 signal
- **THEN** resolution enables the configured decoder path and selects compatible downstream processing

### Requirement: Adaptive decisions use stability controls
The system SHALL support configurable detection windows, minimum confidence, hysteresis, and cooldown so noisy observations do not repeatedly switch processing paths.

#### Scenario: Brief false preamble
- **WHEN** a single low-confidence preamble appears below the configured switching threshold
- **THEN** the active processing path remains unchanged and diagnostics record the ignored observation

### Requirement: Decoder bypass is explicit
A desired graph SHALL explicitly declare whether PCM bypass, encoded decoding, passthrough, silence, or error is permitted for each adaptive decoder node.

#### Scenario: PCM bypass allowed
- **WHEN** the input is confirmed PCM and bypass is allowed
- **THEN** resolution selects the PCM bypass branch

#### Scenario: Unsupported encoded codec
- **WHEN** an encoded codec is detected for which no permitted decoder or passthrough path exists
- **THEN** the plan enters an explicit degraded or error state and does not send encoded frames into a PCM-only processor

### Requirement: Actual decoded format is authoritative
The decoder SHALL report the format produced from decoded frames, and the resolver SHALL prefer that observation over static codec assumptions.

#### Scenario: Codec carries stereo content
- **WHEN** an AC-3 stream decodes to stereo rather than the maximum configured channel count
- **THEN** downstream planning uses the observed stereo layout

### Requirement: Decoder communication failure is visible
The system SHALL distinguish decoder process failure, status-channel failure, unknown signal, decode error, and unsupported codec.

#### Scenario: Status socket disconnects
- **WHEN** the decoder process remains present but its status interface becomes unavailable
- **THEN** processor health becomes unknown or degraded and automatic format-dependent transitions follow configured safe behavior

### Requirement: Signal state is available to users and plugins
Current and recent signal descriptors SHALL be available through orchestration APIs and processing-plugin planning context.

#### Scenario: User inspects TV input
- **WHEN** a user views the active TV route
- **THEN** the UI can show transport format, detected codec, decoded format, channel layout, and the processing decision they caused
