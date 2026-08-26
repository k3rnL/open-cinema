# Coordinated release inventory and safety boundary

Date: 2026-08-26 UTC

Scope: release-preparation tasks 1.1–1.6 and corrective publication for Open Cinema `0.3.1`,
WyrePlumber `0.2.0`, PCM Auto Decoder `0.2.2`, and Open Cinema UI `2.0.0`.
This is evidence only: no index entry, commit, branch, tag, release, or remote
reference was changed while collecting it.

## Outcome

The four public repositories and their existing `v<version>` release paths are
real and the authenticated GitHub identity has admin/push authority for each
repository. All four default branches are `master`, but the candidate work is
not yet on an accepted integration commit and none of the `master` branches is
protected by required status checks. CI success therefore remains a manual
promotion gate rather than a GitHub-enforced branch rule.

The historical tuple `0.2.0 / 0.1.0 / 0.1.4 / 1.0.5` is still downloadable and
all published checksum records validate. It is **not** a usable immutable
rollback tuple for the current native PipeWire appliance: the Open Cinema tag
contains a package identified as `0.0.1`, the WyrePlumber AArch64 wheel links
WirePlumber 0.4, and the decoder AArch64 binary links PulseAudio. No published
coordinated manifest exists for that tuple.

The only demonstrated rollback baseline is the appliance-local transition
bundle documented in
`deployment/acceptance/2026-08-26-coordinated-rollback.md`. Its embedded
manifest and nine checksummed recovery artifacts successfully restored the
previous generation. That private bundle is suitable as the first coordinated
release's operational fallback only if its live presence and checksums are
reverified and it is retained; it is not a substitute for a downloadable
previous coordinated release manifest.

During publication, decoder `v0.2.0` was created once at
`aa94345fa2db1c6b9a5f89ea9eb1e23da187eb5d`, but both packaging jobs failed
before release creation because Git rejected the container-owned checkout as
unsafe. No release assets were published. The tag is retained and is not moved
or reused. Corrective `v0.2.1` then published artifacts, but its AArch64
post-download job failed because the minimum-runtime verification image omitted
`libavformat61`; the same published AArch64 bytes passed digest, version, and
native-linkage execution on the target Pi. That tag is also retained and
rejected. The corrected decoder target is `0.2.2` / `v0.2.2`.

## Collection method and safety checks

- Repository state came from `git status --short --untracked-files=all`, branch,
  upstream, tag, log, index, and remote-reference queries. Status counts below
  are a point-in-time snapshot and include this evidence file.
- Public release metadata and assets came from read-only GitHub API/CLI calls.
  Previous assets were downloaded to a temporary directory and their published
  checksum files were verified. No token, credential, or tokenized URL is
  recorded here.
- Dirty filenames and text files were scanned for common private-key, GitHub
  token, AWS access-key, and credential-bearing URL patterns. No match was
  found. Binary UI screenshots were identified as generated review evidence;
  they still require a visual privacy review before staging.
- The tracked development inventory contains machine-specific LAN addresses,
  usernames, and absolute source paths and is excluded below. Shared inventory
  contains deliberately documented bootstrap placeholders, not discovered live
  secrets; their literal values are not repeated here.
- No blanket staging, reset, checkout, history rewrite, or cleanup is permitted.
  Two pre-existing index states need explicit resolution: three Open Cinema
  `plugin/pipewire/**` files are staged additions but absent from the worktree
  (`AD`), and WyrePlumber's `oui.py` is staged as an addition.

## Repository identity snapshot

| Repository | Local branch and HEAD | Upstream / divergence | Remote integration state | Latest tag |
|---|---|---|---|---|
| Open Cinema | `pipewire` at `4a2ec1a3476e612977ec11e2408d3b85e2cb8ba4` | no upstream; local `master` is the same commit and is 4 commits ahead of its locally recorded `origin/master` | GitHub default `master`; live remote `master` is `b22569c00b1c21cf5fb063a650c9bd1be9a546f4`; no live `pipewire` branch | `v0.2.0` at `1f8ac45c2502c6eb2fafeada736e6da884e9ae1a` |
| WyrePlumber | `pipewire-object-refactor` at `e58456fd9b1f94b778b39f5529ba10d16bdc68c3` | `origin/pipewire-object-refactor`, `0/0` | GitHub default `master` at `51c0cd195ab464601e85df5fd98a9fcf12c363bf`; feature branch exists remotely | `v0.1.0` at `97cc4f07b3d52e5afab12af1088c0aa9a3a95af6` |
| PCM Auto Decoder | `master` at `e1be22be3759dd67b0a3bd21384eaab33f87c2c2` | `origin/master`, `0/0` | GitHub default/live `master` is the same commit | `v0.1.4` at the same commit |
| Open Cinema UI | `master` at `a1933d5eccc63f7c9f811424cca5dc167967a0da` | `origin/master`, `0/0` | GitHub default/live `master` is the same commit | `v1.0.5` at `614dfb5bd058b8b9f9a3c41d8f37f68daf56d92f` |

