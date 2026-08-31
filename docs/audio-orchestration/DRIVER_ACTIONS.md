# Driver action contract

Reconciliation drivers receive immutable `DriverAction` values. An action is
not an arbitrary callback: it declares all information needed to fence, retry,
verify, explain, and recover a mutation.

Each action contains:

- a structured identity: driver, resource kind, durable resource identity, and
  operation;
- a typed command with detached JSON arguments;
- zero or more observed-state preconditions;
- a deterministic idempotency key derived from the identity, canonical command,
  and desired intent scope;
- a positive execution timeout;
- one or more postcondition verifications against fresh observed state;
- an explicit recovery policy: inverse, safe fallback, both in order, or a
  documented `none-required` choice for a non-mutating action;
- optional detached metadata for phase and explanation correlation.

Drivers report failures using exactly one of five classifications:

- `transient`: retrying the same idempotent action may succeed;
- `permanent`: the current command cannot succeed without changing intent or
  implementation;
- `stale-precondition`: discard the action and resolve against a fresh world;
- `dependency`: a required runtime or processor is unavailable and may recover;
- `safety`: keep suppression in place and follow the declared safe recovery.

Only transient and dependency failures are directly retryable. A stale
precondition schedules re-resolution. Safety failures explicitly block
unsuppression. Retry policy, phase ordering, journal persistence, and actual
driver adapters build on this contract in subsequent reconciliation tasks.

## Pure action diff

`build_reconciliation_action_plan` compares a resolved typed driver intent with
one immutable observed-state version. It evaluates each action's verification
assertions, records already-satisfied actions without scheduling them, and
orders remaining work through `prepare`, `suppress`, `configure`, `route`,
`verify`, `unsuppress`, then `cleanup`.

Cleanup is generated only for resources explicitly identified as Open
Cinema-owned and carrying a typed cleanup action. Unmanaged resources are
reported but never mutated. An owned obsolete resource without a cleanup action
becomes a diagnostic instead of prompting a guessed destructive operation. The
diff is pure and canonically digested, so equivalent input orderings produce the
same plan.

## Durable transition boundary

`TransitionJournalStore` commits an action's phase, complete typed command, and
idempotency key before handing control to an external driver. The observed
success or classified failure is committed immediately when the driver returns,
before another action may begin. Database transactions never contain driver or
runtime calls.

If the process disappears between those commits, startup recovery changes the
open entry from `started` to `uncertain` and reconstructs the immutable action.
The recovery directive requires checking its declared verification assertions
before any retry, preventing an uncertain successful mutation from being
blindly duplicated. Journals whose outcomes are all known resume from their
persisted phase; terminal completed journals are not recovered.

## Scheduling and mutation scopes

Runtime and desired-state bursts enter a bounded coalescing queue. It retains
only the newest pending generation per graph while combining a bounded list of
causes; an older generation cannot replace newer work. Distinct graph scopes
keep their first-arrival order so a busy graph cannot multiply queue entries.

Mutation leases lock the graph scope and every shared resource scope in stable
key order. This serializes actions for the same graph and shared processor while
allowing unrelated graphs to progress concurrently. Read-only diagnostics take
no mutation lease and remain available during transitions. Lock waits are
bounded and report the exact busy scopes.

## Idempotent execution

Immediately before an action, the executor obtains fresh facts and evaluates
its declared verification. An already-satisfied action is journaled as such and
never sent to the driver. A driver return is accepted only after another fresh
observation satisfies every postcondition.

An uncertain restart entry follows the same path. If its postconditions already
hold, the original attempt is closed without a second mutation. Otherwise the
same immutable action, including the identical idempotency key, is retried.
This contract lets processor creation, metadata updates, and managed-link
creation use ensure-style driver operations without duplicating resources.

## Failure handling and retry

Retry state is kept per action idempotency key. Transient and dependency
failures retry the identical action with bounded exponential jitter and a fixed
maximum attempt count; a driver retry hint may lengthen the wait but never pass
the configured cap. A successful result clears that action's budget.

The other classes do not enter that loop. Stale preconditions request a fresh
resolution, permanent failures stop until intent or implementation changes, and
safety failures retain suppression and select declared recovery. Exhausted and
shutdown-interrupted retries are separate terminal decisions, so neither can be
mistaken for a permanent configuration error.

## Suppression and release gate

Transitions build paired suppress/restore actions from each affected target's
declared capabilities and exact observed state. The preference order is an
input, so deployments may choose fade, mute, or pause without changing graph
semantics. Unknown prior state is rejected because it cannot produce a safe
inverse.

