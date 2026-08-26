## MODIFIED Requirements

### Requirement: CamillaDSP exposes stable PipeWire-facing endpoints
Managed CamillaDSP instances SHALL expose stable, identifiable input and output nodes or streams whose complete declared port sets can be matched after process or PipeWire restart. A node match without all ports required by the selected profile SHALL NOT satisfy route readiness.

#### Scenario: CamillaDSP restarts
- **WHEN** the processor restarts and receives new runtime identifiers
- **THEN** reconciliation rematches its managed endpoints and all profile-required ports before restoring the intended route

#### Scenario: CamillaDSP node appears before all declared ports
- **WHEN** a managed CamillaDSP node is observed but one or more channels required by its active profile are absent
- **THEN** the instance remains waiting for runtime resources and programme ingress is not connected to it

### Requirement: Reconfiguration is coordinated safely
The processor SHALL participate in ordered suppress, configure, resource-readiness, downstream-route, topology-verification, ingress-activation, final-verification, and recovery behavior when a change can alter sample format, rate, channels, runtime identities, or audible output.

#### Scenario: Channel count changes
- **WHEN** a route changes from six-channel speakers to two-channel headphones
- **THEN** no incompatible audio is intentionally sent during the CamillaDSP reconfiguration window

#### Scenario: Eight-channel route is restored after restart
- **WHEN** CamillaDSP restarts while an eight-channel profile remains selected
- **THEN** all required output and input channels are linked and freshly verified before the source-facing link activates processing, and a partial route is never reported converged

#### Scenario: Topology verification fails
- **WHEN** CamillaDSP is process-healthy but its required PipeWire links do not converge before timeout
- **THEN** its affected route remains safely suppressed, the applied plan is not advanced, and diagnostics distinguish topology failure from processor control health
