## 1. Contract Version 2 Foundation

- [x] 1.1 Define and version the static `open-cinema-plugin.toml`, capability, permission, lifecycle-impact, UI-contribution, and runtime-result schemas with strict validation and bounded field sizes.
- [x] 1.2 Replace the single-kind manifest records with one distribution manifest and typed API, automation, processing, managed-resource, managed-source, and admin-UI capability descriptors.
- [x] 1.3 Add the `open_cinema.plugins` entry-point loader, enforce static/runtime identity agreement, namespace ownership, compatibility ranges, and duplicate-capability rejection.
- [x] 1.4 Refactor registry state and catalogue documents to expose desired state, aggregate and per-capability health, provenance, lifecycle impact, diagnostics, and preserved schema metadata.
- [x] 1.5 Retain bounded lifecycle and processing hook contexts while preventing version-2 plugins from declaring core authentication, audio-backend, device-observation, reconciliation, or arbitrary host-command ownership.
- [x] 1.6 Add focused contract tests for valid composite plugins, malformed manifests, identity mismatch, incompatibility, duplicate capabilities, prohibited capabilities, import failure, and partial capability failure.

## 2. Plugin State, Configuration, and Secrets

- [x] 2.1 Add core migrations and repositories for plugin installations, manifest/provenance snapshots, desired and observed state, active generation, operations, diagnostics, configuration documents, repeatable instances, and secret references.
- [x] 2.2 Implement namespaced plugin document and instance APIs with ownership checks, schema validation, optimistic concurrency, stable identifiers, and bounded querying.
- [x] 2.3 Implement pure version-by-version plugin configuration migrations that validate before atomically replacing the active document and preserve the previous version on failure.
- [x] 2.4 Implement core-managed write-only secret create, replace, presence, resolve-for-owner, and delete semantics with redaction in serialization, diagnostics, operations, and logs.
- [x] 2.5 Implement explicit retained-data versus delete-data uninstall behavior and graph-reference discovery without deleting desired graph nodes.
- [x] 2.6 Add persistence tests covering disable/re-enable retention, incompatible upgrades, migration failure, concurrent writes, secret non-disclosure, uninstall retention, and reinstall validation.

## 3. Capability Integration and Version-1 Removal

- [x] 3.1 Add a core route wrapper that mounts plugin APIs under their namespace and enforces authentication, request protection, enabled state, capability health, timeout/error correlation, and disabled responses.
- [x] 3.2 Adapt automation registration to the common plugin identity, desired-state gate, namespaced IDs, and per-capability diagnostics.
- [x] 3.3 Migrate typed processing node registration, planning, drivers, configuration migration, unavailable-node preservation, and graph catalogue ownership to version 2.
- [x] 3.4 Add managed-resource provider contracts for observation, freshness, health, supported actions, concurrency tokens, and lifecycle-impact metadata.
- [x] 3.5 Add managed-audio-source contracts for repeatable instances, declared PCM/encoded signal shape, PipeWire correlation facts, lifecycle hooks, and core-owned resolution boundaries.
- [x] 3.6 Rewrite the bundled counter example against version-2 namespaced storage and declarative UI contributions, deliberately removing its old model data path.
- [x] 3.7 Remove the version-1 entry-point groups, model-package contract, direct counter fallback, and compatibility loader after all bundled callers and tests use version 2.

## 4. Catalogue and Candidate Inspection

- [x] 4.1 Define the maintained first-party catalogue format and add server-side loading, validation, pinned source/release metadata, publisher trust, compatibility, digest, and documentation fields.
- [x] 4.2 Add authenticated catalogue and installed-inventory APIs that join catalogue, verified manifest, installation, update, desired state, observed health, permissions, and action availability.
- [x] 4.3 Implement staged HTTPS Git acquisition with URL validation, optional revision, resolved-commit capture, mutable-ref classification, bounded checkout, and cleanup.
- [x] 4.4 Inspect source and built artifacts before activation, compare verified identity/version with catalogue expectations, and persist reproducible provenance and trust acknowledgement.
- [x] 4.5 Add tests for first-party matching, catalogue mismatch, malformed repositories, pinned and mutable revisions, unsupported URLs, cancellation, timeout, and non-staff rejection.

