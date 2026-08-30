## ADDED Requirements

### Requirement: Managed software sources have dual inventory projections
Each plugin-managed audio source instance SHALL appear in Devices as one durable logical input and
in Managed resources as one supervised software resource. The two projections SHALL share the
plugin and instance identity while separately describing endpoint availability/controls and
process lifecycle/health.

#### Scenario: Librespot instance is running
- **WHEN** the plugin observes a healthy instance and one correlated PipeWire source
- **THEN** Devices shows its logical Spotify input and candidate state while Managed resources shows the librespot/bridge resource group and its supported actions

#### Scenario: Instance is enabled but its process failed
- **WHEN** the logical instance remains configured but its resource group is unhealthy
- **THEN** Devices retains the input as unavailable with last-seen information and Managed resources exposes the failure and safe recovery action

#### Scenario: Instance is disabled
- **WHEN** an administrator disables one librespot instance
- **THEN** its durable input remains known as unavailable, its managed resource reports stopped by desired state, and other instances remain unaffected

### Requirement: Managed-source candidates bind through provider correlation
A managed-source logical endpoint SHALL resolve only to runtime objects whose fresh core
observation matches the provider-declared plugin ID, instance ID, generation, direction, media
class, and signal properties. User binding SHALL NOT weaken those required ownership predicates.

#### Scenario: Unrelated playback stream has a similar name
- **WHEN** another application creates a PipeWire stream whose description resembles the librespot device name but lacks its correlation properties
- **THEN** it is not adopted as the managed-source candidate

#### Scenario: Writable source level is observed
- **WHEN** the uniquely correlated stream exposes writable volume or mute
- **THEN** Devices advertises the corresponding standard endpoint controls and current freshness token

