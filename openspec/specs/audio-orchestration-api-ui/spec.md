# Audio Orchestration API and UI Specification

## Purpose

Defines stable APIs and the end-user management experience for configuring desired audio behavior, inserting processors, discovering endpoints, and understanding resolved and runtime state without exposing unnecessary PipeWire mechanics.

## Requirements

### Requirement: APIs separate desired, resolved, applied, and runtime representations
The system SHALL expose distinct versioned resources for desired graph definitions, resolved plans and explanations, applied transition state, and observed runtime graph state.

#### Scenario: Fetch desired graph
- **WHEN** a client retrieves a desired graph
- **THEN** the response contains persistent nodes, parameters, subgraphs, selectors, processors, and rules without transient PipeWire identifiers as durable references

#### Scenario: Fetch runtime graph
- **WHEN** a client retrieves the live graph
- **THEN** the response contains current runtime identifiers and correlation metadata without implying that they are desired-state identifiers

### Requirement: The management and on-box applications retain distinct roles
The `apps/admin` web application SHALL remain the complete end-user management console, and `apps/ui` SHALL remain a separate placeholder for the future interface rendered on the physical home-cinema display during this change.

#### Scenario: User opens audio management
- **WHEN** a user opens the web management console
- **THEN** dashboard, device inventory, graph configuration, processors, validation, application status, and live-control workflows are available from `apps/admin`

#### Scenario: On-box UI is built
- **WHEN** the UI workspace is built during this change
- **THEN** `apps/ui` remains a minimal independent application and does not replace or duplicate the management console

### Requirement: The existing management experience is evolved in place
The management console SHALL preserve its application shell, dashboard direction, navigation, direct-manipulation graph editor, node presentation, validation feedback, error feedback, and explicit Save and Apply interaction while adapting those workflows to the orchestration APIs.

#### Scenario: Existing user returns to graph management
- **WHEN** the revised management console is opened
- **THEN** the user can use the established graphical workflow and visual structure rather than a replacement raw-document or diagnostics-only editor

#### Scenario: Dashboard is extended later
- **WHEN** additional appliance-management features such as system information, update, or reboot are added
- **THEN** the existing dashboard and management shell can host them without changing the role of `apps/admin`

### Requirement: Existing look and feel is the visual baseline
The management console SHALL preserve the established graph-editor and application look and feel, and SHALL implement new orchestration UI by composing the existing component library, theme, layout primitives, and graph styling without adding project-specific custom CSS rules or stylesheets.

#### Scenario: UI implementation begins
- **WHEN** implementation of the revised graph experience starts
- **THEN** the current application and graph editor are run and visually inspected as the reference before components are changed

#### Scenario: Processor UI is added
- **WHEN** new processor cards, fields, status, or palette controls are rendered
- **THEN** they use the same visual language, spacing, controls, theme behavior, and graph conventions as the reference editor

#### Scenario: Visual acceptance is reviewed
- **WHEN** the revised management workflows are ready for acceptance
- **THEN** reference and revised views are compared at representative viewport sizes and no new custom CSS is required to achieve the result

### Requirement: Graph and subgraph editing supports drafts and revisions
The API and UI SHALL support creating, saving, validating, comparing, publishing, activating, and discarding graph and subgraph drafts with optimistic concurrency.

#### Scenario: Concurrent edit conflict
- **WHEN** a client publishes against an outdated graph revision
- **THEN** the API rejects the write with current revision information and does not overwrite the newer draft

### Requirement: Save and Apply have separate effects
The graph editor SHALL provide an explicit Save action that persists only the editable draft and an explicit Apply action that saves, validates, publishes, and activates the draft as one user-directed workflow.

#### Scenario: Save an incomplete draft
- **WHEN** a user selects Save while editing a graph
- **THEN** the latest graph document and layout are persisted as a draft
- **AND** the published revision, active revision, resolved plan, and live audio remain unchanged

#### Scenario: Apply a valid draft
- **WHEN** a user selects Apply for a valid saved or unsaved draft
- **THEN** the UI saves it, obtains canonical backend validation, publishes an immutable revision, activates it atomically, and displays reconciliation progress to convergence

#### Scenario: Apply an invalid draft
- **WHEN** canonical validation rejects the draft
- **THEN** the draft remains saved and editable, the prior active revision remains unchanged, and node, edge, field, and graph errors are displayed in context

#### Scenario: Activation fails after publication
- **WHEN** publication succeeds but activation or reconciliation cannot safely complete
- **THEN** the UI distinguishes the published revision from the still-applied revision and displays the failed phase, reason, and safe runtime state

### Requirement: Processors are first-class insertable graph nodes
The advanced editor SHALL distinguish processors from input/output endpoints and SHALL allow built-in and plugin-provided processors to be inserted between compatible graph stages from a dedicated catalogue category.

#### Scenario: Insert CamillaDSP
- **WHEN** a user inserts CamillaDSP between a source path and an output path
- **THEN** the node exposes typed audio ports, profile and parameter configuration, signal constraints, resource assignment, lifecycle, health, and resolved/runtime state

