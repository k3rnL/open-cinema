## ADDED Requirements

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
