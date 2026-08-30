## Purpose

Defines a safe, user-facing appliance overview and control contract for observing Open Cinema health, resource use, installed component versions, and explicitly authorized restart operations.

## ADDED Requirements

### Requirement: Appliance overview reports useful system identity and health
The system SHALL expose an authenticated appliance overview containing hostname, hardware model when available, operating-system and kernel identity, uptime, storage use, temperature and throttling state when supported, application readiness, and the observation timestamp. Unsupported platform fields SHALL be identified as unavailable rather than causing the overview to fail.

#### Scenario: Raspberry Pi overview is available
- **WHEN** an authenticated administrator opens the dashboard on the Raspberry Pi
- **THEN** the UI presents the appliance identity, uptime, storage, temperature, throttling, and overall Open Cinema health with the age of the observation

#### Scenario: Optional platform sensor is unavailable
- **WHEN** the host cannot report a temperature or throttling field
- **THEN** the overview remains available and labels that field as unsupported or unavailable

### Requirement: Live resource metrics are bounded and freshness-aware
The system SHALL expose timestamped CPU and memory samples suitable for a live rolling display. The management client SHALL retain only a bounded recent window, SHALL use a bounded polling or streaming cadence, and SHALL indicate stale data after updates stop without clearing the last valid history.

#### Scenario: Dashboard remains open
- **WHEN** system metric samples continue to arrive
- **THEN** CPU and memory charts advance without unbounded browser or server memory growth

#### Scenario: Metrics stop updating
- **WHEN** no fresh sample arrives within the declared stale interval
- **THEN** the last graph remains visible and is marked stale instead of disappearing or displaying fabricated zero values

### Requirement: Installed component versions and lifecycle state are discoverable
The system SHALL return a stable component inventory containing a user-facing name, stable component identifier, installed version or explicit unknown state, lifecycle and health, last observation, and the actions currently supported for that component. The inventory SHALL include at least the Open Cinema web/API application, orchestration service, WirePlumber binding/runtime, CamillaDSP, and adaptive PCM decoder when installed.

#### Scenario: All expected components are installed
- **WHEN** the dashboard requests component information
- **THEN** it can display every component version and health without parsing command output in the browser

#### Scenario: A component does not expose a version
- **WHEN** a supervised component is present but its version cannot be determined
- **THEN** the component remains listed with version marked unknown and actionable diagnostics

### Requirement: Managed resource actions are capability advertised
Every managed resource representation SHALL distinguish observation from available control actions. An action SHALL be rendered as executable only when the server advertises an authenticated action identifier, current availability, and any required concurrency token; otherwise the resource remains readable with a reason that control is unavailable.

#### Scenario: Managed adapter supports restart
- **WHEN** a running managed adapter advertises a restart action
- **THEN** the Managed resources page offers Restart and reports progress until a newer healthy observation is received

#### Scenario: Processor is observation-only
- **WHEN** a processor projection has health information but no restart action
- **THEN** the Managed resources page shows its state without a non-functional Restart button

### Requirement: Service and appliance controls are allowlisted and guarded
Only authenticated staff administrators SHALL be able to request a restart. The server SHALL resolve client-visible component identifiers through a fixed allowlist, SHALL NOT accept arbitrary service names or commands, and SHALL advertise Open Cinema application restart, orchestrator restart, and full-appliance reboot only when the required host authorization is installed. The UI SHALL require confirmation, prevent duplicate submission, and explain the expected temporary disconnection.

#### Scenario: Administrator restarts the orchestrator
- **WHEN** an administrator confirms restart for the advertised orchestrator component using current action state
- **THEN** the server accepts one allowlisted operation and the UI follows its state from requested through reconnect and a fresh health observation

#### Scenario: Administrator reboots the appliance
- **WHEN** an administrator confirms full-appliance reboot
- **THEN** the server schedules the reboot, returns an accepted operation before shutdown when possible, and the UI enters a reconnecting state without reporting the expected connection loss as an unexplained error

#### Scenario: Host permission is not configured
- **WHEN** the deployment has not installed permission for an otherwise known restart action
- **THEN** the server advertises that action as unavailable with a reason and rejects direct attempts without invoking a command

#### Scenario: Client submits an arbitrary service name
- **WHEN** a client attempts to restart a component outside the server allowlist
- **THEN** the server rejects the request and does not pass the value to a process or service manager

### Requirement: Dashboard prioritizes daily operation
The management dashboard SHALL present overall health, active audio path, master volume, live resource use, device and processor availability, system identity, component versions, and guarded controls in a responsive hierarchy. Destructive system controls SHALL be visually separated from frequent audio controls, and detailed inventories SHALL link to their dedicated pages rather than duplicating full tables on the dashboard.

#### Scenario: User checks normal playback
- **WHEN** the appliance is healthy and a graph is active
- **THEN** the first dashboard region identifies the current source, processing path, selected output, format, volume, and health without requiring raw runtime inspection

#### Scenario: A component is degraded
- **WHEN** any required component reports degraded or unavailable
- **THEN** the dashboard summarizes the problem, preserves usable controls, and links to the affected resource or runtime explanation

