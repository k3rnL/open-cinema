## Purpose

Defines signal-format observations and adaptive processing behavior so Open Cinema can react safely to PCM and IEC-61937 content without conflating transport, encoded content, and decoded output.

## ADDED Requirements

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
