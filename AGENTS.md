# Open Cinema agent guide

This file is the durable collaboration context for coding agents working on
Open Cinema. Read it before planning or editing. More specific `AGENTS.md`
files, when present in a subdirectory or adjacent repository, override this
guide for their scope.

## How to work with the project owner

- Lead with the outcome and keep progress updates short. The owner prefers
  implementation and evidence over long speculative plans.
- When the owner says “continue”, resume the current OpenSpec change or the
  clearly active implementation thread. Re-read its current status instead of
  restarting the design discussion.
- Make reasonable, reversible assumptions and proceed. Ask only when a choice
  would materially change the product, destroy data, or expand scope.
- Be explicit about blockers and failed criteria. Never make a benchmark,
  deployment, or release look green by weakening a condition after seeing the
  result.
- Work efficiently: use focused tests while iterating, inspect retained
  evidence before rerunning long hardware campaigns, and run the complete gate
  once when the implementation is stable.
- English is the working language. Prefer clear, direct explanations over
  jargon or excessive formatting.

## Product goal

Open Cinema is the control plane for a modular, highly configurable home
cinema/audio appliance, currently targeting a Raspberry Pi. It should make the
common case simple while retaining advanced graph composition:

- TV audio normally plays on the main speakers.
- A Bluetooth programme source can take over the main speakers.
- A connected headset has higher priority and receives all audio.
- Removing the headset automatically falls back without manually applying the
  graph again.
- Inputs, outputs, processors, fallback policy, and reusable graph fragments
  remain configurable from the end-user administration UI.

The system is intended to become an appliance, not merely a PipeWire debugging
tool. System status, updates, reboot/power controls, audio levels, device
management, graph editing, and diagnostics belong in a coherent end-user
experience.

## Architectural boundaries

### Open Cinema

Open Cinema owns:

- versioned desired audio graphs and parameterized reusable subgraphs;
- draft validation, publication, activation, disabling, and explanation;
- endpoint bindings and managed virtual-device definitions;
- processor definitions, profiles, and desired instance lifecycle;
- resolution of desired state against currently available runtime facts;
- continuous reconciliation, retry policy, diagnostics, and audit data;
- the versioned management API and appliance system API.

Keep these four states distinct:

1. **Draft** — mutable user intent; it may reference unavailable devices.
2. **Published revision** — immutable desired state.
3. **Resolved plan** — the explanation of what matches the current world.
4. **Applied/runtime state** — the actual owned PipeWire objects and actions.

Saving a draft must never change live audio. Apply is an observable transaction:
save, validate, publish, activate, and reconcile. Failure preserves the prior
active audio. A published graph can be applied directly, and an active graph
can be disabled/unapplied without first creating a draft.

### PipeWire, WirePlumber, and WyrePlumber

PipeWire is the real media graph. WirePlumber owns session and device lifecycle.
Open Cinema observes and mutates that runtime through the native Python
WyrePlumber binding.

Do not reintroduce an audio-backend plugin abstraction. WirePlumber integration
is intentionally a core dependency and the only audio-runtime backend.
Application and audio-processing extension points remain valid, but a plugin
must not create a competing PipeWire/session owner.

Do not reproduce WirePlumber’s policy engine inside Open Cinema. Open Cinema
stores user intent and higher-level policy; WirePlumber exposes the world and
performs native session operations. The resolver turns intent plus runtime
facts into a concrete plan.

### Processors are graph nodes, not endpoints

CamillaDSP and PCM Auto Decoder are processors inserted between logical inputs
and outputs. They are not discovered speakers or capture devices.

- **PCM Auto Decoder** accepts PCM or IEC-61937 input and exposes one stable
  adaptive PCM output. Format/layout changes update facts; they should not
  replace the logical processor node.
- **CamillaDSP 4** is native PipeWire. Open Cinema manages typed profiles and
  instances, while CamillaDSP owns real-time DSP execution.
- PipeWire does not launch these programs. The orchestrator starts and stops
  the required systemd instance services after resolving a desired graph and
  writes owned runtime configuration below `/run/open-cinema`.

Prefer one stable processor output and runtime format/layout metadata over
rewiring the desired graph for every movie/menu format change.

### Managed endpoint adapters

Managed ROC inputs/outputs and debug-file devices are user-configured virtual
endpoints. Debug playback loops its audio fixture; debug recording writes to an
explicit managed media root. Adapter processes, files, ownership, readiness,
and cleanup are part of runtime reconciliation. Do not require users to start
ROC or debug processes by hand.

## User-interface boundaries

The UI lives in the adjacent `open-cinema-ui` repository.