## 5. Immutable Plugin Overlay Generations

- [x] 5.1 Define the application-owned overlay directory layout, generation manifest/index, active and last-known-good pointers, staging rules, retention bounds, and local-development override.
- [x] 5.2 Add early runtime bootstrap that appends the selected overlay after core site-packages before entry-point discovery and enters a diagnosable recovery mode for an invalid pointer.
- [x] 5.3 Export immutable core dependency constraints and implement full installed-plugin resolution that rejects replacement or incompatible use of core packages.
- [x] 5.4 Build candidate wheels and dependencies into a fresh staging generation as the unprivileged service account, recording artifact digests, resolved versions, logs, and environment fingerprint.
- [x] 5.5 Implement a fixed plugin-control helper for server-owned generation identifiers, validation, atomic pointer switch, rollback, and bounded cleanup without accepting commands, service names, or arbitrary destination paths.
- [x] 5.6 Validate the complete staged generation through manifest parsing, entry-point import, contract registration, namespace checks, and catalogue generation before switching it active.
- [x] 5.7 Add tests for dependency conflict, build failure, malicious paths, partial generation, atomic switch, rollback, active-generation retention, and base-environment non-mutation.

## 6. Persistent Operations and Lifecycle

- [x] 6.1 Implement the serialized plugin operation state machine with idempotency keys, stages, timestamps, progress, bounded diagnostics, input/output generations, cancellation boundaries, and concurrency tokens.
- [x] 6.2 Add the background acquisition/build/validation worker and its structured handoff to the allowlisted plugin-control helper.
- [x] 6.3 Implement install, enable, disable, update, uninstall, retry, cleanup, and rollback commands with per-operation effective lifecycle impact.
- [x] 6.4 Implement hot start/stop gating for eligible loaded plugins and raise the effective impact to application restart when hooks, routes, processing, or managed resources cannot deactivate safely.
- [x] 6.5 Integrate application-service restart and separately confirmed host-reboot transitions with the existing guarded system-control APIs.
- [x] 6.6 Add startup finalization that resumes restart-pending operations, validates the expected generation and registry state, runs bounded health verification, and requests rollback on failure.
- [x] 6.7 Expose operation list/detail/status APIs suitable for polling through expected service disconnection and reconnect.
- [x] 6.8 Test duplicate requests, stale tokens, worker interruption, application restart, failed health gate, rollback failure, host-reboot pending state, and unrelated API availability.

## 7. Declarative UI Contract and Renderer

- [x] 7.1 Define shared TypeScript types and validators for plugin navigation, pages, data bindings, presentation hierarchy, fields, actions, permissions, operations, freshness, and schema versions.
- [x] 7.2 Add authenticated plugin-descriptor bootstrap with ETag caching, bounded payloads, stale-state handling, and no blocking dependency on plugin data endpoints.
- [x] 7.3 Integrate enabled plugin navigation and Refine resources with a stable `/plugins/:pluginId/:pageId` route while keeping disabled and failed plugins accessible only through Plugins diagnostics.
- [x] 7.4 Build product-owned Ant Design templates for settings, resource list/detail, overview/status, and guided flows with consistent headers, cards, tabs, empty states, skeletons, and responsive layout.
- [x] 7.5 Build typed widgets for scalar, numeric, boolean, enum, multiselect, duration, path, URL, secret, repeatable, and nested fields with help, defaults, constraints, conditional visibility, and safe cross-field validation.
- [x] 7.6 Implement stable action/status regions, server-advertised availability, confirmations, concurrency tokens, operation progress, reconnect handling, notifications, and duplicate-submit protection.
- [x] 7.7 Add per-plugin page error boundaries, invalid-descriptor diagnostics, authorization filtering, keyboard/focus behavior, accessible labels, and unknown-template fail-closed behavior.
- [x] 7.8 Add component and integration tests for runtime navigation changes, slow/failed endpoints, secrets, conditionals, repeatable fields, layout stability, responsive rendering, accessibility, and error isolation.

