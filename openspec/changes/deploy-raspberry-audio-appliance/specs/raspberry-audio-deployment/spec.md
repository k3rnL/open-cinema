## Purpose

Defines reproducible deployment, verification, and coordinated recovery of the current native-PipeWire Open Cinema Raspberry Pi appliance.

## ADDED Requirements

### Requirement: The supported appliance target is explicit and enforced
The deployment SHALL support the currently validated Raspberry Pi 5 8 GB fixture and the exact operating-system and runtime family recorded in its coordinated manifest until a separate hardware benchmark change qualifies another target.

#### Scenario: Deployment targets the validated appliance
- **WHEN** preflight inspects the current Raspberry Pi 5 8 GB fixture
- **THEN** it verifies the recorded architecture, operating-system, runtime, power, cooling, storage, memory, and service-identity prerequisites before installation

#### Scenario: Deployment targets another host
- **WHEN** a host does not match the recorded appliance target
- **THEN** preflight stops before migration or live audio mutation and reports the unsupported facts

### Requirement: Ansible installs one coherent native audio runtime
The deployment SHALL install compatible versions of PipeWire, WirePlumber, WyrePlumber, Open Cinema, the management UI, CamillaDSP, the decoder, required state services, and the appliance web proxy as one coordinated stack on the provisioned supported appliance.

#### Scenario: Appliance-mode installation runs
- **WHEN** the supported playbook runs against the provisioned appliance
- **THEN** all declared packages, application artifacts, configuration, migrations, and services are installed from the selected coordinated manifest

### Requirement: Appliance inputs are immutable and version correlated
Appliance mode SHALL consume release artifacts, commit-addressed artifacts, or equivalently immutable inputs and SHALL record the compatibility identity and provenance of every installed application and processor.

#### Scenario: Development uses local source trees
- **WHEN** an operator explicitly selects development mode
- **THEN** local source dependencies may be used and the resulting installation is identified as mutable and non-release

#### Scenario: Appliance mode receives a mutable dependency
- **WHEN** appliance-mode preflight finds a local-directory, editable, or otherwise unpinned production dependency
- **THEN** it rejects the installation and identifies every mutable input

#### Scenario: Installed contracts are incompatible
- **WHEN** binding, processor protocol, backend API, UI schema, or manifest identities do not satisfy the coordinated compatibility contract
- **THEN** deployment stops before live reconciliation is enabled and reports every incompatible component

### Requirement: Headless service identity is consistent
PipeWire, WirePlumber, Open Cinema, and managed processors SHALL run with documented users, groups, runtime directories, D-Bus access, audio permissions, socket ownership, and service ordering suitable for a headless appliance.

#### Scenario: The appliance boots without a graphical login
- **WHEN** the Raspberry Pi enters multi-user operation
- **THEN** Bluetooth and local audio devices become visible to the same PipeWire and WirePlumber session used by Open Cinema and its processors

#### Scenario: A managed processor creates resources
- **WHEN** CamillaDSP or a decoder instance starts
- **THEN** only the intended service identities can access its control, status, configuration, and audio resources

### Requirement: Static deployment configuration and dynamic user intent remain separate
Deployment SHALL manage packages, identities, services, base PipeWire and WirePlumber policy, environment defaults, readiness, and recovery, while graph definitions, endpoint bindings, processor profiles, parameters, rules, scenes, active revisions, and overrides remain dynamic Open Cinema data.

#### Scenario: A user applies a graph
- **WHEN** the user changes and applies desired audio behavior in the management console
- **THEN** Open Cinema and WirePlumber enact it without rerunning Ansible or rewriting deployment-managed configuration

#### Scenario: The playbook is rerun
- **WHEN** Ansible reconciles static appliance configuration
- **THEN** it does not create, replace, or delete dynamic user intent

### Requirement: WirePlumber overlays preserve distribution ownership
Deployment SHALL use identifiable configuration fragments, profiles, settings, and service overrides and SHALL NOT replace distribution-owned PipeWire or WirePlumber configuration wholesale.

#### Scenario: Static audio policy is reconciled
- **WHEN** the playbook installs or removes an Open Cinema audio-policy overlay
- **THEN** the overlay has explicit ownership and removal behavior and distribution-owned files remain intact

### Requirement: Bluetooth audio roles are configured explicitly
Deployment SHALL configure and validate the BlueZ and WirePlumber roles required for the accepted programme-source and headset-output scenarios.

#### Scenario: A phone provides programme audio
- **WHEN** the configured phone connects using the accepted source role
- **THEN** WirePlumber exposes the expected objects and Open Cinema can match them to the intended logical programme-source endpoint