The restore action is released only through an unsuppression gate containing at
least one fresh runtime check and one fresh processor check. Missing or failed
checks keep suppression active. If restore itself cannot be verified, its
recovery policy applies the paired suppression command again.

## Rollback and degraded fallback

Failures in prepare, configure, route, or verify enter the action's declared
recovery policy. A verified inverse ends the journal as rolled back. If the
inverse fails, the executor can apply the action's safe fallback and then the
graph's explicit degraded-fallback actions. Every recovery action uses the same
observe-before-apply and post-verification rules as normal work and is recorded
in the journal.

There is no inferred fallback. If no declared recovery succeeds, the transition
ends with an explicit failure and its prior suppression state is not released.
A successfully applied degraded fallback is distinguished in the recovery
summary even though the original desired transition did not converge.

## Ownership and drift

Drift reconciliation separates Open Cinema-managed resources, declared movable
streams, and unmanaged runtime objects. Managed resources whose verification no
longer matches are restored with their ensure action. Unmanaged objects remain
visible in diagnostics but can never produce a mutation or deletion action.

Movable streams carry an explicit routing policy. `follow-default` clears a
per-stream target even when it currently happens to equal the default, so later
default changes still apply. `explicit-target` restores the declared target and
`observe-only` preserves external choice. This keeps ordinary WirePlumber
target/default behavior distinct from owned-resource convergence.

## Generation audit

Every finished reconciliation generation emits one structured durable audit
payload correlated to its graph and plan correlation ID. It records the trigger
and coalesced causes; desired revision, activation, world, resolved-plan,
transition, applied-plan, and final runtime versions; the resolver decision;
every action identity, idempotency key, attempt count, outcome, observation, and
classified failure; total and per-phase timing; and final convergence status.

Converged/superseded generations are informational, degraded/cancelled results
are warnings, and failed generations are errors. These bounded durable events
complement the detailed transition journal and ephemeral Redis progress stream.

## Integrated scenario coverage

Fake-driver scenarios exercise the complete safety boundaries: event storms
coalesce to one latest generation, stale generations stop before driver entry,
already-applied crash outcomes are verified without duplication, successful
actions converge in phase order, and a failure after partial progress journals
the failure before applying and verifying rollback. These tests run without
audio hardware and complement later WirePlumber/container acceptance tests.

## WirePlumber binding boundary

`WirePlumberDriverAdapter` checks the released orchestration contract, captures
one detached coherent snapshot before dispatch, and routes typed commands
through an explicit operation registry. It retains no native node, port,
metadata, link, profile, or route proxy and returns only detached binding
outcome documents.

Binding failure codes are translated once into reconciliation classes: stale
generation/identity requests re-resolve, stopped or unavailable runtime becomes
a dependency failure, ownership conflicts are safety failures, confirmation
timeouts are transient, and unsupported/read-only operations are permanent.

## Logical endpoint volume and mute

Volume and mute actions keep the durable logical endpoint ID as their action
identity while carrying the selected node's generation-scoped runtime key only
as an execution precondition. The adapter resolves that detached key against a
fresh coherent snapshot immediately before calling WyrePlumber, so PipeWire
numeric node IDs never enter desired state or survive a runtime generation.

Only nodes resolved by WirePlumber's mixer API can be controlled. The effective
mixer value takes precedence over raw node `Props`, because hardware endpoints
can expose writable-looking Props while their actual level lives on a device
route. Unsupported controls fail permanently for the current resolved plan
without changing the immutable desired action. A missing node or changed
runtime generation is stale instead, causing the orchestrator to resolve a
replacement candidate. Successful calls are accepted only after WyrePlumber
reports a confirmed effective mixer value; action verification then checks the
same value in a fresh orchestration observation.

The desired factors live outside graph revisions and temporary overrides. The
master record defaults to `1.0` and unmuted; each logical endpoint independently
defaults to `1.0` and unmuted. For an active output the requested runtime level
is `master × endpoint`, and either mute silences it. Inputs never inherit the
output master factor. This keeps a user's device trim stable while the active
route changes.

Level intent is part of convergence ordering and is applied before a route is
reported converged. The reconciler compares the desired effective value with a
fresh observation and skips an already-confirmed write. It reapplies after an
active-output change, Bluetooth or other endpoint recreation, runtime-generation
change, orchestrator restart, or later observed drift. A disconnected endpoint
keeps its preference without generating writes; ambiguity, stale identity, and
read-only capabilities become explicit pending or degraded evidence.

