# Shadow rollout acceptance — 2026-08-25

Status: **accepted for the experimental Raspberry Pi appliance**.

This acceptance covers rollout stage `shadow` only. Processor lifecycle and
live reconciliation remain disabled and unaccepted.

## Implementation gate

The orchestrator now has an explicit shadow execution path. It builds the same
immutable resolver inputs as live reconciliation, persists a shadow
`ResolvedPlan` and `ShadowResolutionComparison`, completes the guarded
generation, and publishes a zero-action plan event. The shadow resolver has no
driver adapter or action executor dependency.

The complete Open Cinema suite passed after this integration: **760 tests**.
Focused tests prove that shadow execution selects an optional live baseline,
persists no applied state or transition journal, exposes an empty driver-action
tuple, and never constructs the live reconciler.

## Active probe graph

The normal authenticated API created, published, and activated this experimental
desired state while the Pi was still in the accepted observation stage:

| Resource | Identifier |
| --- | --- |
| graph definition | `36eab3cd-9911-4793-8a98-6f7ba00d98b7` |
| published revision | `85942f6a-387c-4a8f-87a7-d51a6bcb611f` |
| unavailable programme-input endpoint | `3109662e-1f4e-4f09-aa86-3be1356be9e4` |
| Wondom main-output endpoint | `6ab84449-5f97-470a-b7ff-1b1c7835a824` |

The graph contains one endpoint route from a selector for
`node.name=opencinema.shadow-input` to Main Speakers. Observation mode saw the
new activation but retained zero plans, comparisons, applied states,
transitions, and PipeWire links.

## Deployed stage and decisions

The Pi was then deployed with API, runtime observation, and shadow resolution
enabled; processor management and live reconciliation remained disabled.
Activation versions 1 and 2 each scheduled and completed a shadow generation.
The second version was created through the normal API by changing the scene
bindings, without a playbook rerun.

| Desired version | Plan mode | Status | Plan digest |
| ---: | --- | --- | --- |
| 1 | `shadow` | `waiting` | `0f847a7afd2db3a91ddbbc726838a4e911058c7390d318544828982d3e6ddf83` |
| 2 | `shadow` | `waiting` | `c0f8987acf067d83cfa60a61313a5e872cd0aad2c6623feff9d3f8be1d7f3e83` |

Both plans used runtime generation 1 and sequence 2. The resolver matched the
Wondom output and reported `endpoint_no_match` for the deliberately absent
programme input. Each plan has a persisted comparison with no live baseline,
as expected before any live stage has produced a candidate plan.

The authenticated `/api/audio/v1/plans/current` response exposed the latest
shadow plan as `waiting`, included the endpoint explanation, and reported the
applied state as `idle` with no current plan.

## No-mutation proof

After both shadow generations:

| Mutation evidence | Count |
| --- | ---: |
| shadow plans | 2 |
| shadow comparisons | 2 |
| applied plan states | 0 |
| transition journals | 0 |
| managed CamillaDSP/decoder instances | 0 |
| PipeWire links | 0 |

The rollback remains the accepted `observation` stage. The appliance may not
advance to processor management until generated processor configuration and
owned-instance lifecycle are exercised without changing ordinary endpoint
routing.
