## Context

See `proposal.md` for motivation and `specs/raspberry-audio-deployment/spec.md` for the observable appliance contract.

The deployment already operates the current cooled Raspberry Pi 5 8 GB fixture as a headless native-PipeWire appliance. Existing roles establish the service identity, audio session, BlueZ policy, managed processors, application services, readiness checks, backups, and rollback mechanics. The remaining work is to remove retired compatibility configuration, consume coordinated immutable artifacts, and close reproducibility and rollback evidence without reopening product UI or audio-model decisions.

The accepted runtime spans `open-cinema`, `wyreplumber`, `open-cinema-ui`, and `pcm-auto-decoder`, plus PipeWire, WirePlumber, CamillaDSP, state services where enabled, and nginx. Component release publication is owned by `publish-coordinated-project-releases`; hardware measurements and broader platform limits are owned by `benchmark-raspberry-audio-appliance`.

Historic implementation and appliance evidence remains in:

- `deployment/acceptance/2026-08-25-local-product-baseline.md`
- `deployment/acceptance/2026-08-25-static-dynamic-boundary.md`
- `deployment/acceptance/2026-08-25-service-restart-matrix.md`
- `deployment/acceptance/2026-08-25-interrupted-transition-recovery.md`
- `deployment/acceptance/2026-08-26-tv-spdif-input.md`
- `deployment/acceptance/2026-08-26-bluetooth-programme-source.md`
- `deployment/acceptance/2026-08-26-bluetooth-headset-output.md`
- `deployment/acceptance/2026-08-26-adaptive-bluetooth-routing.md`
- `deployment/acceptance/2026-08-26-coordinated-rollback.md`

Those reports are supporting evidence, not a reason to retain their former microtasks in this narrowed plan.

## Goals / Non-Goals

**Goals:**

- Reproduce the accepted runtime on the already provisioned current appliance from one coordinated manifest.
- Make mutable development inputs and immutable appliance inputs explicit and impossible to confuse.
- Keep a single headless audio-session identity and a native processor topology.
- Preserve clear static-versus-dynamic ownership, readiness, least privilege, diagnostics, backup, and rollback.
- Finish with a short, auditable deployment acceptance record.

**Non-Goals:**

- Qualifying a fresh Raspberry Pi OS image or arbitrary older-to-newer upgrade paths.
- Benchmarking hardware, selecting performance limits, or extending support beyond the current Pi 5 8 GB fixture.
- Publishing commits, component versions, packages, tags, or coordinated releases.
- Redesigning desired graphs, processor behavior, endpoint identity, routing policy, or the management UI.
- Requiring a staged feature rollout or a ceremonial user checkpoint for behavior already accepted on hardware.

## Decisions

### 1. Treat the current fixture as the entire supported platform boundary

The coordinated manifest identifies the exact operating-system and runtime family used by the current Raspberry Pi 5 8 GB appliance. Preflight accepts that boundary and rejects mismatched hosts before migrations or audio mutation. A later benchmark change may broaden or constrain it.

**Why:** One known target is enough to finish development deployment safely; claiming support for unmeasured platforms would add work without evidence.

**Alternative considered:** Keep a candidate platform matrix in this change. Deferred because hardware characterization now has its own change.

### 2. Keep explicit development and appliance input modes

Development mode may install from local source trees and records the result as mutable and non-release. Appliance mode uses the coordinated manifest as the authority and accepts only release artifacts, immutable commit artifacts, or equivalent content-addressed inputs. Preflight reports all mutable or incompatible inputs before installation.

The release change publishes and versions those inputs. This change consumes them, verifies provenance and compatibility, and records the installed manifest digest.

**Why:** Local paths make iteration efficient, but the same inputs cannot define a reproducible or restorable appliance.

**Alternative considered:** Remove local-source support entirely. Rejected because it remains valuable during active multi-repository development when it cannot be mistaken for release mode.

### 3. Run one headless user audio session under a dedicated identity

A dedicated non-interactive Open Cinema account owns the PipeWire and WirePlumber user session and its XDG runtime directory. Linger and the user manager start it at boot without graphical login. Every consuming system service derives socket paths, D-Bus access, groups, runtime directories, and ownership from that configured identity.

