## ADDED Requirements

### Requirement: Equivalent format resolutions do not mutate runtime resources
The reconciler SHALL compare the effective resolved plan after a material signal-format observation and SHALL perform no processor, link, route, or profile mutation when that plan is unchanged.

#### Scenario: Five-one movie returns to stereo menu
- **WHEN** the decoder observation changes from 5.1 decoded content to stereo PCM but both resolve to the same adaptive output contract, route, and CamillaDSP profile
- **THEN** the new observation and explanation are recorded while the applied runtime resources remain unchanged

#### Scenario: Content-dependent profile rule matches
- **WHEN** a stable observation changes the resolved CamillaDSP profile through an explicit rule
- **THEN** reconciliation performs the required safe processor transition because the effective plan changed
