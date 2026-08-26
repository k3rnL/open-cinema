## Why

Physical multichannel amplifier wiring and channel documentation can disagree, while ordinary stereo or movie playback does not provide a deterministic way to identify every speaker. The management UI needs a simple, safe channel tester so the user can verify the physical output mapping before diagnosing decoder or DSP channel behavior.

## What Changes

- Add an authenticated management API that can start a short test signal on exactly one declared channel of an eligible physical audio output.
- Make each test bounded, non-overlapping, observable, and explicitly stoppable without editing or applying an audio graph.
- Add an admin UI menu that selects an output and exposes labelled channel buttons using the output's reported channel positions.
- Show current test state and actionable errors while preserving the established Refine/Ant Design look and responsive layout without custom CSS.
- Ensure test resources are temporary and cannot be mistaken for desired-graph-owned links or persisted audio adapters.

## Capabilities

### New Capabilities

- `speaker-channel-testing`: Authenticated discovery, safe per-channel signal generation, stop behavior, state reporting, and management UI interaction for physical speaker mapping tests.

### Modified Capabilities

None.

## Impact

- Open Cinema gains a small audio-v1 diagnostics API and a bounded runtime controller for temporary PipeWire test resources.
- The `open-cinema-ui` admin application gains a speaker-test route/menu using its existing Refine and Ant Design components.
- Backend and frontend contracts gain typed output/channel-test DTOs and focused tests.
- Raspberry Pi deployment uses the existing headless `opencinema` PipeWire session; no new daemon, CSS layer, or persistent schema is required.