**Why:** A single identity prevents split audio worlds, inaccessible sockets, and devices visible to a developer login but not the appliance.

**Alternative considered:** Run a separate system-wide audio daemon. Deferred because the current distribution-aligned user-session design is already accepted and tested.

### 4. Keep Ansible static and Open Cinema dynamic

Ansible owns packages, identities, permissions, units, environment defaults, base policy overlays, readiness, backups, and rollback. Open Cinema owns graph revisions, endpoint bindings, processor profiles, parameters, rules, scenes, active revisions, and manual overrides.

No playbook task derives static files from a saved graph, and Save or Apply never invokes deployment automation.

**Why:** This leaves one controller for runtime audio intent and makes repeat deployment idempotent without damaging user state.

### 5. Install named overlays instead of replacing distribution configuration

PipeWire and WirePlumber policy uses identifiable Open Cinema fragments and systemd overrides with explicit ownership and removal behavior. Distribution files remain untouched. The final cleanup removes retired compatibility-service configuration rather than leaving dormant selectable paths in current inventory or templates.

**Why:** Small overlays make package ownership clear and let preflight and readiness attribute failures to the appliance configuration.

**Alternative considered:** Render complete distribution configuration from Ansible. Rejected because it silently couples deployment to package-internal defaults.

### 6. Require native, correlated managed-processor resources

CamillaDSP and the adaptive decoder use native PipeWire I/O. Their units expose stable Open Cinema instance identities, bounded runtime directories, control and status endpoints, and correlated node properties. WirePlumber chooses targets; processors do not autoconnect themselves. Runtime nodes are managed resources rather than discoverable physical endpoints.

**Why:** Stable logical identity survives process and audio-session restarts while keeping routing policy in one place.

**Alternative considered:** Correlate processors by transient object identifiers or node names. Rejected because both can change across restarts and collide across instances.

### 7. Make readiness, not elapsed time, the service dependency

Systemd ordering establishes prerequisites, while bounded readiness probes prove usable sockets, discovery, contracts, migrations, processor resources, web services, and absence of an unsafe unfinished transition. The API may remain available in diagnosable degraded mode, but unsafe audio mutation stays disabled until the runtime is ready.

**Why:** Unit activation and fixed delays cannot prove that the distributed audio graph is usable.

**Alternative considered:** Add conservative sleeps after boot and restart. Rejected because correctness would depend on machine load and hide the failing component.

### 8. Treat appliance installation as a manifest-backed transaction

Before a candidate transition, deployment records component identities and snapshots the database, generated processor configuration, inventory, and managed static files needed by the previous manifest. Installation, migration, service startup, and readiness form one transition. Only a fully ready result becomes the installed successful manifest.

Failure retains correlated diagnostics and the prior restorable state. Rollback selects the retained manifest and restores compatible application, UI, binding, decoder, processor, configuration, and database identities together.

The transition record is schema-aware. A release-mode application archive
already contains the exact wheel-installed WyrePlumber binding inside its
virtual environment, so a separate binding-source archive is optional after an
installed version/API/orchestration/runtime-contract probe succeeds and the
resolved virtual environment is proven to be inside the archived application
root. A mutable development generation is recorded explicitly and still
requires a real, non-symlink WyrePlumber source directory. READY and the
manifest must agree exactly on whichever restore boundary applies, and retained
schema-1 bundles remain readable.

Readiness selects an active recovery identity only from immediate rollback
directories whose manifest, READY record, schema, mode/source relationship,
regular-file boundary, and every artifact digest verify. A newer partial or
malformed directory can therefore neither displace a complete bundle nor cause
that bundle to be pruned. Window closure validates the active and protected
sets before deletion, verifies the retained set afterward, and only then writes
the correlated closure record. An unchanged later deployment preserves that
closed state while its release identity and retained bundles still agree.
If stricter verification exposes a malformed historical bundle and leaves no
verified mutable recovery point, an explicit operator-only reseed performs the
normal quiesce, full snapshot, install, gate, and readiness transaction against
the unchanged accepted manifest. It is disabled by default and may be combined
with pruning/closure only after the newly created and protected bundles verify.

