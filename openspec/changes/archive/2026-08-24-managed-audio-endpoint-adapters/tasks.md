## 1. Persistent adapter contracts

- [x] 1.1 Add the configured adapter-media root and lifecycle timing settings with safe local defaults.
- [x] 1.2 Add desired adapter and separate observed runtime-state models, owner filtering, constraints, and a migration with no legacy-data compatibility work.
- [x] 1.3 Implement the adapter-type registry and versioned catalogue documents for ROC receiver, ROC sender, debug WAV source, and debug WAV recorder.
- [x] 1.4 Implement per-type configuration normalization and field-level validation, including ROC addresses/ports and constrained media paths.
- [x] 1.5 Add model, registry, configuration, and malicious-path test coverage.

## 2. Runtime drivers

- [x] 2.1 Implement stable PipeWire node-name/property generation and shell-free process argument builders shared by all adapter drivers.
- [x] 2.2 Implement supervised ROC receiver and sender processes using the installed PipeWire ROC modules.
- [x] 2.3 Implement PCM WAV inspection and bounded looping frame delivery to one persistent unconnected PipeWire source.
- [x] 2.4 Implement an unconnected PipeWire recording sink with collision policy, graceful file finalization, and progress observation.
- [x] 2.5 Implement common start, poll, and bounded graceful-stop behavior with captured failure diagnostics and no orphaned children.
- [x] 2.6 Add unit tests for exact driver arguments, stable metadata, looping, recorder finalization, process failures, and stop escalation.

## 3. Orchestrator reconciliation

- [x] 3.1 Implement an adapter supervisor that deterministically diffs enabled desired definitions against owned runtimes and applies create, restart, stop, and retry transitions idempotently.
- [x] 3.2 Persist desired and observed lifecycle separately, including generation, PID, expected node, runtime correlation, progress, retry time, and last error.
- [x] 3.3 Correlate adapter nodes from detached WirePlumber world snapshots using stable properties and require node observation before reporting ready.
- [x] 3.4 Integrate supervisor polling and guaranteed child cleanup into the active-controller lifecycle without launching processes from web requests.
- [x] 3.5 Add supervisor and orchestrator tests for initial start, configuration change, explicit restart, disable, crash/backoff, node appearance, controller shutdown, and duplicate prevention.

## 4. Versioned adapter API

- [x] 4.1 Add desired/observed representations and adapter-type catalogue responses to the versioned API contract.
- [x] 4.2 Add authenticated owner-filtered adapter list, create, detail, update, and disabled-only delete endpoints with canonical validation.
- [x] 4.3 Add explicit restart semantics and optimistic-concurrency enforcement for every adapter mutation.
- [x] 4.4 Publish desired-state wake-ups and auditable lifecycle intent without waiting synchronously for runtime mutation.
- [x] 4.5 Add API tests for CRUD, schema discovery, desired/observed separation, permissions, concurrency, restart, safe delete, validation problems, and CSRF-authenticated writes.

## 5. Inventory integration

- [x] 5.1 Project stable adapter ownership and correlation metadata into endpoint candidates without excluding them as processors.
- [x] 5.2 Expose managed-adapter origin, adapter identity, kind, local readiness, and runtime linkage in device discovery diagnostics.
- [x] 5.3 Add inventory tests proving adapters are bindable logical input/output candidates and remain distinct from hardware and processor resources.

## 6. Shared client and management UI

- [x] 6.1 Add versioned adapter type, definition, desired state, observed state, configuration, and API client contracts to the shared UI package.
- [x] 6.2 Add an “Endpoint adapters” resource and management route to `apps/admin` using the existing application shell and component library.
- [x] 6.3 Implement schema-driven create/edit forms for all four built-in types, including type help, safe defaults, field diagnostics, and unsaved-change handling.
- [x] 6.4 Implement list/detail status, enable/disable, restart, disabled-only delete, retry/error diagnostics, recording progress, and device-discovery linkage.
- [x] 6.5 Add UI contract, behavior, accessibility, and no-new-custom-CSS regression tests.

## 7. Local integration and acceptance

- [x] 7.1 Apply migrations and verify one ROC receiver, one ROC sender, one looping WAV source, and one WAV recorder locally without replacing the currently active manual ROC route.
- [x] 7.2 Verify adapter endpoints can be bound and routed by a desired graph, looping preserves endpoint identity, recording finalizes a playable WAV, and disabling removes each endpoint.
- [x] 7.3 Run the full backend suite, UI tests/type-check/lint/build, and strict OpenSpec validation.
- [x] 7.4 Visually inspect the management workflow at representative desktop widths and confirm it preserves the established look and feel without new custom CSS.
- [x] 7.5 Obtain explicit user acceptance of the endpoint-adapter menu and local ROC/debug-file workflows before archiving the change.

## 8. Graph deactivation

- [x] 8.1 Add a durable enabled/disabled activation state, monotonic compare-and-swap deactivation service, versioned API operation, representations, schema contract, and migration.
- [x] 8.2 Reconcile disabled graphs through journaled graph-scoped managed-link cleanup and leave their applied state idle with no current plan.
- [x] 8.3 Add Deactivate controls with confirmation and progress/error feedback to the existing graph list and editor without custom CSS.
- [x] 8.4 Add service, API, desired-state monitor, live-reconciliation, shared-client, and UI tests; run backend/UI checks and strict OpenSpec validation.
- [x] 8.5 Restore Apply in the graph-list action column and for published revisions opened in the editor, keeping draft creation/publication independent; add UI tests and rerun UI/OpenSpec checks.