All remotes resolve to the public GitHub repositories under `k3rnL` (the
decoder's existing references vary only in owner-name case, which GitHub treats
case-insensitively). Fetch and push URLs identify the same repositories. GitHub
reports `admin`, `maintain`, `push`, `triage`, and `pull` permission for the
authenticated identity. There is no prior pull-request history in any of the
four repositories and no protection on any `master` branch; prior history is
consistent with direct conventional commits followed by `v*` tags.

## Complete dirty-path classification

The tables use disjoint path sets. Counts are Git status entries, not filesystem
file counts. A directory pattern accounts for every dirty descendant matched
by that set; exclusions are stated explicitly. `M`, `D`, `A`, `AD`, and `??`
retain their normal Git meanings.

### Open Cinema

Snapshot at `2026-08-26T19:35:14Z`: 607 status entries (`M` 41, `D` 96,
`AD` 3, `??` 467), status-stream SHA-256
`b3deb68f92e8a4b49d697281a2612dea5195de07b790886eec6b8d0450707f82`.
The disjoint classifications contain 406 intended-product, 171
release/deployment-readiness, 22 generated-evidence, 1 machine-local, and 7
deferred entries.

Top-level accounting is: root 10, `.devcontainer` 11, `.github` 4, `api` 97,
`contracts` 5, `core` 113, `deployment` 109, `docs` 18, `opencinema` 5,
`openspec` 72, `plugin` 29, `scripts` 3, and `tests` 131. The largest groups
break down as follows: `api` = admin 1, apps 1, `audio_v1` 16, auth 1,
management 7, migrations 16, models 31, permissions 2, tasks 4, URLs 1, and
views 17; `core` = legacy audio 13, legacy Camilla 6, orchestration 89, and
plugin system 5; `tests` = factories 2, fixtures 8, and 121 top-level test
modules; `plugin` = ALSA 4, counter 3, PCM decoder 7, staged PipeWire 3, and
PulseAudio 12. `deployment` = root/readme/platform/config/manifest files 5,
acceptance 17, audit 1, benchmark definitions 10, benchmark results 4,
collections 1, filter plugins 1, inventories 2, playbooks 4, roles 62, and
scripts 2. `openspec` = archived completed changes 40, approved active changes
16, deferred proposals 4, main specs 11, and configuration 1.

| Classification | Complete disjoint path inventory | Treatment |
|---|---|---|
| Intended product work | `.devcontainer/**`; `api/**`; `contracts/**`; `core/**`; `docs/audio-orchestration/**`; `opencinema/**`; `plugin/**` except `plugin/pipewire/**`; `tests/**`; deleted `api_tests.http` | Include through small implementation/test commits. The legacy model/backend/plugin deletions must stay coherent with migrations and replacement orchestration code. |
| Release/deployment readiness | `.github/**`; `deployment/**` except the generated-evidence and local-inventory sets below; `openspec/**` except the four deferred proposal files below; `scripts/**`; `docs/release-readiness/2026-08-26-coordinated-release-inventory.md`; root `LICENSE`, `MANIFEST.in`, `README.md`, `VERSION`, `pyproject.toml`, `requirements-dev.txt`, `requirements.txt`, `uv.lock`, and `version.py` | Include in deployment, documentation/spec, and release-infrastructure commits, not in the application implementation commit. |
| Generated/observed evidence | `deployment/acceptance/**`; `deployment/audits/**`; `deployment/benchmarks/results/**` | Retain as reviewable evidence after privacy/sanitization review; do not confuse these observations with source or release artifacts. |
| Machine-local state | `deployment/inventories/local.yml` | Exclude from release commits. It identifies this workstation, LAN, Pi login, and adjacent worktrees. Preserve in place. |
| Explicitly deferred user work | staged-but-worktree-deleted `plugin/pipewire/__init__.py`, `plugin/pipewire/audio/__init__.py`, `plugin/pipewire/audio/backend.py`; `openspec/changes/additional-managed-link-shapes/{.openspec.yaml,proposal.md}`; `openspec/changes/multi-instance-audio-processing/{.openspec.yaml,proposal.md}` | Do not stage with the release. Resolve the stale index entries explicitly after review; preserve both future-change proposals untouched. |
| Secret-sensitive material | none detected | Re-run the scan against the staged diff immediately before each commit. |

The large source inventory is completely covered by these current subtrees:
`.devcontainer`, `.github`, `api`, `contracts`, `core`, `deployment`, `docs`,
`opencinema`, `openspec`, `plugin`, `scripts`, `tests`, and the ten root-level
status entries named above (nine release files plus `api_tests.http`). No dirty
path falls outside those sets.

#### Release-candidate inclusion recheck

The final pre-commit recheck at `2026-08-26T22:16:22Z` contains 98 status
entries (`M` 41, staged `D` 1, `AD` 3, and `??` 53), with status-stream
SHA-256 `8e85111fe5f07713daf1ac8c47b31919591d2efeaa17bf6dd975a275126c2457`.
Ninety-one entries are release-owned and seven remain explicitly deferred.

