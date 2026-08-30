## ADDED Requirements

### Requirement: Resolution consumes managed-source lifecycle and activity facts
The resolver SHALL evaluate a plugin-managed source using one fresh snapshot containing plugin
state, instance desired and observed state, resource health, PipeWire correlation, route
availability, authentication, session, playback, active signal, and activity-hold state. A stale,
ambiguous, disabled, or unhealthy source SHALL NOT be treated as actively eligible.

#### Scenario: Spotify activity has priority over TV
- **WHEN** an ordered selector gives an actively playing librespot instance priority over an available TV input
- **THEN** the resolved plan selects Spotify while its active-signal condition is true

#### Scenario: Spotify playback stops
- **WHEN** the instance's active signal clears after its declared hold interval and the TV input remains eligible
- **THEN** the next plan selects the TV fallback without stopping the librespot discovery resource

#### Scenario: Librespot remains idle but healthy
- **WHEN** a selector requires active signal and the instance is merely route-available
- **THEN** the explanation rejects that candidate for inactivity rather than reporting it unavailable

### Requirement: A selected managed source resolves to one correlated runtime stream
When a plugin-managed source is selected, the resolved plan SHALL identify its stable provider and
instance, expected signal contract, one current correlated PipeWire stream, correlation evidence,
and world generation. It SHALL reject zero or ambiguous candidates and SHALL NOT ask the plugin to
select a physical output.

#### Scenario: One healthy stream is correlated
- **WHEN** the selected librespot instance has exactly one fresh stream matching its correlation identity and signal contract
- **THEN** the resolved plan routes that stream through the remaining desired graph and explains the instance and runtime match

#### Scenario: Two streams claim one instance
- **WHEN** duplicate live streams expose the same provider and instance identity
- **THEN** the plan is degraded or conflicted, identifies both candidates, and creates no arbitrary route

