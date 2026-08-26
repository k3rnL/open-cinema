## Context

See `proposal.md` for the hardware failure. The current controller prepares and starts decoder/CamillaDSP processes, waits until their stable node identities are matchable, builds individual managed-link actions from one world snapshot, executes those actions in identifier order, and verifies processor control health afterward. It does not verify the complete resulting link topology from one fresh snapshot before marking the plan converged. Route order can feed CamillaDSP before all downstream links exist, and the orchestrator currently gives up after eight immediate catch-up passes until another external event arrives.

PipeWire/WyrePlumber exposes individual managed-link mutations rather than a transaction spanning an arbitrary multi-node topology. The implementation therefore needs a safe audible activation boundary and fresh verification instead of pretending link creation itself is atomic. Existing desired graphs, stable processor identities, transition journals, ownership tags, and public APIs must remain compatible.

## Goals / Non-Goals

**Goals:**

- Make complete processor topology—not process health or individual action success—the convergence condition.
- Keep programme audio out of a processor chain until its downstream route is ready.
- Recover automatically from processor and PipeWire identifier replacement without waiting forever for another event.
- Retain idempotent, graph-scoped ownership and useful transition evidence.
- Make the reproduced eight-channel failure deterministic in tests and validate the correction on the Pi.

**Non-Goals:**

- Add a generic PipeWire patch-bay or support the deferred advanced managed-link shapes.
- Add parallel processor instances or change resource allocation policy.
- Guarantee gapless audio across process restart; bounded silence is safer than partial or invalid audio.
- Change graph documents, profile documents, endpoint identity, or UI authoring behavior.

## Decisions

### 1. Materialize a complete topology expectation before mutation

Route planning will produce both phased actions and an immutable expectation containing every required graph-owned link: desired identity, edge, channel, current-generation node/port runtime keys, and whether the link is programme ingress. Planning fails before mutation if the selected processor nodes do not expose the complete channel/port contract needed to construct that expectation.

This keeps verification independent of action return values and provides structured missing/mismatched-link evidence. Relying only on each link action's confirmation was rejected because confirmations happen at different runtime sequences and do not prove that all links coexist afterward.

### 2. Use ingress deferral as the audible activation boundary

For a processor path requiring mutation, graph-owned source-facing ingress links are suppressed or withheld first. The executor then establishes output-facing links and processor-internal links from downstream to upstream. A fresh snapshot must satisfy the downstream expectation before ingress actions run. After ingress, another fresh snapshot must satisfy the complete expectation before the applied plan advances.

This is a practical transaction surrogate: an idle but fully wired downstream chain is safe, while an early ingress link can start CamillaDSP and fill buffers before playback is connected. A global device mute was rejected as the sole mechanism because not every source/sink exposes reliable mute controls and it would unnecessarily affect unrelated audio. A future driver-specific mute/fade can wrap the same topology gate.

### 3. Verify ownership and exact current-generation endpoints as a set

Topology verification will refresh the authoritative world and compare the complete expectation against Open Cinema-owned links. Every required identity must occur exactly once and match all four node/port endpoints. Missing, duplicate, stale-generation, and mismatched links are classified separately. Unmanaged links and other graphs are ignored and never adopted or removed.

On failure, the journal records the evidence and graph-owned links created for the failed target are removed where safe. The previous route is restored only when its resources remain viable; otherwise the path stays suppressed and the graph is degraded/failed rather than falsely converged.

### 4. Separate processor health verification from topology verification

Driver observation still proves decoder status-channel health and CamillaDSP engine readiness. Runtime resource readiness will additionally include the complete profile-required port set, while link topology is verified by the live reconciler. Diagnostics retain these as separate evidence so a healthy CamillaDSP process with missing links is not misreported as a processor-control failure.

### 5. Add a deadline-driven catch-up retry to the existing event loop

After the immediate catch-up limit, the service stores a pending retry deadline and cause. The connected-session loop reduces its event wait timeout to that deadline and invokes reconciliation when due even if the consumed batch contains no runtime event. Repeated exhaustion advances a bounded backoff; successful catch-up clears it. Only the active controller owns this state, so retries cannot overlap.

An outcome explicitly distinguishes transition-invalidating advancement from a
satisfied no-op that merely refreshed processor readiness. Both update the
authoritative world projection, but only the former drives immediate catch-up.
This prevents an active PipeWire stream from making the controller chase
sequence changes created or absorbed by its own readiness observations.

This avoids a helper thread and preserves the single-controller mutation model. Waiting exclusively for another WirePlumber event was rejected because the reproduced runtime can become quiet while still incomplete. Unbounded immediate catch-up was rejected because processor/link events can create a busy loop.

### 6. Keep acceptance claims tied to the stronger scenario

The new automated tests will cover partial eight-channel registration/linking, new processor IDs, idempotent existing links, topology disappearance during verification, continuous advancement, and a quiet runtime after catch-up exhaustion. Raspberry Pi acceptance will restart CamillaDSP, the decoder, the orchestrator, and relevant combinations while the active eight-channel graph is selected, then verify all required links, audio recovery, bounded gap, and absence of sustained buffer warnings.

The existing deployment restart tasks were checked using narrower probes. Their historical work remains, but final appliance acceptance depends on the new change and the still-open benchmark/functional tasks.

## Risks / Trade-offs

- **[Risk] Downstream-first activation increases the intentional silent interval.** → Keep retries and readiness waits bounded, measure the audible gap, and prefer silence to partial-channel output or buffer floods.
- **[Risk] A fresh snapshot may advance while verification is running.** → Bind expectations to one runtime generation, reject stale identities, and rebuild from the newest snapshot on the scheduled retry.
- **[Risk] Cleanup after partial failure could affect a replacement attempt.** → Target only exact graph-owned desired identities recorded in the transition expectation and make removal idempotent.
- **[Risk] Port publication order differs between processors and PipeWire versions.** → Match stable node identities plus declared channel contracts and wait within the existing bounded processor readiness window.
- **[Risk] Frequent runtime events can repeatedly defer convergence.** → Combine limited immediate passes with delayed bounded backoff and one pending retry owned by the event loop.

## Migration Plan

1. Land topology expectation, ordering, verification, diagnostics, and catch-up retry behind the existing live-reconciliation feature gate; no data migration is needed.
2. Run focused and full local tests, then deploy the backend to the Pi without changing the desired graph or processor profiles.
3. Restart components individually and together, capturing runtime links, journal/status evidence, CamillaDSP/decoder warnings, recovery time, and audible result.
4. Roll back by deploying the prior backend revision and restarting only the orchestrator. Existing graph/profile data and stable processor units remain compatible.
