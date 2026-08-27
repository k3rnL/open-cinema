## Context

See `proposal.md` for motivation and `specs/coordinated-project-releases/spec.md` for the release contract. The four repositories already use `v*` tag-triggered GitHub release workflows and conventional history for release notes, but they are at different versions and all contain substantial uncommitted development work. The current appliance manifest explicitly describes local dirty trees and is therefore useful development evidence, not a promotable release input.

The release surfaces also have concrete inconsistencies:

- Open Cinema derives its version from `version.py`, publishes only a source archive, and still has a standalone CamillaDSP ARM64 workflow that builds a Pulse backend which is no longer part of the native PipeWire architecture.
- WyrePlumber's release matrix builds most wheels against WirePlumber 0.4 even though its orchestration contract is validated against WirePlumber 0.5.
- PCM Auto Decoder's GitHub and devcontainer environments still install PulseAudio-era dependencies and are not aligned to the Debian Trixie ABI used by the appliance.
- Open Cinema UI versions the workspace packages independently through npm, while current CI treats lint as optional and does not gate releases on unit or end-to-end tests.

The current production fixture is Debian 13 (Trixie), AArch64, on a Raspberry Pi 5. GitHub release immutability is verified per publication surface; every appliance-selected byte must resolve through an immutable release or a digest-identical immutable coordinated mirror. Local worktree content belongs to the user and must not be discarded or rewritten while history is curated.

## Goals / Non-Goals

**Goals:**

- Turn the current four-repository implementation into reviewable source history and a coherent release tuple.
- Make each repository's normal CI and tag workflow authoritative for its own artifacts.
- Verify native ABI and architecture compatibility from the published bytes, not merely from local builds.
- Replace the development manifest's mutable sources with immutable artifacts, digests, provenance, and compatibility data.
- Leave a documented previous manifest that deployment can use for rollback.

**Non-Goals:**

- Fixing product UI/UX defects or adding product features while preparing the UI release.
- Collecting appliance performance benchmarks.
- Proving installation onto a fresh image or independence from every prior deployment state.
- Implementing a second processing instance or changing audio graph behavior.
- Executing the deployment rollback itself; deployment owns that operation.

## Decisions

### 1. Treat the release as a versioned tuple, not a shared version number

The coordinated release record will name four independent versions: corrective Open Cinema `0.3.2`, WyrePlumber `0.2.0`, PCM Auto Decoder `0.2.2`, and Open Cinema UI `2.0.0`. Open Cinema `v0.3.0` passed source, test, package, and native-artifact gates but stopped before artifact upload because its release-only manifest finalizer environment lacked PyYAML. Corrective `v0.3.1` fixed that dependency and built the complete finalized manifest, but stopped before creating a draft release because the scoped Actions token cannot read the administration-only repository immutability setting. Both tags remain fixed and excluded. Corrective `v0.3.2` verifies the resulting public release's `immutable` field through the release endpoint that the scoped token can read, and rejects and removes an explicitly mutable release while retaining the failed tag. Decoder `v0.2.0` was created once but failed before publication because its tag workflow could not read the container-owned checkout. Corrective `v0.2.1` published its artifacts, but its AArch64 post-download gate exposed an incomplete minimum-runtime package list (`libavformat61` was omitted). Those failed or rejected tags remain fixed and excluded; decoder `v0.2.2` corrects its verification environment and must pass the complete published-byte gate. Each repository keeps its existing `v<project-version>` tag convention, while the Open Cinema deployment manifest binds the four accepted tags and their contract versions into one release identifier.

This avoids forcing unrelated repositories into lockstep SemVer while retaining one compatibility decision. A single shared version was considered, but would make future independent patch releases misleading and needlessly coupled.

### 2. Curate worktrees before changing release metadata

For each repository, the implementation will first capture branch, parent commit, full status, untracked files, and diff summaries. Changes will then be grouped by coherent subsystem and staged selectively into conventional commits. Generated outputs, secrets, machine-local files, and unrelated user changes will be excluded intentionally; no reset, blanket discard, history rewrite, or catch-all commit will be used.

Repository tests will run at meaningful commit boundaries, then the version/lockfile and release-readiness changes will form explicit commits. This makes the tag auditable and keeps a release bump from obscuring the implementation it publishes. Squashing every dirty tree into one commit was rejected because it would make regression isolation and review impractical.

### 3. Keep repository-native release workflows authoritative

Each project will retain its tag-triggered GitHub Actions release path. Branch CI must pass on the intended release commit before its tag is created; the tag workflow then rebuilds and publishes from that same commit. Metadata-to-tag checks will fail early, and a failed published tag will never be moved or reused—a corrective version will be required if immutable release bytes are invalid.

