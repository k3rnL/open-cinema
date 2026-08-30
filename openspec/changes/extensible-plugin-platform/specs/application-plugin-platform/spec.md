## Purpose

Defines how administrators safely discover, install, configure, activate, update, diagnose, and
remove independently released Open Cinema plugins through a stable, documented contract.

## ADDED Requirements

### Requirement: Plugins expose a versioned distribution manifest
Every installable plugin SHALL provide static metadata that can be inspected before its runtime
code is activated, including stable plugin and distribution identifiers, vendor, version, license,
source and documentation links, supported plugin-contract and Open Cinema versions, supported
platforms, declared capabilities, requested permissions, dependencies, configuration version, and
lifecycle impact.

#### Scenario: Compatible manifest is inspected
- **WHEN** an administrator opens a catalogue or Git-sourced plugin candidate
- **THEN** the system presents its identity, provenance, compatibility, capabilities, permissions, dependencies, and lifecycle impact before offering installation

#### Scenario: Manifest is malformed
- **WHEN** a package omits required identity or compatibility metadata or contains an unknown mandatory contract feature
- **THEN** installation is rejected before the plugin entry point is activated and an actionable validation diagnostic is retained

### Requirement: One plugin identity can contribute multiple bounded capabilities
The plugin contract SHALL allow one stable plugin identity to contribute any supported combination
of namespaced APIs, automations, processing nodes, managed resources, managed audio sources, and
declarative administration pages without registering competing plugin identities.

#### Scenario: Composite plugin is discovered
- **WHEN** one compatible distribution declares an API, a managed audio source, and administration pages
- **THEN** the registry reports one plugin with three independently described capabilities and one lifecycle state

#### Scenario: Capability identifier conflicts
- **WHEN** two enabled plugins claim the same globally unique capability identifier
- **THEN** the registry rejects the conflicting capability without silently replacing an existing contribution

### Requirement: Compatibility is checked before activation
The system SHALL compare a plugin's declared contract range, Open Cinema range, platform,
architecture, Python/runtime requirements, and capability versions with the running appliance.
An incompatible plugin SHALL remain inspectable but SHALL NOT be enabled.

#### Scenario: Contract range is incompatible
- **WHEN** an installed plugin does not support the running plugin-contract version
- **THEN** it is marked incompatible with the compared versions and none of its runtime capabilities are activated

#### Scenario: Upgrade makes a plugin incompatible
- **WHEN** Open Cinema starts after an upgrade and a previously enabled plugin no longer satisfies compatibility checks
- **THEN** the plugin is isolated, its saved configuration is preserved, and the administrator receives a remediation diagnostic

### Requirement: A first-party catalogue is available without a remote marketplace
The system SHALL expose a maintained first-party catalogue with pinned source or release metadata,
available versions, compatibility, installation state, and update state. Catalogue presentation
SHALL distinguish catalogue metadata from the manifest verified from the downloaded artifact.

#### Scenario: First-party plugin is available
- **WHEN** an administrator opens the Plugins page
- **THEN** the hard-coded catalogue lists the plugin, its verified publisher status, compatible version, capabilities, and whether it is installed or updateable

#### Scenario: Downloaded manifest does not match catalogue identity
- **WHEN** a catalogue artifact declares a different identity or version from its catalogue record
- **THEN** installation stops before activation and reports the mismatch

### Requirement: Administrators can install a plugin from a Git source
An authenticated staff administrator SHALL be able to submit a supported Git repository URL and
an optional immutable revision. The system SHALL display the resolved repository and revision,
validate the plugin contract, and require explicit acknowledgement that third-party plugin code is
trusted code executed with Open Cinema's service privileges.

#### Scenario: Pinned Git plugin is accepted
- **WHEN** an administrator confirms a compatible Git plugin at a resolved commit
- **THEN** the system creates a tracked installation operation tied to that URL and commit

#### Scenario: Moving Git revision is selected
- **WHEN** an administrator selects a branch or other mutable revision
- **THEN** the UI identifies it as non-reproducible, records the resolved commit, and requires an additional confirmation before installation

#### Scenario: Non-administrator submits an installation
- **WHEN** an authenticated user without staff administration privileges attempts to install a plugin
- **THEN** the request is rejected before any repository is fetched or package code is executed

### Requirement: Installation and update are staged and recoverable
Plugin installation and update SHALL run as serialized, persistent operations with explicit stages
for acquisition, provenance capture, build, manifest validation, dependency resolution, contract
validation, staging, activation, health verification, and cleanup. Failure SHALL leave the previous
active plugin generation usable and SHALL expose a bounded diagnostic rather than a partial install.

#### Scenario: Dependency resolution fails
- **WHEN** a candidate plugin cannot be resolved with the Open Cinema runtime and enabled plugins
- **THEN** the operation fails before activation, the active generation is unchanged, and the conflicting requirements are reported

#### Scenario: Service restart occurs during activation
- **WHEN** activation requires an Open Cinema restart
- **THEN** the persisted operation resumes after startup and reaches healthy, failed, or rollback state without duplicate installation

#### Scenario: New generation fails health verification
- **WHEN** the services restart with a staged plugin but its required capabilities do not become healthy
- **THEN** the system restores the prior generation or enters an explicit safe recovery state and reports the failed verification