New release-owned paths since the initial inventory are the benchmark runner,
intent adapter, workload driver, waveform analyzer, deterministic media and
CamillaDSP fixtures under `deployment/benchmarks/`; the benchmark command
template; `deployment/development-manifest.yml`; the privacy-safe rollback
receipt and documentation; private-capsule verifier and shared rollback
preflight task; and their six focused test modules. The generated audio files
are checksummed deterministic test fixtures covered by the media manifest, not
observed appliance recordings or disposable build output.

The staged deletion of `deployment/inventories/local.yml` is intentional: it
removes machine-private content from Git while the ignored file remains present
on the controller. The three staged-but-worktree-deleted `plugin/pipewire/**`
entries and both two-file future OpenSpec proposals remain untouched and are
the seven deferred entries. No private-key, GitHub-token, or AWS-key marker was
found in the release-owned paths. The private rollback capsule and its
controller path remain outside Git; only its privacy-safe content-addressed
receipt is included.

The remaining release-owned work uses
`feat(benchmark): harden Raspberry audio evidence collection` for the bounded
benchmark contract/harness/fixtures/tests and
`build(release): prepare coordinated 0.3.0 publication` for rollback hardening,
manifest validation/finalization, workflows, version/lock data, deployment and
release documentation, and OpenSpec state. Narrow housekeeping commits untrack
the private inventory and normalize fixture endings. Every commit uses explicit
pathspecs so the seven deferred entries cannot enter it.

### WyrePlumber

Snapshot at `2026-08-26T19:35:14Z`: 95 status entries (`M` 28, staged `A` 1,
`??` 66), status-stream SHA-256
`476801e737c1affbb7b3e1c6a8f1123348eb818e6d23b59d3198208dffea2610`.
The disjoint classifications contain 65 intended-product, 11
release-readiness, 6 machine-local, and 13 deferred entries.

| Classification | Complete disjoint path inventory | Treatment |
|---|---|---|
| Intended product work | `CMakeLists.txt`, `setup.py`, all `native/**`, all `src/wyreplumber/**` except `py.typed`, all `tests/**` except `tests/pipewire_container/Dockerfile` and `tests/test_release_tools.py`, `docs/runtime-contract-v1.md`, `examples/runtime_orchestration.py`, and all `openspec/**` | Include as native proxy/SPA work and the new runtime observation/control contract with its tests. |
| Release readiness | `.github/workflows/release.yml`, `MANIFEST.in`, `README.md`, `pyproject.toml`, `uv.lock`, `docs/release-readiness/2026-08-26-wireplumber-0.5.md`, `scripts/__init__.py`, `scripts/release_contract.py`, `src/wyreplumber/py.typed`, `tests/pipewire_container/Dockerfile`, `tests/test_release_tools.py` | Include in a separate WirePlumber-0.5 packaging/CI commit. |
| Machine-local state | all six `.codex/skills/**/SKILL.md` files | Exclude; these are local agent workflow copies, not binding source. |
| Explicitly deferred user work | already-staged `oui.py`; `BEAUTIFUL_API_DEMO.md`, `EXAMPLE_SPA_PARSING.md`, `PARAM_USAGE_EXAMPLES.md`, `demo_new_api.py`, `example_beautiful_api.py`, `example_param_usage.py`, `test.py`, `test2.py`, `test3.py`, `test4.py`, `test_set_python_values.py`, `test_spa_types.py` | Preserve and exclude unless the user separately promotes an experiment into the supported examples/API. Do not alter the existing index entry silently. |
| Generated output / secret-sensitive material | none detected | Recheck before staging. |

### PCM Auto Decoder

Snapshot at `2026-08-26T19:35:14Z`: 29 status entries (`M` 10, `D` 2, `??`
17), status-stream SHA-256
`68397f6c0e18ccb3d77cb0bee774802df0be09e90833485a0c49767c88e789af`.
The disjoint classifications contain 14 intended-product and 15
release-readiness entries.

| Classification | Complete disjoint path inventory | Treatment |
|---|---|---|
| Intended product work | all seven `src/**` entries; all six `tests/**` entries, including deletion of `tests/pulseaudio_test.rs`; `docs/STATUS_PROTOCOL.md` | Include as the stable adaptive native PipeWire output/status-v2 implementation and tests. |
| Release readiness | all three `.devcontainer/**` entries; both `.github/workflows/**` entries; `Cargo.toml`, `Cargo.lock`, `README.md`, `rust-toolchain.toml`; all six `scripts/**` entries | Include as Trixie native build, validation, packaging, and release infrastructure. |
| Generated output / machine-local state / secret-sensitive material / deferred work | none detected | Recheck before staging. |

### Open Cinema UI

Snapshot at `2026-08-26T19:35:14Z`: 102 status entries (`M` 18, `D` 27,
`??` 57), status-stream SHA-256
`762dd314b4169a0f0c0d3b6c18ea751eb35a4afed73364bd30697b82bd7a032e`.
The disjoint status classifications contain 71 intended-product, 22
release-readiness, and 9 generated-evidence entries. Five `.idea/**` paths are
now ignored machine-local state and therefore intentionally sit outside the
102-entry Git status total.

