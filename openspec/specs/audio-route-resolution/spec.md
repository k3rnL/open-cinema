# Audio Route Resolution Specification

## Purpose

Defines how Open Cinema deterministically transforms a desired graph and current world state into an explainable resolved plan without mutating the user's saved intent.

## Requirements

### Requirement: Resolution consumes a consistent world snapshot
The resolver SHALL evaluate one published desired-graph revision against one consistent versioned snapshot of endpoints, signals, processor health, parameters, rules, and manual overrides.

#### Scenario: Runtime changes during resolution
- **WHEN** a newer runtime event arrives while a plan is being resolved
- **THEN** the current resolution completes against its original snapshot and a subsequent resolution is scheduled for the newer snapshot

### Requirement: Conditions are evaluated against typed facts
The system SHALL support conditions over endpoint availability and activity, signal transport and codec, channel layout, processor health, user mode, graph parameters, and manual overrides.

#### Scenario: Headset availability condition
- **WHEN** a headset endpoint changes from unavailable to route-available
- **THEN** conditions referencing headset availability are reevaluated

#### Scenario: Decoder codec condition
- **WHEN** the active signal descriptor changes from PCM to IEC-61937 AC-3
- **THEN** codec-dependent processing branches are reevaluated

### Requirement: Selectors support priority and fallback
The resolver SHALL support ordered exclusive selection with explicit priority, eligibility conditions, and fallback behavior.

#### Scenario: Headset overrides speakers
- **WHEN** the headset output is eligible with higher priority than the main speakers
- **THEN** the resolved plan selects the headset as the exclusive primary output

#### Scenario: Preferred endpoint disappears
- **WHEN** the selected headset becomes unavailable and the main speakers remain eligible
- **THEN** the resolved plan selects the main speakers as fallback

### Requirement: Graphs support fan-out and mixing intent
The resolver SHALL distinguish exclusive selection, fan-out to multiple targets, and mixing of multiple sources, and SHALL require explicit graph nodes or policies for each behavior.

#### Scenario: Mirror output
- **WHEN** a fan-out node targets two compatible available outputs
- **THEN** both targets appear in the resolved plan

#### Scenario: Multiple sources without mixer
- **WHEN** two simultaneously active sources reach an input that does not declare mixing support
- **THEN** resolution reports a conflict instead of implicitly mixing them

### Requirement: Resolution negotiates compatible signal paths
The resolver SHALL compare source signal descriptors, processor input/output contracts, and endpoint capabilities to select compatible formats or required adapters.

#### Scenario: Decoded 5.1 to stereo headset
- **WHEN** a decoder produces six-channel audio and the selected headset accepts stereo
- **THEN** the plan selects an allowed downmix or compatible processing profile, or reports incompatibility if none is configured

#### Scenario: Compatible path exists
- **WHEN** all adjacent stages share a directly compatible format
- **THEN** the plan does not add an unnecessary conversion stage

### Requirement: Manual overrides have explicit scope and lifetime
The system SHALL support manual overrides with a target, scope, creation time, optional expiry, and precedence over automatic rules as configured.

#### Scenario: Temporary output override
- **WHEN** a user selects the headset for one hour
- **THEN** eligible routes use the headset until expiry or cancellation, after which automatic resolution resumes

#### Scenario: Override target unavailable
- **WHEN** a locked output override targets an unavailable endpoint
- **THEN** the resolved state reports waiting or uses only the override's explicitly configured fallback behavior

### Requirement: Resolution is deterministic
The resolver SHALL produce the same resolved plan and explanation for equivalent desired input and world state, including deterministic tie-breaking.

#### Scenario: Equal priority candidates
- **WHEN** two candidates have equal priority and eligibility
- **THEN** the resolver uses the declared secondary ordering or reports an unresolved tie rather than relying on iteration order

### Requirement: Resolved plans are explainable
Every resolved plan SHALL identify selected and rejected branches, the facts and rules involved, parameter values, compatibility decisions, warnings, and the source revisions used.

#### Scenario: Inspect selected route
- **WHEN** a user requests the explanation for an active route
- **THEN** the response shows why each input, processor, and output was selected and why higher or lower alternatives were rejected

### Requirement: Unresolvable intent produces explicit state
The resolver SHALL classify graphs with no complete route as waiting, degraded, conflicted, or invalid and SHALL preserve all diagnostic causes.

#### Scenario: Required input absent
- **WHEN** a required input has no matching available endpoint and no fallback
- **THEN** the plan is waiting and identifies the missing logical endpoint

#### Scenario: Optional processor unavailable
- **WHEN** an optional processor is unhealthy and an allowed bypass exists
- **THEN** the plan is degraded, selects the bypass, and records the processor failure
