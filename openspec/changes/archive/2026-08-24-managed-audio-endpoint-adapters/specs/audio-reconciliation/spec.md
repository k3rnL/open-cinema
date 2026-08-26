## ADDED Requirements

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