| Classification | Complete disjoint path inventory | Treatment |
|---|---|---|
| Intended product work | all `apps/**` except the seven release/build surfaces below; all `packages/**` except `packages/shared/package.json`; `contracts/audio-orchestration-client-v1.json`; `e2e/orchestration.spec.ts`; root `eslint.config.js` and `playwright.config.ts`; `docs/AUDIO_ORCHESTRATION_UI.md`, `docs/UI_BASELINE.md`, and `docs/ui-current/README.md` | Include as admin/orchestration, shared client contract, on-box placeholder, and product-test commits. The user has accepted this UI as a release base while deferring later UX details. |
| Release readiness | `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.gitignore`, `README.md`, `package.json`, `package-lock.json`, all seven `scripts/**` files, `apps/admin/{index.html,package.json,vite.config.ts}`, `apps/ui/{index.html,package.json,tsconfig.json,vite.config.ts}`, `packages/shared/package.json`, `docs/SECURITY_AUDIT.md` | Include as deterministic workspace versioning, hard CI gates, build identity, audit evidence, and verified release packaging. |
| Generated review evidence | all five `docs/ui-baseline/*.png` and all four `docs/ui-current/*.png` files | Include only after a visual privacy review; dimensions were inspected and no filesystem metadata is needed by the release. |
| Machine-local state | five ignored paths under `.idea/**` (inspection profile directory, module metadata, project module, VCS settings, and workspace state) | Exclude and preserve; IDE project state is not release input or part of the status total. |
| Secret-sensitive material / explicitly deferred user work | none detected beyond the machine-local and generated-review sets | Recheck before staging. |

## Proposed selective conventional commits

These are staging boundaries, not commands. Files shared by two concerns require
interactive hunk review. Every commit starts from an explicit path list and an
inspection of `git diff --cached`; never use `git add .`, `git add -A`, reset,
or a history rewrite.

### Open Cinema

1. `feat(orchestration): add versioned desired graph control plane` — graph
   models/migrations, contracts, resolver/planner/runtime, API representations,
   orchestrator, and focused tests.
2. `feat(audio): manage endpoint adapters and processing stages` — endpoint
   inventory/adapters, CamillaDSP, adaptive decoder, speaker tester, driver and
   reconciliation paths, with their API/tests.
3. `refactor(audio): remove legacy backend and plugin models` — legacy
   audio/Camilla backend deletions, final removal migration, route/plugin
   cleanup, and removal tests. Keep this ordered after the replacement commits.
4. `feat(deployment): provision the native PipeWire appliance` — shared
   inventory, roles, templates, full-runtime playbook, readiness, and deployment
   tests; explicitly omit `deployment/inventories/local.yml`.
5. `feat(deployment): add coordinated recovery and benchmark tooling` — backup,
   rollback, diagnostics, benchmark definitions/harness, and separately reviewed
   acceptance/measurement evidence.
6. `docs(openspec): record audio orchestration and appliance contracts` —
   current docs, main specs, archived completed changes, and active approved
   deployment/benchmark/release plans; omit the two deferred future proposals.
7. `build(release): harden backend distributions and coordinated manifest` —
   version/package inputs, lock data, license, CI/tag workflows, release scripts,
   README release sections, and this inventory.

### WyrePlumber

1. `refactor(native): complete proxy and SPA value support` — existing proxy,
   metadata/module/node and SPA-pod work with focused tests.
2. `feat(runtime): add immutable orchestration observation and controls` — new
   native capture/event/lifecycle/mutation code, `src/wyreplumber/runtime/**`,
   contract docs/example/OpenSpec, and runtime tests.
3. `build(release): publish WirePlumber 0.5 native artifacts` — build metadata,
   typed marker, Trixie fixture, release contract, workflow, README, and evidence.
4. Exclude `.codex/**`, staged `oui.py`, and all named scratch/demo files unless
   the user makes an explicit separate decision.

### PCM Auto Decoder

1. `feat(pipewire): add one stable adaptive PCM output` — native I/O,
   detection/decoder/status implementation, status contract, fixture/live tests,
   and Pulse client/test removal.
2. `build(ci): standardize native Debian Trixie gates` — devcontainer,
   toolchain, CI gates, linkage/offline checks, and branch workflow.
3. `build(release): publish verified target-qualified decoder archives` —
   version surfaces, locked metadata, packaging/verifiers, tag workflow, and
   release documentation.

### Open Cinema UI

1. `feat(admin): add authenticated orchestration management` — authentication,
   dashboard/device discovery, graph editor, processors/adapters/speaker testing,
   legacy page replacement, and component tests.
2. `feat(shared): add the audio orchestration client contract` — versioned
   client contract, API/state/rule/validation modules, legacy shared API removal,
   and shared tests.
3. `feat(on-box): retain the independent on-box placeholder` — on-box app
   configuration and its boot test.
