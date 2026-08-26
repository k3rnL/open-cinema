# Local audio orchestration acceptance report

Status: **automated local-product acceptance and explicit owner UI acceptance passed**.

This report covers the non-deployment requirements of OpenSpec change
`wireplumber-desired-graph-orchestration`. Raspberry Pi installation, service
packaging, hardware measurements, and production tuning belong to the separate
`deploy-raspberry-audio-appliance` change and are not local-product blockers.

Legacy audio data and compatibility are deliberately absent. The sole owner
confirmed that the old alpha data may be deleted, so destructive removal is the
required behavior rather than a migration limitation.

## Verification snapshot

The following checks were run locally on 2026-08-23:

| Repository/boundary | Result |
| --- | --- |
| Open Cinema backend | `uv run pytest -q`: **701 passed**; `manage.py check` and `makemigrations --check --dry-run` passed |
| Fresh database | All migrations through `api.0051_remove_legacy_audio_models` applied to a new SQLite database; post-migration Django check passed |
| Management and on-box UI | TypeScript checks passed; **14** component/contract tests passed; both production builds passed; **3** Playwright flows passed with serious/critical Axe checks |
| Visual baseline | Accepted views are recorded in `open-cinema-ui/docs/ui-baseline`; current dashboard, discovery, canvas, and selected-node views are in `open-cinema-ui/docs/ui-current` |
| WyrePlumber binding | `uv run pytest tests -q`: **196 passed, 1 host-native connection fixture failed** because `wp_core_connect` could not connect to its temporary PipeWire socket in this environment. Open Cinema contract/fake integration passes; native binding CI remains required before release. |
| PCM auto decoder | Open Cinema decoder contract/fixture tests pass. `cargo` is not installed in this environment, so the adjacent Rust suite must be confirmed by that repository's CI before release. |

On 2026-08-24 the owner explicitly accepted the graph editor, endpoint-adapter
UI, navigation, discovery, processor editing, Save/Apply behavior,
validation/error feedback, simple and advanced views, live overlays, and visual
baseline as a suitable foundation for appliance deployment. Minor UI details
remain possible future improvements, but are not deployment blockers.

## Adaptive signal processing

| Requirement | Evidence |
| --- | --- |
| Signal descriptors separate transport, content, and decoded output | `tests/test_signal_descriptors.py`, `tests/test_adaptive_signal_fixtures.py`, decoder `tests/status_fixtures.rs` |
| Decoder reports structured state | `tests/test_decoder_driver.py`, decoder `src/status_protocol.rs` and `tests/status_fixtures.rs` |
| Format observations trigger resolution | `tests/test_world_state_scheduler.py`, `tests/test_adaptive_signal_fixtures.py` |
| Adaptive decisions use stability controls | `tests/test_world_state_scheduler.py`, `tests/test_adaptive_signal_fixtures.py` |
| Decoder bypass is explicit | `tests/test_adaptive_decoder.py`, `tests/test_adaptive_signal_fixtures.py` |
| Actual decoded format is authoritative | `tests/test_signal_observation_resolution.py`, `tests/test_adaptive_processing_acceptance.py` |
| Decoder communication failure is visible | `tests/test_decoder_driver.py` socket-failure/recovery coverage |
| Signal state is available to users and plugins | `tests/test_audio_v1_api.py`, UI orchestration tests, `DECODER_DRIVER.md` |

## Audio endpoint inventory