## 8. Plugins Administration Experience

- [x] 8.1 Add a top-level Plugins menu with visually distinct Marketplace and Installed views, search/filtering, compatible/incompatible states, source trust, versions, capabilities, permissions, health, and update summaries.
- [x] 8.2 Add plugin detail pages with provenance, manifest metadata, configuration/data state, resources, diagnostics, operation history, documentation links, and lifecycle actions.
- [x] 8.3 Add first-party installation flow with artifact verification summary, permissions, lifecycle impact, progress, expected restart, failure recovery, and success handoff to the plugin's page.
- [x] 8.4 Add an advanced Git-source flow with repository/revision input, resolved-commit preview, mutable-ref warning, explicit trusted-code acknowledgement, validation diagnostics, and retry cleanup.
- [x] 8.5 Add enable, disable, update, uninstall, retained/delete-data, restart-pending, and rollback interactions with destructive controls visually separated and stale actions guarded.
- [x] 8.6 Verify that background refresh, operation progress, alerts, and reconnect states keep primary controls spatially stable and do not delay core dashboard/navigation startup.

## 9. Deployment and Appliance Safety

- [x] 9.1 Add deployment variables, directories, ownership, quotas, environment/bootstrap configuration, and backup metadata for plugin overlays, staging, provenance, secrets, and operations.
- [x] 9.2 Install the plugin-control helper and minimum sudo/systemd authorization for fixed generation and Open Cinema restart operations; prove arbitrary paths, units, and commands are rejected.
- [x] 9.3 Coordinate API, worker, and orchestrator restart order so active audio is stopped or preserved according to existing transition policy and plugin operations finalize after fresh readiness.
- [x] 9.4 Extend readiness, rollback, diagnostics collection, and release manifests with plugin generation identity, overlay integrity, pending operations, incompatible plugins, and last-known-good recovery.
- [x] 9.5 Provide a documented local-development path for installing an editable plugin directory without weakening production source/provenance rules.

## 10. SDK, Documentation, and Examples

- [x] 10.1 Package the versioned plugin SDK schemas, typed contracts, validators, frozen contexts, action/result helpers, and pytest contract suite for external repositories.
- [x] 10.2 Write the plugin author guide covering package layout, static manifest, entry point, capabilities, namespaces, storage, secrets, configuration migrations, lifecycle, UI templates, security, CI, release, and compatibility.
- [x] 10.3 Document administrator marketplace, Git trust, enable/disable, restart, update, uninstall, retained data, rollback, and diagnostic workflows.
- [x] 10.4 Turn the bundled counter into a minimal external-author example in documentation and validate both its source checkout and built wheel with the public contract suite.
- [x] 10.5 Update Open Cinema and UI READMEs, architecture documents, API references, and deployment documentation to remove version-1 plugin instructions.

## 11. Acceptance and Release

- [x] 11.1 Run backend unit/integration tests, plugin contract fixtures, static checks, migration checks, and packaging tests in the Open Cinema CI matrix.
- [x] 11.2 Run admin UI type checks, lint, unit tests, production build, accessibility checks, and plugin-renderer integration fixtures in the UI CI matrix.
- [ ] 11.3 Exercise local catalogue install, pinned and mutable Git install, hot and restart-required enable/disable, update, failed build, failed activation, rollback, retained-data uninstall, and reinstall end to end.
- [ ] 11.4 Validate overlay installation, service restart recovery, permissions, storage bounds, UI reconnect, and rollback on the Raspberry Pi without regressing active audio, dashboard responsiveness, or core graph control.
- [x] 11.5 Validate the separate librespot repository against the SDK as the first composite UI and managed-audio-source plugin, feeding only genuine reusable gaps back into contract version 2.
- [ ] 11.6 Update versions and changelogs according to each repository's release strategy, run release pipelines, pin the published contract/catalogue artifacts, and record final acceptance and rollback evidence.