4. `test(ui): preserve visual and browser acceptance baselines` — E2E contract,
   Playwright configuration, reviewed screenshots, and baseline documentation.
5. `build(release): make UI 2.0 gates and assets deterministic` — manifests and
   lockfile, version/release scripts, runtime build metadata, CI/release
   workflows, lint configuration, and README. Exclude `.idea/**`.

## Integration, CI, tags, assets, and authority

| Project | Integration decision before tagging | Candidate branch/PR CI | Tag release gate and assets | Authority result |
|---|---|---|---|---|
| Open Cinema | Development is on local `pipewire`, while GitHub integration is `master`. The accepted release SHA must become reachable from `master`; do not tag the unpushed local branch. | New local `ci.yml` covers backend tests, Django/migrations, distributions, isolated install and Ansible syntax on pushes to `master`/`pipewire` and PRs. It is not authoritative until committed and run remotely. | `v*`; local candidate release calls equivalent CI, builds wheel+sdist, verifies tag/package/contracts/license, and publishes checksums, provenance, and finalized coordinated manifest. | GitHub admin/push confirmed; no protected status checks, so record successful run IDs manually. |
| WyrePlumber | Merge the remote `pipewire-object-refactor` candidate into default `master` after its all-branch workflow passes. | The combined candidate workflow runs on every branch/PR and builds/tests the WirePlumber-0.5 matrix. | `v*`; six target wheels plus one sdist, each with checksum/provenance, only after installed-wheel tests. | GitHub admin/push confirmed; no protected status checks. |
| PCM Auto Decoder | Current integration branch is `master`; commit only after native local gates. | New local CI runs locked native Trixie x86_64/AArch64 gates on all branches/PRs. | `v*`; repeats native gates, publishes two target-qualified archives/checksums/provenance, then verifies published bytes. | GitHub admin/push confirmed; no protected status checks. |
| Open Cinema UI | Current integration branch is `master`; commit only after audit/type/lint/unit/build/E2E gates. | Candidate CI makes installation, audit, type checks, lint, tests, both builds, version metadata, and bounded browser smoke hard failures. | `v*`; rejects tag mismatch, repeats gates, publishes separate admin/on-box archives with checksum/provenance, and verifies downloaded served builds. | GitHub admin/push confirmed; no protected status checks. |

All repositories use conventional-style history (`feat:`, `fix:`, `refactor:`,
`docs:`, `ci:`, `chore:`) and `v<project-version>` tags. Existing release notes
are generated with `git-cliff`. No push or tag should occur until the candidate
workflow files themselves are committed, the target integration SHA is known,
and the corresponding branch run is green.

## Version, dependency, contract, ABI, asset, and README surfaces

| Project | Current source-of-truth surfaces | Required release state |
|---|---|---|
| Open Cinema | `opencinema/version.py` originally reported `0.2.0`; `pyproject.toml` derives package metadata from it; `/api/version` imports it. `pyproject.toml` and `uv.lock` originally resolved WyrePlumber `0.1.0` through an adjacent editable development source. Shared inventory and the development manifest also identified Open Cinema `0.2.0`. | Set all backend/package/deployment surfaces to corrective `0.3.1`/`v0.3.1`; retain failed `v0.3.0` without reuse; consume verified WyrePlumber `0.2.0` in release mode while keeping the adjacent path only as an explicit development override. README now accurately describes native PipeWire/WirePlumber, processor ownership, admin/on-box roles, Trixie appliance, validation, immutable deployment, and tag flow. |
| WyrePlumber | `pyproject.toml` is `0.1.0`; installed `__version__` comes from package metadata. Build family is selected in `setup.py`/CMake, with candidate release workflow fixed to WirePlumber 0.5. Public native surfaces include `_core`, `_core.pyi`, `py.typed`, and runtime contract/value schema v1. | Set metadata/lock to `0.2.0` and tag `v0.2.0`; ship CPython 3.12/3.13/3.14 wheels for x86_64/AArch64 linked to `libwireplumber-0.5` and `libpipewire-0.3`. README's GitHub-release installation, no-PyPI statement, Trixie matrix, permission/runtime ownership, validation, and release claims match the candidate workflow. |
| PCM Auto Decoder | `Cargo.toml` and `Cargo.lock` started at `0.1.4`; Clap derives `--version` from Cargo metadata. `rust-toolchain.toml` pins 1.98.0 while package MSRV is 1.85. Status protocol is v2 and the one-output contract is implemented through native PipeWire 0.10 and system FFmpeg 8 crates/libraries. | Set Cargo/lock/binary/archive/title surfaces to corrective `0.2.2`/`v0.2.2`; retain failed `v0.2.0` and published-but-rejected `v0.2.1`, and publish native Debian Trixie x86_64/AArch64 archives linked to PipeWire/FFmpeg and forbidden from linking libpulse. README's stable output, codecs/layouts, ownership, offline fixture, dependencies, validation, asset, and immutable-tag claims match the candidate. |
| Open Cinema UI | Root, admin, on-box, shared manifests and corresponding lock entries are `1.0.5`; both internal shared dependencies are pinned to that version. Vite emits HTML and `open-cinema-release.json` identity and embeds the v1 client contract in admin. | Deterministically set every workspace/lock/runtime surface to `2.0.0` and tag `v2.0.0`. README correctly distinguishes the administration console from the on-box placeholder and documents environment, all hard gates, separate assets, workspace versioning, and immutable tag flow. The local release example must be updated or intentionally expressed as a version placeholder during the bump. |