| Requirement | Evidence |
| --- | --- |
| Logical endpoints have stable identity | `tests/test_endpoint_identity.py`, `tests/test_recorded_endpoint_snapshots.py` |
| Endpoint selectors use observable properties | `tests/test_endpoint_selectors.py`, `tests/test_endpoint_binding.py` |
| Endpoint matching is deterministic and explainable | `tests/test_endpoint_matching.py`, `tests/test_logical_endpoint_selection.py` |
| Inventory distinguishes availability states | `tests/test_endpoint_projection.py`, `tests/test_recorded_endpoint_snapshots.py`, management discovery E2E |
| Inventory exposes capabilities | `tests/test_endpoint_audio_projection.py`, `tests/test_endpoint_inventory_mapping.py` |
| Inventory distinguishes endpoint candidates from processor resources | `tests/test_audio_v1_api.py`, management discovery E2E |
| Users can explicitly bind endpoints | `tests/test_endpoint_binding.py`, `tests/test_audio_v1_api.py`, discovery selector-preview UI |
| Endpoint groups support intent | `tests/test_logical_endpoint.py`, `tests/test_logical_endpoint_selection.py` |
| Runtime inventory updates are monotonic per snapshot version | `tests/test_endpoint_continuity.py`, `tests/test_runtime_event_consumer.py` |

## Audio orchestration API and UI

| Requirement | Evidence / status |
| --- | --- |
| APIs separate desired, resolved, applied, and runtime representations | `tests/test_audio_v1_api.py`, shared store/contract tests, `API_V1.md` |
| The management and on-box applications retain distinct roles | Admin and placeholder component/E2E tests; `open-cinema-ui/docs/UI_BASELINE.md` |
| The existing management experience is evolved in place | Preserved React Flow canvas/node interaction in `AdvancedGraphEditor.tsx`, graph E2E, and explicit owner acceptance on 2026-08-24 |
| Existing look and feel is the visual baseline | Baseline/current reference images, `ui-regression.test.ts`, and explicit owner acceptance on 2026-08-24 |
| Graph and subgraph editing supports drafts and revisions | `tests/test_graph_revision_workflow.py`, admin component tests and graph E2E |
| Save and Apply have separate effects | Admin component tests and E2E, backend revision publish/atomic activation tests, and explicit owner acceptance on 2026-08-24 |
| Processors are first-class insertable graph nodes | Node catalogue/processing tests, processor palette and node editing E2E |
| Parameterized subgraphs are manageable | `tests/test_subgraph_expansion.py`, `tests/test_subgraph_upgrade_dry_run.py`, admin component tests |
| Simple configuration is rule-oriented | Shared rule compile/round-trip tests and same-document extension implementation |
| Advanced graph editing preserves direct manipulation | Canvas E2E covers palette, selection, inline fields, typed nodes, Save, Apply, and convergence |
| Device discovery remains a dedicated management workflow | Discovery component/E2E coverage and current reference view |
| Resolution explanations are visible | `tests/test_resolved_plan_output.py`, `tests/test_audio_v1_api.py`, `PlanExplanation.tsx` |
| Live updates are efficient and recoverable | `tests/test_redis_events.py`, backend SSE gap/resume tests, shared event-store tests |
| Manual controls are explicit overrides | `tests/test_manual_override.py`, `tests/test_manual_override_resolution.py` |
| Shared client contracts do not collapse application roles | Shared DTO/API tests plus independent admin and placeholder app tests |
| Degraded operation remains understandable | `tests/test_orchestrator_recovery.py`, API readiness tests, admin readiness alerts and overlays |

## Audio processing plugins

| Requirement | Evidence |
| --- | --- |
| Processing plugins register graph node types | `tests/test_plugin_contracts.py`, `tests/test_node_catalogue.py` |
| Plugins do not provide audio runtimes | `tests/test_plugin_contracts.py` prohibited-capability tests |
| Plugin schemas are serializable | `tests/test_plugin_contracts.py`, API node-catalogue schema tests |
| Plugins participate in validation and planning | Typed and failure-isolated hook tests in `tests/test_plugin_contracts.py` |
| Runtime lifecycle is reconciliation-driven | Processing driver lifecycle, timeout, and retry tests |
| Plugins expose processor health and state | Plugin contract, plan, API, and management-overlay tests |
| Plugin failures are contained | Import/start/validation/planning/timeout/schema failure tests in `tests/test_plugin_contracts.py` |
| Plugin upgrades preserve graph compatibility | `tests/test_unknown_plugin_graph_nodes.py`, plugin configuration migration tests |
| General application plugins remain supported | `tests/test_application_plugin_integration.py`; fresh-database Django startup registered the counter plugin |