- `apps/admin` is the real end-user administration console for the whole
  appliance. It is not Django Admin.
- `apps/ui` is the future on-box/external-screen interface and is currently a
  separate, minimal application.
- Django Admin is not a product surface. Do not make users visit it to log in or
  manage Open Cinema.
- Use the existing Refine authentication/session/CSRF flow. The development
  account is `admin` / `admin`, but that credential must never be presented as
  production-safe.

Preserve and evolve the existing graph editor. Do not replace it with a generic
CRUD screen or a list-only interface. It already establishes important product
concepts:

- node-based graph editing and automatic layout;
- inputs, outputs, processors, routing/control nodes, and subgraphs;
- Save and Apply as separate actions;
- validation errors, apply progress, safe failure, and runtime explanation;
- Apply in graph-list actions and for published non-draft revisions;
- Disable/unapply for the active graph;
- device discovery showing connected and unavailable devices.

Before editing graph UI code, run or inspect the current editor. Preserve its
look and interaction model. Prefer the existing component system and layout
tokens; avoid custom CSS unless the existing system genuinely cannot express
the requirement. Do not casually redesign working screens.

UI additions should keep common tasks obvious and advanced state inspectable.
Show actionable explanations in user language; raw orchestration records remain
available for deeper diagnostics.

## Repository map and coordinated projects

Primary repository:

- `/home/edaniel/PyCharmProjects/open-cinema`
  - `core/orchestration/` — resolution, reconciliation, runtime projection.
  - `api/audio_v1/` — versioned audio-management API.
  - `api/system_v1/` — appliance observability and control API.
  - `contracts/` — packaged cross-project schemas/protocol data.
  - `deployment/` — Ansible deployment, rollback, readiness, benchmarks.
  - `docs/audio-orchestration/` — API and behavioral documentation.
  - `openspec/` — source specifications and active changes.

Adjacent repositories:

- `/home/edaniel/PyCharmProjects/wyreplumber` — native Python WirePlumber 0.5
  binding and orchestration contract.
- `/home/edaniel/WebStormProjects/open-cinema-ui` — npm workspace containing
  both web applications and shared DTO/client code.
- `/home/edaniel/RustroverProjects/pcm-auto-decoder` — Rust native-PipeWire
  PCM/IEC-61937 decoder.

When a coordinated change crosses a contract boundary, inspect all affected
repositories before editing. Keep API/schema changes synchronized with the
binding, UI shared types, decoder events, deployment manifests, and tests. Check
each repository’s worktree independently and preserve unrelated edits. Local
path dependencies are acceptable during development; coordinated releases use
immutable artifacts and manifests.

## API and persistence conventions

- Public audio APIs remain versioned below `/api/audio/v1`; system APIs remain
  below `/api/system/v1`.
- Browser mutation uses authenticated Django sessions and CSRF. Basic auth is
  only a convenient local/API probe.
- Keep schema, representation, endpoint behavior, API documentation, and UI
  DTOs in sync.
- Prefer typed resources and explicit lifecycle/status fields over opaque JSON
  when the concept is public and stable.
- Runtime observations are not desired configuration. Avoid persisting a live
  PipeWire identifier as though it were stable user intent.
- There are no external users yet, so backward compatibility with abandoned
  development data is not a product requirement. Keep migrations coherent for
  the current schema, but do not spend substantial effort migrating obsolete
  experimental rows unless requested.
- Never destroy the owner’s current database or graphs merely because legacy
  compatibility is unnecessary. Destructive reset still requires explicit
  scope and intent.

## Audio-runtime safety

- Native PipeWire only. PulseAudio compatibility commands and modules are
  legacy and must not be reintroduced into product or deployment paths.
- PipeWire and WirePlumber run as user services for the dedicated persistent
  audio identity. Django, the orchestrator, and processor instances are system
  services running as the same identity. A system-level `systemctl is-active
  pipewire` check is therefore misleading; use the deployment/runtime helpers
  or the correct user manager.
- Reconciliation owns only objects bearing Open Cinema ownership markers. Never
  delete or relink unrelated PipeWire objects.
- Every disruptive test must snapshot desired intent and service state, use
  bounded named targets, restore the previous graph, and verify exact topology
  plus state digests.
- Hardware experiments must leave the appliance usable. If a test fails, run
  the restoration guard before beginning another campaign.
- Treat listener reports as subjective unless a calibrated waveform capture
  measured them. Do not turn “about four seconds” or an audible click into a
  formal percentile.

## Supported fixture and evidence claims