The coordinated manifest contracts currently inventoried are:

- API `/api/audio/v1`; orchestration schema 1; desired graph schema 1; UI DTO
  schema 1; processing plugin and driver contracts 1.
- WyrePlumber orchestration contract 1, runtime value schema 1, WirePlumber ABI
  family 0.5, PipeWire ABI 0.3.
- Decoder status protocol 2 and one stable adaptive native-PipeWire PCM output.
- Debian 13/Trixie AArch64 appliance target, Python 3.13, PipeWire
  `>=1.4,<2`, WirePlumber `>=0.5.8,<0.6`, CamillaDSP 4.1.3 native PipeWire,
  and pycamilladsp 4.0.0.

The previously identified compatibility blockers are corrected:
`deployment/compatibility.yml` now requires WyrePlumber `>=0.2.0,<0.3.0` and
PCM Auto Decoder `>=0.2.2,<0.3.0`, and the manifest validator enforces those
ranges. Mutable local identities now live only in the explicitly selected
`deployment/development-manifest.yml`; the local inventory points to that file
in development mode. `deployment/release-manifest.yml` is reserved for the
immutable candidate and must contain the verified public asset identities
before the Open Cinema tag is created.

### Expected coordinated release matrix

| Component | Version/tag | Required published assets and target identity |
|---|---|---|
| Open Cinema | `0.3.1` / `v0.3.1` | `open_cinema-0.3.1-py3-none-any.whl`, `open_cinema-0.3.1.tar.gz`, the republished pinned `camilladsp-4.0.0-py3-none-any.whl`, `provenance.json`, `pycamilladsp-provenance.json`, `camilladsp-provenance.json`, `open-cinema-coordinated-manifest.yml`, and `checksums.sha256`. |
| WyrePlumber | `0.2.0` / `v0.2.0` | `wyreplumber-0.2.0.tar.gz` and six wheels `wyreplumber-0.2.0-cp{312,313,314}-cp{312,313,314}-linux_{x86_64,aarch64}.whl`; every primary artifact has adjacent `.sha256` and `.provenance.json`. Appliance selector: `cp313` + `aarch64` + Debian Trixie + WirePlumber 0.5. |
| PCM Auto Decoder | `0.2.2` / `v0.2.2` | `pcm-auto-decoder-v0.2.2-debian-trixie-{x86_64-unknown-linux-gnu,aarch64-unknown-linux-gnu}.tar.gz`, each with `.sha256` and `.provenance.json`. Appliance selector: AArch64. |
| Open Cinema UI | `2.0.0` / `v2.0.0` | `open-cinema-admin-v2.0.0.tar.gz`, `open-cinema-ui-v2.0.0.tar.gz`, one provenance JSON adjacent to each archive, and `checksums.sha256` covering both archives and both provenance files. |
| CamillaDSP (external retained pin) | `4.1.3` / `v4.1.3` | `camilladsp-linux-pipewire-aarch64.tar.gz`, existing pinned SHA-256 `ca8b6cc32bda29bd7cb38f7bcda5fcc6f5e69690b3d0efaa23b6c3c05c45696c`. |

The finalized Open Cinema manifest must add repository, exact tag/commit,
immutable URL, size, SHA-256, target selector, and portable provenance for every
component and point to a verified previous/replacement manifest. No editable
path, branch, dirty-tree parent revision, mutable `latest` URL, or unverified
adjacent worktree is permitted.

## Rejected Open Cinema release attempt

- Lightweight tag `v0.3.0` remains fixed at
  `c79db4ef612696d8e25daae1e56476da446f50d7`; branch run
  `https://github.com/k3rnL/open-cinema/actions/runs/33019903034` and `master`
  run `https://github.com/k3rnL/open-cinema/actions/runs/33020044441` both passed.
- Tag workflow `https://github.com/k3rnL/open-cinema/actions/runs/33020200718`
  passed the complete release-commit gate, built the Open Cinema,
  pyCamillaDSP, CamillaDSP, UI, and decoder inputs, and then stopped before
  upload because the release-only manifest finalizer interpreter lacked
  PyYAML.
- No `v0.3.0` GitHub release or release assets were created. The tag is not
  moved or reused. Corrective `v0.3.1` pins PyYAML 6.0.3 as release tooling and
  adds a regression assertion that it is installed before manifest
  finalization.

## Accepted dependency release evidence

### WyrePlumber `v0.2.0`

- Accepted immutable release and lightweight tag: `v0.2.0`, commit
  `9d55ab1200ee7c484743fe57339a1f56d2c9fcd1`; the tag, remote `master`, and
  release target agree.
