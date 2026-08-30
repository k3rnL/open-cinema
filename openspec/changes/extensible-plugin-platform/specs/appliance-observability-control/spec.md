## ADDED Requirements

### Requirement: Plugin lifecycle operations use guarded control semantics
Plugin install, enable, disable, update, uninstall, service-restart, and host-reboot transitions
SHALL be available only to authenticated staff administrators, SHALL use persistent operation
identifiers and concurrency protection, and SHALL invoke only structured, allowlisted privileged
helpers. Plugin-supplied strings SHALL NOT become arbitrary service names or shell commands.

#### Scenario: Plugin update requires an application restart
- **WHEN** an administrator confirms an update using current plugin action state
- **THEN** the server accepts one serialized operation, performs only the allowlisted restart transition, and lets the UI follow it through reconnect and fresh plugin health

#### Scenario: Git plugin declares a privileged command
- **WHEN** a third-party manifest requests an unrecognized host command or service operation
- **THEN** the server refuses that privileged capability and does not forward plugin-controlled text to the host control helper

#### Scenario: Concurrent lifecycle request is submitted
- **WHEN** another plugin environment mutation is already active or the submitted concurrency token is stale
- **THEN** the server rejects or queues the request according to advertised state without executing overlapping environment changes

## MODIFIED Requirements

### Requirement: Managed resource actions are capability advertised
Every core or plugin-managed resource representation SHALL distinguish observation from available
control actions. An action SHALL be rendered as executable only when the server advertises an
authenticated action identifier, current availability, lifecycle impact, and any required
concurrency token; otherwise the resource remains readable with a reason that control is
unavailable. Plugin resource actions SHALL be namespaced and SHALL disappear when their owning
plugin is disabled without removing the observed historical state.

#### Scenario: Managed adapter supports restart
- **WHEN** a running managed adapter advertises a restart action
- **THEN** the Managed resources page offers Restart and reports progress until a newer healthy observation is received

#### Scenario: Processor is observation-only
- **WHEN** a processor projection has health information but no restart action
- **THEN** the Managed resources page shows its state without a non-functional Restart button

#### Scenario: Plugin-managed source supports restart
- **WHEN** an enabled plugin's long-lived audio source advertises a restart action
- **THEN** the Managed resources page offers the namespaced action and follows its operation without treating the plugin-controlled identifier as a host service name

#### Scenario: Owning plugin is disabled
- **WHEN** a previously observed plugin resource belongs to a disabled plugin
- **THEN** the resource remains readable as inactive or unavailable and no stale action is executable

