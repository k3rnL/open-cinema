# Audio orchestration release compatibility contract

Open Cinema audio orchestration is a coordinated release across the backend,
WyrePlumber, the web UI, `pcm-auto-decoder`, and Ansible deployment. Git tags do
not need identical version numbers, but every artifact must implement the same
major contract set declared in
[`contracts/audio-orchestration-v1.yml`](../../contracts/audio-orchestration-v1.yml).

## Compatibility rules

- Missing version metadata or a major-version mismatch is incompatible.
- A newer minor version is accepted only when every advertised required field
  and capability is understood. Unknown optional fields are preserved or
  ignored according to that contract.
- Persistent desired state is never rewritten merely to make an older process
  start. A backend that encounters a future database or graph schema stops
  before making changes.
- Runtime and processor incompatibility leaves desired graph editing and
  diagnostics available, but reconciliation cannot activate the affected path.
- The UI performs an API/schema handshake before enabling audio controls; it
  must not infer compatibility from HTTP success alone.

## Contracts and detection points

| Contract | Producer → consumers | Detection before activation | Incompatible behavior |
| --- | --- | --- | --- |
| Persistent orchestration schema 1 | Backend → backend processes | Read the singleton marker during WSGI, ASGI, and orchestrator startup | Refuse startup read-only and request a compatible release |
| Desired graph document 1 | Backend → backend/UI | Validate `schemaVersion` on load, import, publication, and activation | Preserve data; reject publication/activation |
| `/api/audio/v1` | Backend → UI/deployment | UI and readiness probe fetch schema metadata | UI stays diagnostic; controls remain disabled |
| WyrePlumber runtime contract 1 / WirePlumber 0.5 | Binding → backend/deployment | Check import metadata, connection generation, and complete initial snapshot | Runtime unhealthy; reconciliation paused |
| Decoder status protocol 1 | Decoder → backend/deployment | Unix-socket status handshake before processor readiness | Decoder node incompatible; route waits or uses declared fallback |

During coordinated development, `uv` resolves the exact `wyreplumber==0.1.0`
requirement from the adjacent `../wyreplumber` working tree. That source has
passed the full contract suite against WirePlumber 0.5.8 and PipeWire 1.4.2.
The development path is deliberately not a deployment reference: a production
release must replace it with the immutable commit or released wheel built from
the same tested source.

## Activation sequence

1. Ansible validates the production platform and selected WirePlumber family.
2. Each backend process validates the persisted orchestration schema without
   writing it.
3. The orchestrator validates WyrePlumber's contract and obtains a coherent
   initial snapshot.
4. Every required processor completes its version/capability handshake.
5. The UI validates the HTTP and graph schema before offering controls.
6. Only then may a published desired graph pass the live-reconciliation feature
   gate and create an applied transition.

Each gate reports its observed and supported versions. Disabling a check is not
a compatibility mechanism; experimental platforms must still supply compatible
contracts and differ only in their support/acceptance status.

## Coordinated release record

The baseline commits for the first contract set are recorded in
[`implementation-notes.md`](../../openspec/changes/archive/2026-08-24-wireplumber-desired-graph-orchestration/implementation-notes.md).
Deployment pins the released component revisions and runs all handshakes before
making new reconciliation the default.