- Candidate matrix gate:
  `https://github.com/k3rnL/wyreplumber/actions/runs/33014948301` (all six native
  wheel targets successful). Tag publication and downloaded-wheel gates:
  `https://github.com/k3rnL/wyreplumber/actions/runs/33015311435` (all build,
  installed-wheel, source, and publication jobs successful).
- Public release: `https://github.com/k3rnL/wyreplumber/releases/tag/v0.2.0`;
  GitHub reports release ID `377432949`, `immutable: true`, `draft: false`, and
  `prerelease: false`.
- The complete public matrix contains six CPython 3.12/3.13/3.14 wheels for
  AArch64/x86_64 and one source archive, with an adjacent checksum and portable
  provenance record for each primary artifact (21 assets total). Every checksum
  and provenance target/commit/tag/workflow record passed fresh-download
  verification.
- Appliance artifact:
  `wyreplumber-0.2.0-cp313-cp313-linux_aarch64.whl`, 329,211 bytes, SHA-256
  `cfb92cd7f407c87717f1f539ff3e04573d0cd2224ef744f8efb847a7938e05fd`;
  provenance SHA-256
  `ade1107162e1624afa12e101dd4a542d402af372acffdb69999ad8d7a552e858`.
- The exact public appliance wheel was installed with `--no-deps` in an
  isolated Python 3.13 environment on the physical AArch64 Debian Trixie Pi.
  Import/package version `0.2.0`, AArch64 ELF identity, linkage to
  `libpipewire-0.3.so.0` and `libwireplumber-0.5.so.0`, the absence of
  WirePlumber 0.4 and PulseAudio linkage, build API family `0.5`, orchestration
  contract 1, runtime-value schema 1, and the live WirePlumber 0.5.8 snapshot
  all passed. The installed appliance environment was not modified.

### Open Cinema UI `v2.0.0`

- Accepted commit: `f6f437809da0c646ca29f8a9e4e2725a51378b41` on remote `master` and tag `v2.0.0`.
- Branch gate: `https://github.com/k3rnL/open-cinema-ui/actions/runs/33010439755` (success).
- Tag publication and downloaded-byte gate: `https://github.com/k3rnL/open-cinema-ui/actions/runs/33010953333` (both jobs successful).
- Public release: `https://github.com/k3rnL/open-cinema-ui/releases/tag/v2.0.0`.
- Admin archive: `open-cinema-admin-v2.0.0.tar.gz`, 1,070,748 bytes, SHA-256 `47d215f08a4740e47b7009abb6f0814f94d5330af222c4d98b90caf7ec057ea7`.
- Admin provenance: `open-cinema-admin-v2.0.0.tar.gz.provenance.json`, 489 bytes, SHA-256 `19ce3f8ae3ccd83eab6e1457e26e582b523af83a5a07408082e84ef58f710b1c`.
- On-box archive: `open-cinema-ui-v2.0.0.tar.gz`, 67,443 bytes, SHA-256 `91980a2c0ac72fe54ae04ba84340fddf89a5edeb3fc40b99cb296748e63d8560`.
- On-box provenance: `open-cinema-ui-v2.0.0.tar.gz.provenance.json`, 487 bytes, SHA-256 `c7f39366661c9ba8c251a43bc79a76981153e095a898510a777ea38161c6a200`.
- Checksums record: `checksums.sha256`, 418 bytes, SHA-256 `0feccd43c3fdbf66eb75060a6ce147584725d31155b460df0c636d7053071cec`; it validates both archives and both provenance records.
- Fresh public-download verification passed archive safety and contents, release/version identity, the admin client-contract asset, independent HTTP entry-point smoke, and the workflow's pre-upload and post-download Playwright checks.

### PCM Auto Decoder `v0.2.2`

- Accepted commit: `5856a5ef035618a7284a91f80bdd4ac24afe3427` on remote `master` and lightweight tag `v0.2.2`; rejected tags `v0.2.0` and `v0.2.1` were not moved or reused.
- Branch gate: `https://github.com/k3rnL/pcm-auto-decoder/actions/runs/33012341581` (native Debian Trixie x86_64 and AArch64 jobs successful).
- Tag publication and downloaded-byte gates: `https://github.com/k3rnL/pcm-auto-decoder/actions/runs/33013745740` (both native builds, release creation, and both minimum-runtime download jobs successful).
- Public release: `https://github.com/k3rnL/pcm-auto-decoder/releases/tag/v0.2.2`.
- AArch64 archive: `pcm-auto-decoder-v0.2.2-debian-trixie-aarch64-unknown-linux-gnu.tar.gz`, 652,221 bytes, SHA-256 `7831af706c22198dbb531682264b7eedf88fc693c459d5f4c8c05e154d5e616e`; provenance SHA-256 `1ebe283c5ce274ed6bbdc1481a5b8fc9a82098f5b133f4dc02ae40a031a84f49`.
- x86_64 archive: `pcm-auto-decoder-v0.2.2-debian-trixie-x86_64-unknown-linux-gnu.tar.gz`, 673,701 bytes, SHA-256 `53c22c155567310391c6f65f94f16f27863e5de537966cf2fb53f9676692f205`; provenance SHA-256 `ba034334cbda1b715f4cc7f1d747a7b12ff46d95020d86897b1ad1be2e5ae16a`.
- Fresh public bytes passed the published checksums and portable-provenance checks. The AArch64 archive then ran on the physical Debian Trixie Pi: `--version` reported `0.2.2`, ELF identity was AArch64, direct linkage included PipeWire and system FFmpeg with no PulseAudio library, and the finite plus looping offline decode fixture passed.