**Why:** Rolling back only one protocol participant can create a stack that starts but cannot reconcile safely.

**Alternative considered:** Rely on package-manager downgrade and database backups independently. Rejected because they do not describe a coherent multi-repository runtime.

### 9. Verify idempotency and least privilege on the provisioned appliance

The final candidate is applied twice to the current configured host. The second run must leave managed state unchanged except for transient verification output. Checks cover file modes, service identities, sockets, secrets, backups, diagnostics, network exposure, and redaction.

This proves repeat deployment of the current appliance, not clean-image installation or compatibility with every prior release.

**Why:** Idempotency is valuable now and can be established without claiming the deferred fresh-install and upgrade matrix.

### 10. Keep management authentication in Django sessions

The management application uses the Django session and CSRF boundary for login, identity, protected API calls, and logout. The temporary development administrator remains an explicit private-network inventory input and must be replaced or disabled before broader exposure.

**Why:** This keeps one authorization boundary for the API and management UI and avoids a parallel token store.

**Alternative considered:** Require Django admin as the login entry. Rejected because the management console is the end-user appliance interface.

## Risks / Trade-offs

- **[Risk] An accepted component still depends on retired compatibility configuration.** → Make native resource readiness mandatory and fail preflight before removing the last restorable manifest.
- **[Risk] Immutable artifacts published by the release change do not match the tested source trees.** → Verify content identity, contract probes, and installed versions against the manifest before live reconciliation.
- **[Risk] Mixed system and user services lose access to runtime sockets.** → Derive paths and permissions from one service identity and probe access as each consumer.
- **[Risk] Database or generated configuration cannot cross the tested rollback boundary.** → Exercise restore on the current appliance and record irreversible boundaries before closure.
- **[Trade-off] Supporting only one fixture leaves fresh-install portability unknown.** → State that limitation explicitly and defer broader claims until the dedicated campaigns.

## Migration Plan

### Phase 1: Remove retired deployment paths

1. Remove active legacy compatibility-service inventory, roles, templates, handlers, preflight, readiness, and current documentation.
2. Simplify the coordinated manifest and checks to the native processor contracts.
3. Remove the active staged-rollout selector, local-product checkpoint gate, and graph allowlist from deployment; the contract gate remains the single mutation-safety boundary for the accepted full runtime.
4. Run focused syntax, unit, and deployment-policy tests before changing the appliance.

### Phase 2: Consume immutable coordinated inputs

1. After `publish-coordinated-project-releases` produces immutable component identities, replace appliance-mode local or editable inputs with those artifacts.
2. Record hashes and provenance in the coordinated manifest and reject mutable appliance-mode inputs.
3. Keep the explicit development path available and visibly non-release.

### Phase 3: Verify the current appliance

1. Apply the final manifest to the provisioned Raspberry Pi 5 8 GB fixture and retain the play recap, preflight, readiness output, and diagnostics.
2. Apply it a second time and confirm idempotency and dynamic-state preservation.
3. Recheck boot, restart recovery, native processor correlation, authentication, security boundaries, and the already accepted TV, Bluetooth source, headset takeover, and fallback smoke path.
4. Update deployment documentation with the intentionally narrow support and deferred campaigns.

### Phase 4: Exercise rollback and close

1. Capture a restorable previous coordinated manifest and state snapshot.
2. Transition to the immutable candidate, invoke coordinated rollback, and verify services, runtime identity, user state, and readiness.
3. Reapply the candidate and record both directions, retained artifacts, irreversible boundaries, and recovery instructions.
4. Map every narrowed requirement to automated output, retained acceptance evidence, or an explicit current limitation.

### Rollback

- Stop the candidate transition immediately on migration, installation, restart, or readiness failure.
- Preserve the failed candidate's manifest, logs, readiness result, and correlated diagnostic bundle.
- Restore the compatible database and generated configuration snapshot before reinstalling the previous coordinated component set when state contracts differ.
- Restore the coordinated participant set rather than one component unless the manifest explicitly declares the mixed combination compatible.
- Retain the prior artifacts and recovery instructions until deployment acceptance is closed deliberately.
