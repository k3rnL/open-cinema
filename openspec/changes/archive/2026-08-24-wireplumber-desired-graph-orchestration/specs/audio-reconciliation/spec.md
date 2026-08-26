## Purpose

Defines continuous, idempotent reconciliation between resolved audio intent and the live WirePlumber, decoder, and CamillaDSP state, including safe transitions and failure recovery.

## ADDED Requirements

### Requirement: Relevant changes trigger reconciliation
The system SHALL schedule reconciliation when the published graph, parameter values, endpoint inventory, signal descriptor, processor health, manual override, or applied runtime state changes.

#### Scenario: Headset connects
- **WHEN** a headset becomes eligible for a higher-priority output rule
- **THEN** the system resolves and reconciles a new plan without requiring the user to reapply the graph

### Requirement: Reconciliation is debounced and convergent
The system SHALL coalesce bursts of related observations, avoid overlapping mutations for the same graph scope, and repeatedly converge toward the latest resolved plan.

#### Scenario: Bluetooth emits multiple discovery events
- **WHEN** one device connection produces several rapid device, profile, route, node, and port events
- **THEN** the system coalesces them into stable reconciliation work while still converging on the final state

### Requirement: Runtime operations are idempotent
Every reconciliation action SHALL be safe to retry or SHALL be guarded by observed preconditions and an idempotency key.

#### Scenario: Worker restarts after applying a target
- **WHEN** a worker applies an operation but restarts before persisting completion
- **THEN** retrying reconciliation recognizes the already-applied state and does not create duplicate runtime resources

### Requirement: Plans are applied as ordered transitions
The system SHALL generate an ordered transition plan that accounts for processor readiness, format changes, route changes, muting, link movement, and cleanup.

#### Scenario: Switch speaker profile to headset
- **WHEN** the output changes from room speakers to a stereo headset
- **THEN** the transition prepares the compatible processing path, prevents unsafe audible output, moves routing, verifies readiness, and removes obsolete resources in the declared order

### Requirement: Unsafe transitions are suppressed
The system SHALL support configurable mute, drain, fade, or pause steps around transitions that could otherwise produce noise, invalid formats, or partially connected audio.

#### Scenario: CamillaDSP format changes
- **WHEN** a new plan requires reconfiguring CamillaDSP from six channels to two channels
- **THEN** the system suppresses output until the new processing configuration and route are verified

### Requirement: Failed transitions preserve or restore service
The system SHALL define rollback or safe-degraded behavior for each reversible action group and SHALL not report a new plan active until required verification succeeds.

#### Scenario: New target fails verification
- **WHEN** the target endpoint disappears during transition
- **THEN** the system restores the previous viable route when possible or enters a safe waiting/degraded state with output suppressed as configured

### Requirement: Reconciliation publishes lifecycle status
The system SHALL expose desired revision, resolved plan revision, applied plan revision, reconciliation phase, health state, pending cause, last success, and last failure.

#### Scenario: Plan is converged
- **WHEN** all required runtime facts match the resolved plan
- **THEN** status is resolved and desired, resolved, and applied revisions are correlated

#### Scenario: External mutation causes drift
- **WHEN** an external tool changes a managed target or link
- **THEN** the system reports drift and reconciles or yields according to the graph's ownership policy

### Requirement: Retries use bounded backoff
The system SHALL retry transient failures with bounded exponential backoff and jitter and SHALL stop automatic retries for classified permanent configuration errors until relevant input changes.

#### Scenario: WirePlumber temporarily unavailable
- **WHEN** the runtime connection is lost
- **THEN** reconciliation retries with backoff and performs a fresh observation before applying pending actions after reconnection

#### Scenario: Invalid processor configuration
- **WHEN** a processor rejects a configuration as invalid
- **THEN** the system records a permanent plan error and does not loop continuously until the configuration or inputs change

### Requirement: Reconciliation is auditable
The system SHALL retain structured events for resolution decisions, transition actions, external drift, retries, failures, rollbacks, and user overrides with correlation identifiers.

#### Scenario: Diagnose an automatic switch
- **WHEN** audio moves from speakers to a headset
- **THEN** an operator can trace the triggering observation, winning rule, generated transition, runtime operations, and final verification
