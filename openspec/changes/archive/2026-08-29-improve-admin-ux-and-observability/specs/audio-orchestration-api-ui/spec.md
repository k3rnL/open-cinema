## MODIFIED Requirements

### Requirement: The existing management experience is evolved in place
The management console SHALL preserve its application shell, dashboard direction, navigation, direct-manipulation graph editor, node presentation, validation feedback, error feedback, and explicit Apply interaction while adapting those workflows to the orchestration APIs and automatic draft persistence.

#### Scenario: Existing user returns to graph management
- **WHEN** the revised management console is opened
- **THEN** the user can use the established graphical workflow and visual structure rather than a replacement raw-document or diagnostics-only editor

#### Scenario: Dashboard hosts appliance management
- **WHEN** the user opens the dashboard
- **THEN** appliance information, current audio state, volume, health, and system controls extend the existing management shell without changing the role of `apps/admin`

### Requirement: Existing look and feel is the visual baseline
The management console SHALL preserve the established graph-editor and application look and feel. New UI SHALL use the existing component library, theme, layout primitives, and design tokens first; a custom component or narrowly scoped graph integration style MAY be used only when the component library cannot provide the required visualization or stable interaction, and it SHALL derive colors and spacing from the active theme.

#### Scenario: UI implementation begins
- **WHEN** implementation of the revised management experience starts
- **THEN** the current application and saved reference views are visually inspected before components are changed

#### Scenario: New dashboard and graph controls are rendered
- **WHEN** the new controls are displayed in light or dark mode
- **THEN** they follow the existing visual language, theme, spacing, responsive behavior, focus treatment, and action hierarchy

#### Scenario: Visual acceptance is reviewed
- **WHEN** revised management workflows are ready for acceptance
- **THEN** reference and revised views are compared at representative viewport sizes and any custom styling is limited to documented graph or chart integration needs

### Requirement: Save and Apply have separate effects
The graph editor SHALL automatically persist editable draft changes without changing live audio and SHALL retain an explicit Apply action that flushes pending saves, validates, publishes, and activates the draft as one user-directed workflow.

#### Scenario: User makes an incomplete edit
- **WHEN** the user changes graph content or layout
- **THEN** the latest document is automatically persisted as a draft after a bounded delay
- **AND** the published revision, active revision, resolved plan, and live audio remain unchanged

#### Scenario: Apply a valid draft
- **WHEN** a user selects Apply for a valid draft with saved or pending changes
- **THEN** the UI first persists the latest local document, obtains canonical backend validation, publishes an immutable revision, activates it atomically, and displays reconciliation progress to convergence

#### Scenario: Apply an invalid draft
- **WHEN** canonical validation rejects the draft
- **THEN** the draft remains saved and editable, the prior active revision remains unchanged, and node, edge, field, and graph errors are displayed in context

#### Scenario: Activation fails after publication
- **WHEN** publication succeeds but activation or reconciliation cannot safely complete
- **THEN** the UI distinguishes the published revision from the still-applied revision and displays the failed phase, reason, and safe runtime state

### Requirement: Advanced graph editing preserves direct manipulation
The advanced management UI SHALL support graphical typed-node creation, compatible-port connections, node movement, selectors, routing/control nodes, mixers, fan-out, adaptive branches, processors, subgraphs, and validation diagnostics. Selecting a node SHALL expose its editable configuration in a stable page-level inspector without resizing the graph node or subjecting form controls to canvas zoom.

#### Scenario: Connect incompatible ports
- **WHEN** a user attempts an invalid edge in the graph editor
- **THEN** the UI prevents or marks the edge and displays the backend-provided compatibility reason

#### Scenario: Edit processor configuration
- **WHEN** a user selects a processor node
- **THEN** its schema fields and validation feedback are available in the graph workflow through a stable inspector while the compact node and its ports remain in place