#### Scenario: Insert the adaptive decoder
- **WHEN** a user inserts the adaptive decoder in an input path
- **THEN** the node exposes its decode/bypass policy, observed transport and codec, produced signal descriptor, lifecycle, and health without appearing as a discovered hardware endpoint

#### Scenario: Insert a plugin processor
- **WHEN** an installed processing plugin contributes a valid node schema
- **THEN** the same processor palette and schema-driven node UI can configure and connect it without plugin-specific editor code

### Requirement: Parameterized subgraphs are manageable
Users SHALL be able to define public ports and parameters, instantiate a subgraph, pin its version, override parameters, collapse or expand it, and preview upgrade compatibility.

#### Scenario: Expand nested processing
- **WHEN** a user expands a subgraph instance in the advanced editor
- **THEN** the UI shows its pinned internal definition and parameter bindings while preserving the parent graph context

### Requirement: Simple configuration is rule-oriented
The management console SHALL offer an optional view for expressing common behavior through readable conditions, actions, priorities, fallbacks, scenes, and manual preferences without requiring users to manipulate PipeWire ports.

#### Scenario: Configure headphone override
- **WHEN** a user creates “when headset is available, use it as primary output, otherwise use main speakers”
- **THEN** the UI stores equivalent desired-graph selection behavior and presents it in plain language

#### Scenario: Switch between simple and advanced views
- **WHEN** a supported rule is viewed in the graph editor
- **THEN** both views represent the same desired graph rather than maintaining competing configurations

### Requirement: Advanced graph editing preserves direct manipulation
The advanced management UI SHALL support graphical typed-node creation, compatible-port connections, node movement, inline configuration, selectors, routing/control nodes, mixers, fan-out, adaptive branches, processors, subgraphs, and validation diagnostics.

#### Scenario: Connect incompatible ports
- **WHEN** a user attempts an invalid edge in the graph editor
- **THEN** the UI prevents or marks the edge and displays the backend-provided compatibility reason

#### Scenario: Edit processor configuration
- **WHEN** a user selects or expands a processor node
- **THEN** its schema fields and validation feedback are available within the graph workflow without navigating to a competing audio pipeline system

### Requirement: Device discovery remains a dedicated management workflow
The management console SHALL provide an endpoint inventory that shows observed endpoints, known unavailable logical endpoints, capabilities, last-seen state, matching evidence, ambiguity, route state, and binding actions.

#### Scenario: Previously configured device is disconnected
- **WHEN** a logical endpoint has no current runtime candidate
- **THEN** the inventory still shows it as unavailable with its last-known details and graphs that reference it remain intact

#### Scenario: User binds a discovered device
- **WHEN** a user chooses an observed candidate for a logical endpoint
- **THEN** the UI previews the stable selector evidence and saves the approved binding without persisting transient PipeWire IDs as durable identity

#### Scenario: Managed processor appears in PipeWire
- **WHEN** a CamillaDSP or decoder process exposes PipeWire-facing nodes
- **THEN** the inventory identifies them as managed processor resources for diagnostics and does not offer them as physical device identities

### Requirement: Resolution explanations are visible
The UI SHALL show active selections, rejected alternatives, missing dependencies, signal-format decisions, processor profile choices, manual overrides, and reconciliation progress.

#### Scenario: Automatic output switch
- **WHEN** the system switches from speakers to a headset
- **THEN** the UI identifies the triggering endpoint event, winning rule, selected processing profile, and final runtime status

### Requirement: Live updates are efficient and recoverable
The API SHALL provide event-driven updates or a versioned incremental mechanism with full-snapshot recovery, and the UI SHALL recover from missed events or reconnects.

#### Scenario: Browser reconnects
- **WHEN** a browser loses and restores its event connection
- **THEN** it obtains changes since a known version or replaces local state with a fresh consistent snapshot

### Requirement: Manual controls are explicit overrides
Volume, mute, endpoint selection, scene selection, and temporary route changes SHALL indicate whether they modify persistent intent or create a scoped manual override.

#### Scenario: Temporary headset selection
- **WHEN** a user chooses “use headset for one hour”
- **THEN** the UI displays the override and its expiry and provides a way to cancel it

### Requirement: Shared client contracts do not collapse application roles
The shared UI package SHALL define and validate versioned orchestration DTOs that the management console consumes now and the independent on-box application may consume when its product requirements are defined.

#### Scenario: Server contract changes incompatibly
- **WHEN** the management console targets an unsupported API schema version
- **THEN** it displays a compatibility error rather than silently misinterpreting graph or edge data

### Requirement: Degraded operation remains understandable
The management console SHALL remain usable for desired-state editing and diagnostics when WirePlumber, CamillaDSP, the decoder, or reconciliation is unhealthy.

#### Scenario: WirePlumber unavailable
- **WHEN** runtime health is unavailable
- **THEN** users can still inspect and save desired-graph drafts while Apply and unsafe live controls clearly report why live changes are paused