The currently exercised appliance class is a Raspberry Pi 5 8 GB running
Debian 13/Trixie with a 27 W supply, active cooling, SPDIF-to-I2S input, WONDOM
GAB8 output, native PipeWire/WirePlumber, one decoder, and one CamillaDSP 4
instance at 48 kHz with a 128-frame DSP period.

This is a scope boundary, not permission to claim acceptance. Before making a
performance, release, latency, reliability, or supported-platform statement,
read:

- `deployment/SUPPORTED_PLATFORMS.md`;
- `deployment/benchmarks/README.md` and its linked result records;
- the current OpenSpec benchmark change/tasks;
- the relevant release-closure document and coordinated manifest.

Keep these classifications separate:

- imported functional evidence;
- exploratory/characterization evidence;
- acceptance against criteria frozen before the run.

Missing physical capture, a fixture-unavailable case, or a failed candidate
criterion remains visible. CPU headroom does not prove arbitrary graph or
multi-instance capacity.

Never copy private inventory values, LAN addresses, Bluetooth addresses,
hardware serials, credentials, rollback-capsule paths, or unrelated journal
content into committed evidence or chat output.

## OpenSpec workflow

Use OpenSpec for non-trivial features, architectural changes, deployment
campaigns, and acceptance work.

1. Identify the active change with `openspec list`/`status` rather than guessing.
2. Read every context file returned by `openspec instructions apply`.
3. Keep proposal, design, delta spec, and tasks coherent when implementation
   reveals a new decision.
4. Mark a task complete only when its stated evidence exists.
5. Strictly validate the change before commit.
6. Sync/archive only when requested and when required work is genuinely done.

Do not archive around a failed benchmark or missing hardware fixture. A task may
be complete with an explicit unsupported/unavailable result only when its spec
allows that outcome. Keep deployment/release work in a separate change from
local product/UI behavior when practical.

## Development and verification

Preferred backend setup and commands:

```bash
uv sync --frozen --extra dev
uv run python manage.py migrate
uv run python manage.py ensure_default_admin
uv run pytest -q path/to/focused_test.py
```

The existing `.venv/bin/pytest` is also valid when the synchronized environment
is already present. Do not repeatedly rebuild dependencies while iterating.

For a stable backend change, run the applicable final gates:

```bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
uv build
```

For deployment changes, at minimum run syntax checks from `deployment/`. Run an
idempotence apply against the private Pi inventory only when the task authorizes
hardware mutation and the appliance is available.

For `open-cinema-ui`, use its npm workspace scripts:

```bash
npm run type-check
npm run lint
npm test
npm run build
```

For WyrePlumber, use its `uv`/pytest gates. For PCM Auto Decoder, use `cargo
fmt --check`, `cargo test`, and `cargo clippy` as appropriate. Hardware success
does not replace unit, contract, packaging, or isolated-install tests.

Verification should be proportional:

- run the smallest focused test after each edit;
- add regression tests for discovered race, lifecycle, and contract failures;
- run the full relevant suite once before handoff/commit;
- do not rerun a ten-minute or multi-repetition campaign until the retained
  evidence explains why the prior attempt was invalid.

## Git, deployment, and release discipline

- The worktree is often shared by multiple chats and may already be dirty.
  Always inspect `git status` before editing.
- Existing modifications, staged entries, and untracked files belong to the
  owner or another active task. Do not reset, stash, delete, reformat, or include
  them in a commit.
- Stage/commit only files in the current task. If unrelated entries are already
  staged, use an isolated temporary index or another non-destructive method and
  verify their index blobs remain unchanged.
- Follow the current repository branch strategy and Conventional Commit style.
  Do not create tags, publish releases, modify immutable manifests, or push
  unless the task authorizes it.
- Development deployment may synchronize local repositories and is explicitly
  mutable. Release deployment consumes only verified immutable artifacts in a
  coordinated manifest.
- Ansible owns appliance installation and static service policy. Avoid manual Pi
  edits except for bounded diagnosis; encode lasting changes in roles/templates
  and prove the second apply is idempotent.
- Do not edit vendor PipeWire/WirePlumber unit files. Use the managed drop-ins
  and configuration fragments documented in `deployment/README.md`.
- Keep README, API docs, OpenSpec, deployment compatibility, changelog, and
  release metadata current for the part of the system changed.

## Definition of done

A task is ready to hand off when:

- behavior matches the desired-state/runtime ownership model;
- active audio is preserved or safely restored;
- API/UI/contracts and documentation agree;
- focused regression tests and the appropriate final gate pass;
- deployment changes are syntax-valid and, when exercised, idempotent;
- benchmark/release claims link to evidence and state their limitations;
- unrelated worktree changes remain untouched;
- the response states what changed, what was verified, and what remains blocked.