### Requirement: Plugin desired state is distinct from observed runtime state
The system SHALL persist whether an installed plugin is enabled independently from discovery and
health. Disabled, incompatible, failed, restart-pending, and healthy plugins SHALL remain visible
with their configuration, provenance, installed version, desired state, observed state, and last
diagnostic.

#### Scenario: Plugin is disabled
- **WHEN** an administrator disables a healthy plugin
- **THEN** its saved configuration and installation remain, its contributed runtime behavior is unavailable, and its state explains whether deactivation is complete or awaiting restart

#### Scenario: Plugin import fails
- **WHEN** installed plugin code raises during startup discovery
- **THEN** the plugin remains in inventory as failed while unrelated plugins and core observation continue operating

### Requirement: Lifecycle impact is explicit per operation
The plugin contract and operation API SHALL classify install, enable, disable, update, and uninstall
effects as hot, Open Cinema application restart, or host reboot. The system SHALL select at least
the minimum impact required by both the operation and host integration and SHALL never present a
lower-impact action as sufficient.

#### Scenario: Loaded plugin supports hot enable
- **WHEN** an installed disabled plugin declares and passes safe hot activation
- **THEN** enable starts its capabilities without restarting Open Cinema and records fresh health

#### Scenario: Newly installed Python entry point requires restart
- **WHEN** a plugin introduces runtime code that is not loaded in the current application process
- **THEN** installation reports that an Open Cinema application restart is required before enablement can complete

#### Scenario: Plugin requires host reboot
- **WHEN** an allowlisted first-party installation changes host integration that cannot become active through a service restart
- **THEN** the operation remains restart-pending until an administrator confirms the separately advertised host reboot action

### Requirement: Configuration and secrets use core-managed contracts
Plugins SHALL declare versioned configuration schemas, defaults, validation rules, and migrations.
Core APIs SHALL store ordinary configuration in a namespaced form and SHALL store declared secrets
through a write-only secret facility that never returns their plaintext value to plugin catalogue
or administration clients.

#### Scenario: Secret is configured
- **WHEN** an administrator submits a valid access token field declared as secret
- **THEN** later reads report that a value exists without returning the token and audit output remains redacted

#### Scenario: Configuration migration is unavailable
- **WHEN** an installed update cannot migrate a saved configuration version
- **THEN** the update is blocked before activation and the original configuration remains usable with the prior plugin version

### Requirement: Update and removal preserve an explicit recovery boundary
The system SHALL show the target version, source, compatibility, lifecycle impact, configuration
effect, and rollback availability before update or removal. Disable SHALL retain plugin data.
Uninstall SHALL require separate confirmation for retaining or deleting plugin-owned data and SHALL
not silently delete desired graphs that reference a removed capability.

#### Scenario: Referenced plugin is uninstalled
- **WHEN** an administrator confirms uninstall while a saved graph references one of its capabilities
- **THEN** the graph is preserved with an unavailable-plugin diagnostic and the UI identifies the references before completing removal

#### Scenario: Plugin is reinstalled after retained-data removal
- **WHEN** a compatible version with the same identity is installed after its data was retained
- **THEN** the system validates the retained configuration version before offering reactivation

### Requirement: Plugins cannot silently acquire core or privileged ownership
The contract SHALL reserve authentication, authorization, plugin installation, privileged host
control, WirePlumber session observation, endpoint inventory, and final graph reconciliation to
core services. Requested plugin permissions SHALL be disclosed, but the UI SHALL NOT claim that
in-process third-party Python code is sandboxed.

#### Scenario: Plugin requests a prohibited core capability
- **WHEN** a plugin declares replacement device discovery, audio-backend selection, or arbitrary host command execution
- **THEN** that capability is rejected with a prohibited-capability diagnostic

#### Scenario: Git plugin requests host integration
- **WHEN** an unverified Git plugin declares a privileged host installation or command capability
- **THEN** the privileged capability is unavailable even if the administrator installs the ordinary plugin code

### Requirement: Plugin APIs are authenticated, namespaced, and failure-isolated
Plugin routes and actions SHALL be mounted under a stable plugin namespace, SHALL inherit core
authentication and request-protection policy, and SHALL be unavailable while the plugin is
disabled. A plugin route, lifecycle hook, health check, or catalogue failure SHALL not prevent
unrelated plugins or core administration APIs from operating.

#### Scenario: Disabled plugin route is requested
- **WHEN** a client calls a namespaced route belonging to a disabled plugin
- **THEN** the server returns an explicit plugin-disabled response without invoking plugin code

#### Scenario: Plugin health hook times out
- **WHEN** one plugin does not answer within its declared bounded health interval
- **THEN** that plugin becomes degraded or failed while the catalogue and unrelated plugin actions remain responsive

### Requirement: The public plugin contract is documented and testable
Open Cinema SHALL publish author documentation and reusable contract tests covering package
layout, manifest fields, capability schemas, UI contributions, lifecycle semantics, configuration
migrations, security boundaries, compatibility, CI expectations, and release metadata.

#### Scenario: Plugin author validates a package
- **WHEN** a plugin repository runs the supported contract-validation suite in CI
- **THEN** malformed manifests, incompatible schema contributions, namespace violations, and unsupported lifecycle declarations fail before release

