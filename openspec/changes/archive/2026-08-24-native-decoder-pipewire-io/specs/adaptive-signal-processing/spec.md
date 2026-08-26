## ADDED Requirements

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
