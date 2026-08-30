## MODIFIED Requirements

### Requirement: Admin UI provides a simple accessible channel tester

The Refine admin application SHALL provide a `Speaker test` menu and page built from the existing Ant Design components without broad custom CSS. The page SHALL explain that other playback should be paused, allow selecting an eligible output, show one clearly labelled button per observed channel with expanded speaker names where known, visibly identify the active test, expose a Stop action, and present actionable loading, empty, stale-inventory, and failure states. The output selector, channel buttons, and Stop control SHALL retain their positions while test status or errors appear and disappear.

#### Scenario: User tests a connected speaker output

- **WHEN** the user selects an eight-channel output and presses `FC · Front center`
- **THEN** the UI starts the test, marks the front-center button as active, disables conflicting actions during the request, retains a visible Stop control, and updates status without moving the channel buttons

#### Scenario: Test reports an error

- **WHEN** a start or stop request fails
- **THEN** an actionable error is announced in a reserved status region and the selector and channel-button positions remain stable

#### Scenario: No testable output is connected

- **WHEN** the API returns no eligible outputs
- **THEN** the page explains that no physical PCM output with a known channel map is currently available and offers Refresh