#### Scenario: Open a field menu while zoomed out
- **WHEN** the graph canvas is zoomed to a small scale and the user opens a selection control in the inspector or graph toolbar
- **THEN** the menu is rendered at readable viewport scale, fits its content up to a maximum width and height, and scrolls rather than overflowing

### Requirement: Device discovery remains a dedicated management workflow
The management console SHALL provide a Devices workflow focused on observed devices and durable logical endpoints, including availability, capabilities, last-seen state, matching evidence, ambiguity, route state, binding actions, and capability-aware device controls. Managed processors and supervised software resources SHALL appear in a separate Managed resources workflow.

#### Scenario: Previously configured device is disconnected
- **WHEN** a logical endpoint has no current runtime candidate
- **THEN** the inventory still shows it as unavailable with its last-known details and graphs that reference it remain intact

#### Scenario: User binds a discovered device
- **WHEN** a user chooses an observed candidate for a logical endpoint
- **THEN** the UI previews the stable selector evidence and saves the approved binding without persisting transient PipeWire IDs as durable identity

#### Scenario: Managed processor appears in PipeWire
- **WHEN** a CamillaDSP or decoder process exposes PipeWire-facing nodes
- **THEN** Devices does not offer them as physical device identities and Managed resources shows their correlated lifecycle, health, version, mode, and advertised controls

### Requirement: Resolution explanations are visible
The UI SHALL first explain active routing in user-facing names and plain language, including the source-to-output path, selection reason, rejected or unavailable alternatives, signal-format and channel decisions, processor choices, manual overrides, transition progress, and actionable errors. Correlation identifiers, runtime keys, stage documents, and raw JSON SHALL remain available only as secondary collapsed technical details.

#### Scenario: Automatic output switch
- **WHEN** the system switches from speakers to a headset
- **THEN** the primary explanation identifies the triggering device event, why the headset won, the source and processor chain, produced signal format, selected output, and final runtime status

#### Scenario: Preferred output is unavailable
- **WHEN** a preferred output cannot be selected and a fallback is used
- **THEN** the explanation names both outputs and states the human-readable availability or compatibility reason before offering technical evidence

#### Scenario: No resolved plan exists
- **WHEN** the graph is inactive or cannot resolve
- **THEN** the explanation presents a concise inactive, waiting, or failed state and an actionable next step rather than an empty raw document

### Requirement: Manual controls are explicit operational state or overrides
Volume and mute controls SHALL identify their persistent master or endpoint scope, while endpoint selection, scene selection, temporary route changes, and graph-parameter changes SHALL indicate whether they modify persistent intent or create an expiring manual override.

#### Scenario: User changes master volume
- **WHEN** a user changes master volume
- **THEN** the UI identifies it as persistent appliance audio state and does not imply that the graph revision was edited

#### Scenario: Temporary headset selection
- **WHEN** a user chooses “use headset for one hour”
- **THEN** the UI displays the override and its expiry and provides a way to cancel it

## ADDED Requirements

### Requirement: Primary controls remain spatially stable
Loading, success, warning, progress, validation, and error feedback SHALL use reserved regions, overlays, skeletons, fixed card sections, or in-control state so its appearance does not unexpectedly move the primary controls the user is operating. Dynamic content SHALL remain accessible to assistive technology.

#### Scenario: An asynchronous action changes state
- **WHEN** a request begins, succeeds, fails, or reconnects
- **THEN** the triggering control retains its position and dimensions while status is announced in a predictable region

#### Scenario: Page performs initial loading
- **WHEN** a management page loads data
- **THEN** the application shell remains mounted and the page shows a shape-preserving skeleton or section loading state instead of replacing the entire viewport with a transient layout

### Requirement: Live updates are efficient and recoverable
The API SHALL provide event-driven updates or a versioned incremental mechanism with full-snapshot recovery, and the UI SHALL recover from missed events or reconnects. A fresh subscription without a resume cursor SHALL start from one current authoritative snapshot and SHALL NOT replay retained historical events before following new events.

