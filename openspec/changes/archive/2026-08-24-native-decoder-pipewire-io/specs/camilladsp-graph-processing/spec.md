## ADDED Requirements

### Requirement: CamillaDSP uses native PipeWire processing nodes
Managed CamillaDSP version 4 or later instances SHALL use native PipeWire capture and playback nodes with stable per-instance names and groups and with backend autoconnect disabled.

#### Scenario: Instance becomes ready
- **WHEN** Open Cinema starts a prepared CamillaDSP instance
- **THEN** the instance publishes one matchable native capture node and one matchable native playback node for WirePlumber-managed linking

### Requirement: Destination profile is independent from transient content layout
The default CamillaDSP profile SHALL be selected from desired route intent, output association, parameters, and compatible working contract rather than from programme channel count alone.

#### Scenario: Stereo menu on room speakers
- **WHEN** a room-speaker route changes from a 5.1 movie to a stereo menu without an explicit content-dependent rule
- **THEN** the room CamillaDSP profile and native node contracts remain active

#### Scenario: Explicit content rule
- **WHEN** a graph rule explicitly selects a different processing profile for a stable observed content format
- **THEN** resolution may select and safely activate that profile with an explanation identifying the rule and observation

### Requirement: CamillaDSP accepts a stable working bus
The system SHALL support CamillaDSP profiles whose capture channel layout is a stable working bus while playback channels and explicit mixers represent the selected destination.

#### Scenario: Stereo carried on a seven-one working bus
- **WHEN** only front-left and front-right programme channels are active on an eight-channel room bus
- **THEN** the unchanged CamillaDSP configuration processes those channels and treats inactive channels as silence

#### Scenario: Seven-one input to five-one speakers
- **WHEN** an eight-channel working bus targets a six-channel speaker profile
- **THEN** a declared CamillaDSP mixer performs the 8-to-6 adaptation rather than the decoder silently dropping channels
