# Admin acceptance follow-up — 2026-08-29

Status: implemented and deployed; final owner UI and physical-audio acceptance remain open.

## Fresh-page performance correction

A browser trace against the Raspberry management UI showed that a fresh SSE
subscription replayed the complete retained transition history. The browser
processed thousands of events in repeated 0.8–1.0 second main-thread stalls.
The same backlog could delay the first graph-node selection even though the
graph inspector itself was fast.

Fresh subscriptions now start with one authoritative `initial-sync` snapshot
at the current event tail and then follow only new events. Explicit resume
cursors retain incremental replay and gap recovery semantics.

Measured in the same headless Chromium environment against the deployed Pi:

| Observation | Before | After |
| --- | ---: | ---: |
| Dashboard interactive after sign-in | 1.66 s plus recurring stalls | 0.82 s |
| Post-load event behavior | thousands of retained events | one snapshot |
| First graph-node selection | timing-dependent multi-second blockage possible | 0.13 s |
| Restored ordered-selector selection | not applicable | 0.11 s |

## Endpoint level correction

Endpoint mutation tokens previously contained the whole runtime world sequence,
so unrelated observations made an unchanged endpoint stale. The token now
tracks the selected runtime generation and node identity. A five-second delayed
write to the connected Main Speakers endpoint retained the same token, returned
success, and required no desired or audible level change.

## Restored adaptive graph

The retained pre-rollback database supplied the accepted 2026-08-26 graph and
device selectors. They were restored as a separate inactive published graph so
the current active graph and audio remain untouched:

- graph: `Adaptive TV, Bluetooth and headset routing`;
- input priority: active Bluetooth programme source, TV SPDIF input, then the
  managed debug input;
- processing: adaptive PCM/encoded decoder followed by output-specific
  CamillaDSP processing;
- output priority: Bluetooth headset, then Main Speakers;
- restored disconnected logical endpoints remain visible in Devices; and
- the graph is structurally valid and exposes Apply from the graph list and its
  published-revision editor.

The Raspberry readiness deployment completed with `ok=196`, `changed=14`, and
zero failures after the corrections.

## Structured endpoint-selector editing

The ordered, fallback, and exclusive endpoint selectors now expose direct
device candidates as structured Ant Design controls for device, priority,
eligibility policy, declaration order, addition, and removal. Recognized
availability and active-signal conditions remain structured; only arbitrary
conditions and dynamic tag/group endpoint selectors use an explicitly labelled
advanced JSON fallback.

The former variadic `candidates` graph socket was removed from these node types.
Endpoint selection is driven by the candidate policy in node configuration, and
the live applier supports only `audio` from a selected input endpoint and
`input` delivered to a selected output endpoint. Keeping a third socket implied
a candidate-path behavior that the resolver and live applier did not implement.

The admin lint, all 44 admin unit tests, production build, and 36 affected
backend routing/validation tests passed. The Pi serves the new
`index-lQ25Rst1.js` asset, its installed selector catalogue exposes only
`input` and `audio`, and the coordinated UI/readiness deployment completed with
`ok=156`, `changed=2`, and zero failures.
