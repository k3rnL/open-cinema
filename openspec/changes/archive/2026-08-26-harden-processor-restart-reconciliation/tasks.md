## 1. Model complete processor topology readiness

- [x] 1.1 Add immutable expected-link and processor-topology value objects containing desired identity, graph edge, channel, current-generation endpoints, ownership, and ingress classification.
- [x] 1.2 Make limited-live route planning reject incomplete processor port/channel contracts before mutation and return structured missing-port evidence.
- [x] 1.3 Add a pure fresh-snapshot verifier that classifies missing, duplicate, endpoint-mismatched, stale-generation, and satisfied graph-owned links without inspecting or mutating unrelated links.

## 2. Apply processor routes through a safe activation boundary

- [x] 2.1 Partition processor route mutations into ingress suppression/deferral, downstream-to-upstream route establishment, and ingress activation while preserving deterministic idempotency keys and journal phases.
- [x] 2.2 Refresh and verify the downstream topology before ingress activation, then refresh and verify the complete topology plus processor health before marking the applied plan converged.
- [x] 2.3 On readiness or topology failure, keep ingress suppressed, remove only failed-target graph-owned links where safe, preserve the prior applied-plan pointer, and record rollback or safe-degraded evidence.
- [x] 2.4 Publish structured transition phase and evidence for processor-resource wait, downstream routing, topology verification, ingress activation, missing channels/links, and recovery outcome.

## 3. Guarantee reconciliation progress after runtime churn

- [x] 3.1 Add validated bounded settings/state for immediate catch-up passes and delayed retry backoff without changing the single active-controller model.
- [x] 3.2 Make the connected-session event loop wake for a pending reconciliation deadline and retry from the latest authoritative world even when no runtime or desired-state event arrives.
- [x] 3.3 Clear retry state on convergence/session replacement and ensure repeated catch-up exhaustion is bounded, non-overlapping, observable, and safe on shutdown.
- [x] 3.4 Distinguish a sequence advance absorbed by a satisfied no-op observation from transition-invalidating runtime churn so active streams do not cause self-induced catch-up retries.

## 4. Add deterministic regression coverage

- [x] 4.1 Test processor resource readiness with complete and incomplete declared CamillaDSP port sets and with replacement runtime keys.
- [x] 4.2 Test an eight-channel decoder-to-CamillaDSP-to-output rebuild for downstream-first ordering, complete-set verification, and no converged state while any channel is absent.
- [x] 4.3 Test link disappearance/mismatch during verification, idempotent existing links, safe graph-scoped cleanup, and preservation of unmanaged and other-graph links.
- [x] 4.4 Test continuously advancing catch-up passes followed by a quiet runtime and prove the deadline-driven retry converges without an external event or busy loop.
- [x] 4.5 Run the focused reconciliation/controller/recovery tests and the full local backend test suite, fixing regressions without weakening the new invariants.

## 5. Deploy and validate on Raspberry Pi hardware

- [x] 5.1 Update reconciliation and operations documentation with the topology activation phases, diagnostics, retry policy, and safe rollback behavior.
- [x] 5.2 Deploy the backend to the Pi and restart CamillaDSP, the decoder, the orchestrator, and relevant combinations against the active eight-channel graph; verify exact owned links, automatic audio recovery, and no sustained processor buffer warnings.
- [x] 5.3 Record convergence time, audible gap, warnings, CPU/thermal observations, and the corrected restart acceptance result in the hardware benchmark/deployment evidence.
