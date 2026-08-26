## 1. Backend contract and discovery

- [x] 1.1 Add speaker-test output/state representations and extract only current physical PCM sinks with validated observed channel order
- [x] 1.2 Add staff-only GET/POST/DELETE audio-v1 routes with stale runtime-key and invalid-channel errors
- [x] 1.3 Add API tests for discovery filtering, authorization, successful start/stop, replacement, and validation failures

## 2. Bounded PipeWire diagnostic runtime

- [x] 2.1 Implement the finite interleaved single-channel tone helper and exact `pw-cat` command construction
- [x] 2.2 Implement cross-worker locked state, PID start-time verification, replacement, stale cleanup, and bounded stop behavior
- [x] 2.3 Add unit tests for sample isolation, process command/environment, exclusivity, stale state, and safe signalling

## 3. Shared frontend contract and admin UI

- [x] 3.1 Add typed speaker-test DTOs and client methods to the shared UI package
- [x] 3.2 Add the Speaker test Refine resource, route, and Ant Design page with output selection, labelled channels, active state, Stop, Refresh, warnings, and errors
- [x] 3.3 Add frontend tests covering channel labels/interactions, empty state, request failures, and accessibility

## 4. Appliance integration and verification

- [x] 4.1 Give the Gunicorn service the owned PipeWire session environment and bounded `/run/open-cinema` write access, with deployment regression coverage
- [x] 4.2 Run backend, frontend, OpenSpec, and deployment validation suites
- [x] 4.3 Deploy backend and admin UI to the Raspberry Pi and verify the live sink/channel inventory without changing the active graph
- [x] 4.4 Exercise explicit stop, automatic expiry, and channel-by-channel output with the user, recording the observed amplifier mapping