Building all four projects from a new central release workflow was considered, but rejected because it would duplicate project knowledge, weaken repository ownership, and make isolated patch releases harder. Coordination belongs in the manifest and release runbook rather than in a monolithic build job.

### 4. Make each project's gates and assets fit its runtime contract

The repositories will share identity, checksum, provenance, and post-download conventions while retaining project-specific validation:

- **Open Cinema:** align `version.py`, package metadata, declared WyrePlumber compatibility, lock data, license metadata, package data, and shipped contract documents; run the complete Python suite plus build, archive-content, isolated-install, version, and contract probes. The current Pulse-backend CamillaDSP workflow will be removed because CamillaDSP 4 is an independently versioned, deployment-pinned native PipeWire component, not an Open Cinema release output.
- **WyrePlumber:** build and test the native extension against WirePlumber 0.5 on the supported Linux/Python target matrix, including a Debian Trixie AArch64 wheel usable by the appliance. CI will install each produced wheel, validate its reported package and WirePlumber build versions, run the orchestration tests, and inspect native linkage before publishing it with the source archive.
- **PCM Auto Decoder:** use a Debian Trixie development and release environment with native PipeWire and system FFmpeg development libraries, no PulseAudio dependency, and locked Rust resolution. CI will test, build natively for the declared architecture, inspect dynamic linkage and runtime version, then publish target-qualified archives. The AArch64 artifact used by the appliance will be built in an AArch64 Trixie environment so its dynamic ABI matches the target rather than relying on an unverified cross sysroot.
- **Open Cinema UI:** update the root, both applications, the shared workspace package, and the lockfile to one `2.0.0` workspace version through deterministic scripts. CI and the release workflow will require dependency installation, audit triage, shared build, type checking, lint, unit tests, both production builds, and a bounded Playwright end-to-end smoke. Release archives will continue to separate the administration UI from the on-box placeholder UI.

For npm security findings, automated major-version remediation is not an acceptable release shortcut. Production-impacting findings must be resolved or explicitly rejected with evidence; development-only findings may be documented with impact and follow-up. Making lint or tests advisory was rejected because it would let the tag workflow publish a state that branch CI did not actually accept.

### 5. Publish dependencies before consumers

Publication will proceed in this order:

1. WyrePlumber `0.2.0` and PCM Auto Decoder `0.2.2`, which are lower-level runtime components and can be released independently.
2. Open Cinema UI `2.0.0`, whose contract assets must exist before the appliance manifest is finalized.
3. Open Cinema `0.3.2`, after its dependency/version references and compatibility documents name the verified releases and the failed `v0.3.0` and `v0.3.1` tags remain excluded.
4. The coordinated immutable manifest, only after all four published artifact sets pass download verification.

Independent components may build in parallel, but no consuming tag or manifest promotion may point to an asset that is not already downloadable and verified. Tagging everything simultaneously was rejected because a failed dependency release could leave consumers permanently pointing at a nonexistent or invalid artifact.

### 6. Separate the development input before promoting `deployment/release-manifest.yml`

The existing mutable record will first be retained as the explicitly selected
`deployment/development-manifest.yml` fixture. Local inventories may choose that
file only together with development mode and explicit source directories. The
canonical `deployment/release-manifest.yml` will then become the source template
for the coordinated record. Before the Open Cinema tag, it will pin every
already-published dependency by repository, version/tag, source commit, artifact
URL/name, SHA-256 digest, supported platform selector, and relevant API/ABI
contract, while declaring the expected Open Cinema tag and commit identity.

The Open Cinema tag workflow will build its own distribution, compute the previously unknowable digest of those exact bytes, inject its artifact URL/digest and workflow provenance into a finalized manifest, and publish that manifest plus its checksum as release assets. This avoids a circular requirement to commit an artifact's digest into the source from which that artifact is built. Deployment consumes the finalized release asset; after verification, the exact finalized manifest is recorded with release-closure evidence and becomes the current deployment pin.

The coordinating release may mirror already verified UI, decoder, CamillaDSP,
and Python-client bytes into its own immutable asset set. Mirroring does not
replace source provenance: every manifest entry keeps the producing repository,
tag, commit, workflow, original artifact identity, and digest, while its selected
URL identifies the byte-for-byte coordinated mirror. This lets deployment and
rollback resolve one retained release without weakening cross-project traceability.