#### Scenario: A headset becomes available
- **WHEN** the configured headset connects using the accepted output role
- **THEN** it becomes eligible for the configured output rule and audio can move to it and return to the main output after disconnection

### Requirement: Managed processors expose stable native resources
Deployment SHALL start CamillaDSP and decoder instances with native PipeWire I/O, stable Open Cinema identities, correlated runtime properties, bounded resources, and service-management adapters compatible with the accepted processor contracts.

#### Scenario: A processor instance starts
- **WHEN** CamillaDSP or the decoder becomes ready
- **THEN** its native PipeWire resources can be correlated to the intended managed instance without appearing as physical endpoint candidates

#### Scenario: A processor or audio session restarts
- **WHEN** runtime identifiers change after restart
- **THEN** Open Cinema rematches the owned processor resources and restores the accepted route without changing physical endpoint bindings

### Requirement: Services expose correlated health and readiness
Deployment SHALL verify the audio-session socket, WirePlumber discovery and control contract, Open Cinema runtime, database and state services where enabled, managed processors, API, management UI, and reverse proxy before declaring the appliance ready.

#### Scenario: A readiness probe fails
- **WHEN** any required component cannot satisfy its readiness contract
- **THEN** the playbook fails with correlated component identities, failed checks, and relevant diagnostics instead of reporting partial success

#### Scenario: Audio is unhealthy while the web service is reachable
- **WHEN** management services can respond but live audio control is unsafe
- **THEN** diagnostics remain accessible and unsafe mutation is disabled with a visible reason

### Requirement: The management console has a secure native entry
The management console SHALL use Django-session authentication and CSRF protection, SHALL keep privileged diagnostics authorized and redacted, and SHALL limit network exposure to the configured appliance boundary.

#### Scenario: An anonymous user opens the management console
- **WHEN** an unauthenticated browser opens a protected management route
- **THEN** the application presents its username and password login page without exposing protected content

#### Scenario: The private development appliance is bootstrapped
- **WHEN** the explicitly enabled temporary-administrator task runs
- **THEN** it idempotently provisions the configured development account and that account can authenticate through the appliance proxy

#### Scenario: The appliance leaves the controlled development network
- **WHEN** deployment is configured for broader exposure
- **THEN** the temporary credential is rejected until it is replaced or disabled through the protected secret mechanism

### Requirement: Service startup and recovery are ordered
Managed services SHALL declare dependencies, readiness gates, bounded timeouts, restart policies, and graceful shutdown behavior that prevent unsafe reconciliation and orphaned processor resources.

#### Scenario: The audio session restarts
- **WHEN** PipeWire and WirePlumber restart after an error
- **THEN** Open Cinema pauses unsafe mutation, reconnects, obtains a fresh snapshot, and restores managed intent only after readiness

#### Scenario: The appliance reboots with active intent
- **WHEN** the host reboots with an active graph
- **THEN** services start in a safe order and converge on the persisted active revision without a graphical login or manual Apply

#### Scenario: A transition is interrupted
- **WHEN** a service or the host stops during an unfinished transition
- **THEN** recovery obtains fresh runtime state, cleans only owned stale resources, and returns to a safe convergent state

### Requirement: Reconciliation of the provisioned appliance is idempotent
Repeated deployment of the same coordinated manifest SHALL leave packages, identities, managed configuration, runtime directories, services, migrations, and generated processor configuration unchanged except for explicitly transient verification output.

#### Scenario: The playbook is rerun without input changes
- **WHEN** Ansible runs again against the already configured appliance
- **THEN** it reports no unintended static or dynamic changes and readiness still passes

### Requirement: State is protected by a coordinated rollback boundary
Before a candidate coordinated transition, deployment SHALL capture the installed manifest, database, generated processor configuration, inventory inputs, and managed static configuration needed to restore the previous accepted state.

#### Scenario: Installation, migration, restart, or readiness fails
- **WHEN** the candidate transition cannot complete
- **THEN** deployment stops, retains correlated diagnostics and the prior restorable state, and does not record the candidate as successful

#### Scenario: A coordinated rollback is requested
- **WHEN** the operator selects the retained previous manifest
- **THEN** deployment restores compatible application, UI, binding, decoder, processor, configuration, and database identities as one boundary and verifies readiness

#### Scenario: Rollback evidence is closed
- **WHEN** rollback has been exercised on the current appliance
- **THEN** the retained artifacts, backups, irreversible boundaries, observed result, and recovery procedure are recorded explicitly
