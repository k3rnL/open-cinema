# Audio Reconciliation Specification

## Purpose

TBD: Describe how resolved audio intent is reconciled with managed runtime resources after archive.

## Requirements

### Requirement: Equivalent format resolutions do not mutate runtime resources
The reconciler SHALL compare the effective resolved plan after a material signal-format observation and SHALL perform no processor, link, route, or profile mutation when that plan is unchanged.

#### Scenario: Five-one movie returns to stereo menu
- **WHEN** the decoder observation changes from 5.1 decoded content to stereo PCM but both resolve to the same adaptive output contract, route, and CamillaDSP profile
- **THEN** the new observation and explanation are recorded while the applied runtime resources remain unchanged

#### Scenario: Content-dependent profile rule matches
- **WHEN** a stable observation changes the resolved CamillaDSP profile through an explicit rule
- **THEN** reconciliation performs the required safe processor transition because the effective plan changed

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

### Requirement: Disabled graphs withdraw their applied runtime routes
The active orchestrator SHALL reconcile a disabled graph by removing all Open Cinema managed links owned by that graph, preserving resources and links owned by other graphs, and retaining a durable retryable record of the disabled desired state.

#### Scenario: Active graph cleanup converges
- **WHEN** a graph activation changes from enabled to disabled
- **THEN** its graph-owned managed links are removed through the transition journal and its applied state becomes idle with no current plan

#### Scenario: Two graphs have managed links
- **WHEN** one of two active graphs is disabled
- **THEN** only links whose desired identity belongs to the disabled graph are removed

#### Scenario: Runtime is already clean
- **WHEN** a disabled graph has no remaining managed links
- **THEN** reconciliation converges idempotently without attempting unrelated mutations

#### Scenario: Cleanup is interrupted
- **WHEN** link cleanup fails or the controller restarts before convergence
- **THEN** the disabled desired state remains authoritative and reconciliation can safely retry the graph-scoped cleanup

### Requirement: Managed processor topologies converge as verified transition groups
The reconciler SHALL treat every required managed link and processor port in one selected processor path as a single transition group. It SHALL NOT report the plan converged or expose programme audio to a replaced processor chain until a fresh observation proves that the complete required topology belongs to the current runtime generation.

#### Scenario: Eight-channel processor restarts with new runtime identifiers
- **WHEN** an eight-channel processor restarts and its nodes, ports, and links are recreated over several runtime observations
- **THEN** reconciliation waits for the complete required port set, establishes and verifies the whole selected topology, and exposes the processor path only after all eight channels match the current generation

#### Scenario: Only part of a processor topology can be restored
- **WHEN** one or more required processor ports or links remain absent after the bounded transition window
- **THEN** the plan is not reported active, the affected path remains safely suppressed or is restored to its previous viable route, and unrelated or unmanaged links are preserved

### Requirement: Processor topology activation is downstream-first
When a processor path cannot be mutated atomically by the runtime, the reconciler SHALL establish and verify the processor's downstream topology before connecting programme ingress, so an incomplete downstream path does not receive programme audio.

#### Scenario: Decoder and CamillaDSP recover together
- **WHEN** a decoder-to-CamillaDSP-to-output path is rebuilt after either processor disappears
- **THEN** the output-facing and internal links are verified before the source-facing ingress link activates the chain

### Requirement: Catch-up exhaustion remains self-progressing
When runtime observations continue advancing through the bounded in-call catch-up limit, the orchestrator SHALL record the pending cause and schedule a bounded delayed retry that does not depend on another external runtime or desired-state event.

#### Scenario: Runtime becomes quiet after the catch-up limit
- **WHEN** the runtime advances during every immediate catch-up pass and then emits no further event
- **THEN** the delayed retry observes the latest runtime state and reconciliation either converges or records a classified waiting or failure state

#### Scenario: Runtime continues changing across delayed retries
- **WHEN** processor registration and link events keep advancing the runtime across multiple retries
- **THEN** retries remain bounded and non-overlapping, use fresh observations, and do not busy-loop or apply stale runtime identities

#### Scenario: A satisfied no-op observation advances the runtime sequence
- **WHEN** processor readiness observation advances the PipeWire sequence while proving that the effective current-generation topology is already satisfied
- **THEN** the orchestrator publishes the newer authoritative runtime state without treating its own no-op observation as transition-invalidating churn or scheduling another catch-up pass

### Requirement: Incomplete processor transitions publish actionable evidence
The system SHALL expose whether a processor transition is preparing, waiting for runtime resources, routing downstream, verifying topology, activating ingress, converged, safely suppressed, or failed, together with missing processor identities, ports, links, runtime generation, retry cause, and last recovery result where applicable.

#### Scenario: One CamillaDSP output link is absent
- **WHEN** post-route verification observes seven of eight required CamillaDSP output links
- **THEN** status identifies the incomplete topology and missing channel without reporting the graph converged
