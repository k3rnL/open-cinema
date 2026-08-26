# Speaker Channel Testing Specification

## Purpose

Provide administrators with a safe, bounded way to identify physical speaker
channels from the live PipeWire map without changing desired audio state.

## Requirements

### Requirement: Discover testable speaker outputs and their observed channel order

The system SHALL expose authenticated administrators to the currently available physical PCM output nodes that have an unambiguous observed channel map. Each output SHALL include its opaque runtime key, human-readable name, PipeWire target name, ordered channel positions, and current runtime generation. Managed adapters, processor nodes, unavailable projections, and outputs without a usable channel map SHALL NOT be offered for speaker testing.

#### Scenario: Multichannel physical output is available

- **WHEN** the runtime inventory contains a physical `Audio/Sink` with a known eight-channel PCM position map
- **THEN** the speaker-test API returns that output with all eight positions in the observed PipeWire order

#### Scenario: Output has no reliable channel map

- **WHEN** an output projection does not expose a usable ordered PCM position map or physical input ports
- **THEN** the speaker-test API omits it and does not invent a channel order

### Requirement: Generate a bounded test signal on exactly one selected channel

The system SHALL accept a selected output runtime key and one channel declared by that output, revalidate both against the current runtime projection, and generate a quiet finite test tone whose non-zero samples occur only in the selected channel. The playback stream SHALL target the selected PipeWire sink by its observed node name and use the complete observed channel map.

#### Scenario: Administrator starts a valid channel test

- **WHEN** an administrator starts a test for `FC` on an available output whose map contains `FC`
- **THEN** the system starts a labelled temporary PipeWire playback stream with signal only in the `FC` sample position and returns its bounded active state

#### Scenario: Runtime identity became stale

- **WHEN** the submitted runtime key no longer identifies the current output projection
- **THEN** the system rejects the request with a conflict response and asks the client to refresh instead of targeting a numeric node from an old generation

#### Scenario: Channel is not declared by the output

- **WHEN** the submitted channel is absent from the output's observed position map
- **THEN** the system rejects the request without starting any playback process

### Requirement: Test playback is temporary, exclusive, and stoppable

At most one speaker test SHALL be active across all web workers. Starting another test SHALL stop the preceding test first. Every test SHALL stop automatically after its server-bounded duration, and an administrator SHALL be able to stop it explicitly. Stale process state SHALL be detected without signalling an unrelated process.

#### Scenario: A second channel is selected during a test

- **WHEN** a test is active and an administrator starts a different channel test
- **THEN** the system terminates the first test before starting the second and reports only the second as active

#### Scenario: Test reaches its duration limit

- **WHEN** the finite test signal completes without an explicit stop request
- **THEN** the helper and PipeWire playback stream exit and a later status request reports no active test

#### Scenario: Administrator stops a test

- **WHEN** an administrator requests stop while a verified speaker-test helper is running
- **THEN** the helper process group is terminated within a bounded interval and status reports no active test

### Requirement: Speaker testing is an administrative diagnostic, not desired state

Only authenticated staff administrators SHALL be allowed to discover, start, inspect, or stop speaker tests. Speaker tests SHALL NOT create or update graph definitions, revisions, activations, logical endpoints, adapters, processors, or reconciliation-owned links.

#### Scenario: Non-administrator requests the diagnostic

- **WHEN** an authenticated non-staff user requests speaker-test state or attempts to start a test
- **THEN** the API denies the request and no diagnostic process is changed

#### Scenario: Test completes while a graph is active

- **WHEN** a speaker test runs and exits while a desired graph remains active
- **THEN** the graph's persisted desired and applied records remain unchanged

### Requirement: Admin UI provides a simple accessible channel tester

The Refine admin application SHALL provide a `Speaker test` menu and page built from the existing Ant Design components without new custom CSS. The page SHALL explain that other playback should be paused, allow selecting an eligible output, show one clearly labelled button per observed channel with expanded speaker names where known, visibly identify the active test, expose a Stop action, and present actionable loading, empty, stale-inventory, and failure states.

#### Scenario: User tests a connected speaker output

- **WHEN** the user selects an eight-channel output and presses `FC · Front center`
- **THEN** the UI starts the test, marks the front-center button as active, disables conflicting actions during the request, and retains a visible Stop control

#### Scenario: No testable output is connected

- **WHEN** the API returns no eligible outputs
- **THEN** the page explains that no physical PCM output with a known channel map is currently available and offers Refresh