## Audio reconciliation

| Requirement | Evidence |
| --- | --- |
| Relevant changes trigger reconciliation | `tests/test_reconciliation_scheduler.py`, `tests/test_desired_state_monitor.py` |
| Reconciliation is debounced and convergent | Scheduler tests including the 10,000-event stress burst; `tests/test_drift_reconciliation.py` |
| Runtime operations are idempotent | `tests/test_idempotent_execution.py`, `tests/test_transition_journal.py` |
| Plans are applied as ordered transitions | `tests/test_action_planning.py`, `tests/test_camilladsp_driver.py` |
| Unsafe transitions are suppressed | `tests/test_transition_suppression.py`, CamillaDSP format-change tests |
| Failed transitions preserve or restore service | `tests/test_transition_recovery.py`, UI Apply failure messaging |
| Reconciliation publishes lifecycle status | `tests/test_reconciliation_audit.py`, `tests/test_orchestrator_lifecycle.py`, SSE tests |
| Retries use bounded backoff | `tests/test_action_retry.py`, `tests/test_configurable_safety_bounds.py`, `tests/test_orchestrator_recovery.py` |
| Reconciliation is auditable | `tests/test_reconciliation_audit.py`, `tests/test_state_correlation.py` |

## Audio route resolution

| Requirement | Evidence |
| --- | --- |
| Resolution consumes a consistent world snapshot | `tests/test_resolver_inputs.py`, `tests/test_generation_guard.py` |
| Conditions are evaluated against typed facts | Fact catalogue and condition validation/evaluation suites, including configurable depth bounds |
| Selectors support priority and fallback | `tests/test_path_selection.py`, `tests/test_canonical_orchestration_execution.py` |
| Graphs support fan-out and mixing intent | `tests/test_path_selection.py`, `tests/test_graph_validation.py` |
| Resolution negotiates compatible signal paths | `tests/test_signal_negotiation.py`, `tests/test_camilladsp_config.py` |
| Manual overrides have explicit scope and lifetime | `tests/test_manual_override_resolution.py` |
| Resolution is deterministic | `tests/test_resolver_properties.py`, `tests/test_resolver_replay.py` |
| Resolved plans are explainable | `tests/test_resolved_plan_output.py`, `tests/test_condition_explanations.py` |
| Unresolvable intent produces explicit state | Missing endpoint/resource cases in `tests/test_resolver_pipeline.py` |

## CamillaDSP graph processing

| Requirement | Evidence |
| --- | --- |
| CamillaDSP is an insertable processor rather than an endpoint | Core node catalogue tests; admin processor palette/node E2E |
| CamillaDSP configurations are reusable processing profiles | `tests/test_camilladsp_profiles.py`, v1 immutable profile API tests, profile management page |
| CamillaDSP nodes declare signal contracts | `tests/test_camilladsp_profiles.py`, `tests/test_node_catalogue.py` |
| Configuration is generated from the resolved plan | `tests/test_camilladsp_config.py`, `tests/test_adaptive_processing_acceptance.py` |
| Configuration is validated before activation | `tests/test_camilladsp_config.py`, `tests/test_camilladsp_driver.py` |
| CamillaDSP exposes stable PipeWire-facing endpoints | `tests/test_camilladsp_deployment.py` contract fake; physical/runtime packaging is deferred |
| Reconfiguration is coordinated safely | Rollback and format-phase tests in `tests/test_camilladsp_driver.py` |
| CamillaDSP health and active profile are observable | Control disconnect/restart test plus v1 processor/runtime endpoints and UI overlays |
| Processor resource policy is explicit | `tests/test_resource_allocation.py` and resolver resource tests |
| Legacy CamillaDSP storage is removed | Migration `0051`, fresh migration check, `tests/test_removed_audio_routes.py`; only immutable v1 profiles remain |