## Ordinary WirePlumber routing

Ordinary routes use configured default-node metadata and per-stream
`target.object` metadata. The action document identifies defaults by media
class, streams by a logical orchestration ID, and endpoints by logical endpoint
ID. Generation-scoped runtime keys are execution preconditions only; the
adapter resolves them to current nodes immediately before calling WyrePlumber.

Setting and clearing both default and stream targets are confirmed operations
with explicit inverses. Clear verification checks that the configured metadata
entry is actually absent, rather than merely checking for an unresolved target;
this preserves the distinction between a disconnected configured endpoint and
no configured preference. The action metadata explicitly records that no raw
links are involved. WirePlumber remains responsible for creating, moving, and
maintaining the resulting ordinary stream links.

## Endpoint profile and route selection

Profile and route actions carry the durable logical endpoint ID plus the stable
enumerated profile or route name. Their device ID and parameter index are never
persisted as action identity: the adapter resolves the name through the current
generation-scoped endpoint candidate and passes the matching detached binding
value back to WyrePlumber.

Every selection is fenced by the runtime generation. A missing endpoint or a
missing/ambiguous name is stale and triggers fresh resolution; a binding-level
unavailable profile or route remains a dependency failure. Success is checked
again through a fresh endpoint inventory fact proving the named profile or
route is active. The action declares the previously observed active selection
as its inverse, so an unknown prior configuration is rejected during planning
rather than guessed during recovery.

## Explicit managed links

Raw links are an explicit escape hatch limited to graph-owned routes that
target/default metadata cannot represent: direct source-endpoint to
sink-endpoint appliance bridges, `fan-out`, `mixer`, and `processor-internal`
shapes. Movable application streams cannot produce these actions and continue
to use target/default policy. The durable action identity is the planned link
ID; node and port numbers appear only inside generation-scoped runtime keys and
are resolved from a fresh snapshot immediately before creation.

Every created link uses the fixed `open-cinema.orchestrator` owner and carries
both `open-cinema.owner` and `open-cinema.desired-id` native tags through the
WyrePlumber managed-link contract. Postconditions verify the unique tagged link
and all four detached endpoints. Cleanup accepts only an observed link whose
owner fields and native tags agree. Missing ownership, duplicate identity,
forged owner, or an unmanaged identity collision is a safety failure and no
link is removed. The inverse of removal recreates only the exact previously
observed owned topology.

## Managed processor topology activation

A selected processor path is verified as one topology group even though
PipeWire creates its links individually. Planning records every required owned
link with its graph edge, channel, current runtime generation, four exact
node/port endpoints, and whether it is programme ingress. A processor node is
not runtime-ready until its complete profile-declared capture/playback port set
is present; observing only the node identity is insufficient.

When the group requires mutation, existing graph-owned ingress is removed or
withheld first. Links are then created from the output backwards through the
processor chain. Before any source-facing ingress action runs, a fresh coherent
snapshot must contain the entire downstream owned-link set. A second fresh
snapshot must contain the complete topology after ingress, and processor
control/status health must also pass, before the applied plan becomes
`converged`.

Missing, duplicate, endpoint-mismatched, and stale-generation links are
reported separately in `processor-topology-transition` events and applied-plan
failure evidence. Failure keeps ingress suppressed and removes only desired
processor links belonging to the failed graph transition; unmanaged links and
other graphs are never adopted or removed. This is the audible transaction
boundary used where the runtime cannot provide one atomic multi-link commit.

Link mutations may themselves advance the runtime repeatedly. The orchestrator
performs a bounded number of immediate catch-up passes, then installs a delayed
deadline in its single-controller event loop. That deadline shortens the next
event wait and retries from the newest authoritative snapshot even if no later
WirePlumber event arrives. Successful catch-up clears the bounded backoff.

## WirePlumber reconciliation integration coverage

The application-level contract integration suite drives detached snapshots
through the real adapter action builders and operation registry, with a mutable
binding fake below that released boundary. It verifies headset arrival moves
the configured default and removal restores the main output; Bluetooth source
arrival retargets only the managed decoder capture stream; logical volume and
mute actions converge through fresh observations; and a PipeWire generation
restart rejects the old action before any call, then accepts a newly resolved
runtime key.

An unrelated external playback stream and its unmanaged session link remain
present and unowned throughout the default and target transitions. These tests
complement WyrePlumber's native real-policy integration tests: the binding owns
native event-loop and PipeWire behavior, while this suite proves Open Cinema's
logical identities, generation fences, action verification, and ownership
boundary against that detached contract.