Local-source modes, parent-only dirty-tree revisions, mutable URLs, and editable
dependencies are forbidden in the candidate and finalized manifests. A validator
will cross-check schema completeness, version/tag relationships, digest format,
contract compatibility, and the absence of mutable inputs before Ansible consumes
the file. Project release assets will also carry a small provenance record
containing repository, tag, commit, workflow run, build target, and artifact
digest; GitHub artifact attestations can supplement but not replace this portable
record.

Embedding whichever files happen to be present beside the playbook was rejected because it cannot prove what a later installation or rollback will retrieve.

### 7. Test the published bytes twice

After each tag workflow finishes, release verification will download the release assets to a new temporary directory, verify checksums/provenance and expected filenames, inspect archive contents, then perform the project's install/import/start/version/native-linkage smoke as applicable. Local `dist/` files cannot satisfy this gate.

After manifest assembly, deployment will consume the candidate manifest on the existing Raspberry Pi fixture. It must report the exact four versions, pass service readiness, and pass a bounded audio-path smoke. This is an immutable-artifact acceptance test on the known fixture, not clean-install validation or a benchmark.

### 8. Preserve the previous release before promotion

Before replacing the current coordinated manifest, the release process will snapshot its identity and verify that every referenced previous artifact remains downloadable and digest-valid. The new manifest will be promoted only after that check and the candidate appliance smoke pass. The previous manifest is release output for the deployment rollback role; this change does not invoke or redefine the rollback mechanism.

Treating Git tags alone as retention was rejected because a tag does not prove that every binary asset and external component required by the former appliance remains resolvable.

### 9. Record release closure as evidence, not tribal knowledge

The repository will retain a concise release record with the four tags and commits, CI/release run links, artifact names and hashes, manifest identity, validation results, Pi smoke evidence, known limitations, and previous-manifest identity. README files remain the current user/developer entry points; the closure record is an auditable statement about this exact release set.

## Risks / Trade-offs

- **Large dirty worktrees can mix unrelated or generated changes** → Inventory every path, use selective staging and coherent conventional commits, review each staged diff, and preserve excluded user work in place.
- **A native wheel or binary can build successfully but target the wrong ABI** → Build production artifacts in native Debian Trixie target environments, inspect linkage, and run downloaded artifacts on the Pi before promotion.
- **A tag workflow can fail after the immutable tag is pushed** → Pass branch gates first, tag dependencies sequentially, never retarget a published tag, and use a corrective version when necessary.
- **Repository CI repairs can expose unrelated failures** → Separate release-blocking correctness fixes from product behavior changes and document deferred product/UI defects without weakening gates.
- **Security audit remediation can destabilize the UI** → Triage findings by runtime reachability and severity; avoid blind forced upgrades and rerun unit, build, and E2E gates after dependency changes.
- **Four independently versioned releases can drift** → Make the manifest validator and post-download verifier the promotion gate, with explicit compatibility-contract versions.
- **Published releases and pushes are externally visible mutations** → Review source, version surfaces, remote target, and staged commits before pushing; publish only in dependency order and capture remote workflow results.

## Migration Plan

1. Inventory all four repositories, their remotes/branches/tags, dirty paths, current version surfaces, CI workflows, release asset conventions, and README gaps; save no machine-local or secret material in commits.
2. Repair release infrastructure and project documentation, then run the full local validation suite for each repository.
3. Partition implementation changes into coherent conventional commits, review staged content, and leave unrelated user-owned changes untouched.
4. Apply the exact version bumps and regenerated lock data, verify metadata and runtime version output, push the curated commits, and wait for required branch CI.
5. Tag and publish WyrePlumber and PCM Auto Decoder; download and verify their native assets before continuing.
6. Tag and publish Open Cinema UI; verify both application archives and their contract asset.
7. Update Open Cinema's dependency and compatibility references to the verified component releases, rerun its complete suite, then tag and publish Open Cinema.
8. Before the Open Cinema tag, record the verified dependency digests/provenance in `deployment/release-manifest.yml`, preserve/verify the previous manifest, and validate the candidate template; let the tag workflow finalize and publish the manifest with the newly built Open Cinema artifact digest.
9. Download and validate the finalized manifest, make it the explicit deployment pin, apply it to the existing Raspberry Pi, verify exact versions/readiness, run the bounded audio-path smoke, and record the exact manifest plus closure evidence.

If a pre-publication step fails, fix it before tagging. If a published dependency artifact fails verification, stop the sequence and publish a corrective dependency version rather than modifying the tag. If the candidate appliance smoke fails, keep the previous manifest current; deployment may use that retained manifest through its own rollback procedure.