#### Scenario: Fresh management page subscribes
- **WHEN** a dashboard or graph page opens without a prior event cursor
- **THEN** it receives one current snapshot and then new events without processing the retained transition history

#### Scenario: Browser reconnects
- **WHEN** a browser loses and restores its event connection with a known cursor
- **THEN** it obtains changes since that cursor or replaces local state with a fresh consistent snapshot after a retention gap

### Requirement: Graph activation has one stateful primary action
For each top-level graph, the management UI SHALL present exactly one context-appropriate primary action. The graph list and a published-revision view SHALL show Apply when that revision is inactive or Deactivate when it is active. An editable draft SHALL show Apply changes, whether it will replace an active revision or activate an inactive graph, and SHALL not place Deactivate beside it. Subgraphs and graphs without an eligible revision SHALL not show an executable live-state action.

#### Scenario: Active graph is listed
- **WHEN** a graph has an active revision
- **THEN** its action column and editor show Deactivate and do not simultaneously show Apply

#### Scenario: Inactive published graph is listed
- **WHEN** a top-level graph is inactive and has a published revision
- **THEN** its action column and editor show Apply and do not show Deactivate

#### Scenario: Draft exists for an active graph
- **WHEN** the editor is displaying an editable draft while another revision is active
- **THEN** the editor shows Apply changes as the single primary lifecycle action and leaves deactivation available from the active published context rather than beside Apply changes

#### Scenario: User opens a graph row
- **WHEN** the user activates a non-action area of a graph table row
- **THEN** the editor opens, while buttons and menus in that row execute their own action without also navigating

### Requirement: Common graph values use structured editors
The management UI SHALL generate understandable controls for booleans, numbers, strings, enumerations, bounded arrays, key-value maps, selector predicates, parameter declarations, public ports, and subgraph bindings. Raw JSON SHALL be an explicitly labelled advanced fallback only when the schema is absent, recursive, or too unstructured for a safe generated form.

#### Scenario: User edits a supported-codec list
- **WHEN** a node schema declares an array of codec strings or enumerated values
- **THEN** the inspector offers repeatable or multi-select controls with validation instead of opening a JSON text editor

#### Scenario: User edits endpoint selection priority
- **WHEN** an endpoint selector node contains an ordered list of device candidates
- **THEN** the inspector offers device, priority, eligibility, and ordering controls without exposing the candidate list as raw JSON
- **AND** the node card exposes only graph ports that the resolver and live applier support

#### Scenario: User edits a condition
- **WHEN** a node uses a supported condition operator over device, signal, processor, or graph facts
- **THEN** the inspector names the operation in user language and provides structured fact, typed value, nested-rule, and duration controls instead of exposing an `op` text field or condition JSON

#### Scenario: User configures a catalogue node with alternative or nested values
- **WHEN** the user selects an endpoint reference, signal adapter, CamillaDSP profile selector, dynamic device group, or pinned subgraph instance
- **THEN** the inspector shows only the active alternative and dedicated controls for its meaningful values
- **AND** inactive schema alternatives and duplicate raw subgraph documents are not presented as ordinary editable fields

#### Scenario: User asks what a node does
- **WHEN** the user hovers or focuses a node's information control
- **THEN** a concise catalogue description appears without resizing the node or moving the graph
- **AND** the information control has an accessible name

#### Scenario: Unknown plugin schema is encountered
- **WHEN** a plugin provides valid data that the structured editor cannot represent safely
- **THEN** the value remains preserved and an Advanced JSON editor is available with parse and schema validation before commit

### Requirement: Managed resources have a dedicated workflow
The management navigation SHALL contain a Managed resources destination that groups supervised adapters and processing resources by user-facing type and displays lifecycle, health, active configuration or mode, version, last observation, and only server-advertised actions.

#### Scenario: User needs to restart a ROC adapter
- **WHEN** a managed adapter advertises restart
- **THEN** the user can confirm Restart from Managed resources and observe requested, restarting, healthy, or failed state without returning to Devices