## Previous tuple: public-byte verification and rollback decision

GitHub still exposes all four releases as non-draft, non-prerelease public
releases. Every listed asset downloaded successfully on 2026-08-26 and every
published checksum record passed.

| Release | Available verified primary assets (SHA-256) | Compatibility result |
|---|---|---|
| Open Cinema `v0.2.0` | `open_cinema-0.0.1.tar.gz` — `df150a9b1644fe9b459a24c57f1302e8b2f53d86ab5a5317fc57cfe0cf07155e` | **Reject as immutable `0.2.0`.** Tag-time `version.py`, sdist filename, and `PKG-INFO` all identify `0.0.1`; no wheel, provenance, contracts package, or coordinated manifest was published. |
| WyrePlumber `v0.1.0` | sdist `ce45d199365893ee9820b8270d77a57c62de45e2999f51b64ae58e29f9469c8d`; Pi wheel `cp313/aarch64` `8396d1acbb21fc99c441f4a8e8e840cc2c11b2fdf50f20fd99014b18c7cec99b` (all six wheel checksums also passed) | **Reject for current appliance ABI.** The inspected Pi wheel's ELF dependency is `libwireplumber-0.4.so.0`, while the supported appliance runs WirePlumber 0.5. No portable provenance was published. |
| PCM Auto Decoder `v0.1.4` | AArch64 `a7aef9e8313eee254c91768ab842f830b5a5efedde32e186f11c22bf405b3fb6`; x86_64 `e78e9d1b3f9cfcf0a9d5822f5c0df5bd7196a4a8ac9bdd5045a41b07e81c807d` | **Reject for current native graph.** The inspected Pi binary directly needs `libpulse-simple.so.0` and `libpulse.so.0`; it predates native PipeWire output/status v2 and has no Trixie qualifier or provenance. |
| Open Cinema UI `v1.0.5` | admin `9e0ca015dba1e366b3651a4b92f1cb90978ae4232d1b516074a3aeffcc6e7d6e`; on-box `0947705bbc6ed46e56d23c5608e03b285638a0bd3e8b9a194967d9d09a8c88a8` | Downloadable static fallback; archives contain HTML/JS/CSS entry points. It lacks the new runtime identity, client-contract asset, and portable provenance, so it cannot make the full tuple suitable by itself. |

There is no `deployment/release-manifest.yml` at the Open Cinema `v0.2.0` tag.
The current repository manifest is explicitly `experimental`, `promotable:
false`, and based on local dirty trees. It is development evidence, not the
previous immutable manifest.

The documented Pi transition bundle
`transition-20260826T002452-ebd7b2b6d014` is therefore the only currently
identified replacement baseline. Release task 9.2 revalidated its private
controller capsule against the committed receipt on 2026-08-26: the exact
84,236,888-byte capsule and inner manifest/READY digests matched, all 18 regular
files covered the nine restore artifacts and six nested archives, and the
read-only SQLite integrity check returned `ok`. The controller file remains
mode `0400` below a mode `0700` parent, while a read-only appliance check found
all 20 entries in the retained source bundle still carrying the immutable flag.

Appliance-mode Ansible now repeats that receipt-bound verification on the
controller before the first target-mutating role. It publishes only the safe
baseline identity, protects that identity from permission rewrites and pruning,
and stops promotion on any mismatch or missing private retrieval pointer.
Development mode records an explicit skip. The capsule location and private
contents remain excluded from committed evidence.

## Remaining pre-mutation blockers

1. Final dirty-state counts/digests in this file must match the worktrees after
   concurrent release-readiness edits settle; rerun the inventory before any
   staging.
2. Resolve the two pre-existing index anomalies explicitly without discarding
   work (`plugin/pipewire/**` in Open Cinema and `oui.py` in WyrePlumber).
3. Decide and document how Open Cinema `pipewire` and WyrePlumber
   `pipewire-object-refactor` reach default `master`; neither development state
   may be tagged merely because it is local or has an upstream feature branch.
4. Commit and remotely exercise every candidate CI/release workflow. Branch
   protection does not enforce them, so successful run URLs and SHAs are
   mandatory evidence.
5. Bump/version-check only in dependency order, update the incompatible
   compatibility ranges and stale deployment pins only from verified published
   assets, and never reuse or retarget a failed published tag.
6. Reverify and retain the appliance transition-bundle baseline before
   promoting the new coordinated manifest.