## Desired audio graphs

| Requirement | Evidence |
| --- | --- |
| Desired graphs are persistent intent | Dependency disappearance/return tests; graph model/revision suites |
| Graphs use typed nodes and ports | `tests/test_graph_validation.py`, `tests/test_signal_contracts.py`, canvas E2E |
| Graphs distinguish endpoints from processors | Node catalogue/schema tests; discovery and processor-palette UI tests |
| Graph parameters are declared and validated | `tests/test_graph_parameters.py`, resolver parameter override tests |
| Graphs support reusable subgraphs | `tests/test_subgraph_expansion.py`, `tests/test_subgraph_interface.py` |
| Subgraphs are versioned | `tests/test_subgraph_revision_pins.py`, `tests/test_subgraph_upgrade_dry_run.py` |
| Graph revisions are editable without disrupting the active revision | `tests/test_graph_revision.py`, workflow/API tests, explicit Save/Apply UI behavior |
| Structural validation is independent from availability | `tests/test_graph_validation.py`, dependency disappearance/return acceptance test |
| Desired graph serialization is stable | `tests/test_graph_document_normalization.py`, `tests/test_graph_import_export.py` |

## WirePlumber runtime control

| Requirement | Evidence / limitation |
| --- | --- |
| WirePlumber is the required audio runtime | Open Cinema startup/contract tests and WyrePlumber runtime contract suite |
| Audio backend selection is removed | Deleted source/dependencies, `tests/test_removed_audio_routes.py`, plugin deny-list tests, v1-only UI scan |
| Full runtime snapshots are available | Open Cinema runtime mapping/world tests and WyrePlumber snapshot suites |
| Runtime changes are observable | Runtime event/queue/lifecycle/continuity suites and SSE recovery tests |
| Runtime controls use WirePlumber semantics | WyrePlumber control contracts and Open Cinema driver adapter suites |
| Managed and unmanaged runtime objects are distinguished | Managed-link ownership tests and canonical reconciliation integration |
| Runtime identifiers are transient | Endpoint identity/restart and stale-runtime-key tests |
| Connection access is serialized safely | WyrePlumber mutation-dispatch tests and SQLite/controller concurrency tests |
| The native audio-runtime boundary is exclusive | PipeWire is authoritative; any later protocol bridge must be an explicitly declared processor dependency rather than an alternative backend. |

## Cross-cutting local scenarios and safety

| Scenario/boundary | Evidence |
| --- | --- |
| TV to main speakers, Bluetooth source priority, headset takeover and removal fallback | `tests/test_canonical_orchestration_execution.py`, WirePlumber adapter integration |
| PCM/AC-3/E-AC-3/DTS processor choice | Adaptive processing fixtures and generated CamillaDSP configuration tests |
| Missing endpoints/processors and later return | Resolver dependency disappearance/return and subgraph tests |
| Endpoint/scene/volume/mute overrides | Scope, expiry, provenance, cancellation, and deterministic reversion suites |
| Event loss, queue overflow, Redis/DB/runtime/processor failures | Recovery, event, contention, journal, CamillaDSP, and decoder suites |
| Ownership, generation fencing, suppression, and safe fallback | Managed-link refusal, generation guard, suppression, and transition recovery suites |
| Untrusted input and denial-of-service boundaries | API authorization/redaction tests, graph/condition schema bounds, Redis event/snapshot bounds, `tests/test_configurable_safety_bounds.py` |
| Legacy removal | Fresh database migration, removed-route tests, executable-source/dependency scan, v1-only UI contracts |

## Local acceptance decision

The owner accepted the current local product on 2026-08-24 and authorized
archiving both `wireplumber-desired-graph-orchestration` and
`managed-audio-endpoint-adapters`. Both changes were archived after their delta
specifications were synchronized and strictly validated. Raspberry Pi release
packaging, physical Bluetooth/audio checks, performance limits, and rollback
remain deployment work rather than local-product acceptance gaps.
