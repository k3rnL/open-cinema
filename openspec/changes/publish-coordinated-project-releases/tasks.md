## 1. Release Inventory and Safety Boundary

- [x] 1.1 Record the branch, HEAD, remotes, upstream, latest tags, and complete modified/deleted/untracked path list for all four repositories in a release-preparation evidence file without recording credentials or machine secrets.
- [x] 1.2 Inspect every dirty path and classify it as intended product work, release-readiness work, generated output, machine-local state, secret-sensitive material, or explicitly deferred user work; record the classification before staging anything.
- [x] 1.3 Map included paths to small coherent conventional-commit groups and document exclusions; prohibit blanket staging, resets, history rewrites, and deletion of excluded user-owned work.
- [x] 1.4 Verify each repository's integration branch, `v<version>` tag convention, required CI, release workflow, asset naming, GitHub remote, and push/release authority before an external mutation.
- [x] 1.5 Inventory every version surface, cross-project dependency, API/ABI contract, release asset, deployment pin, and current README claim, then define the expected four-project version/tag/asset matrix.
- [x] 1.6 Resolve the immediately previous candidate tuple (`open-cinema` `0.2.0`, WyrePlumber `0.1.0`, decoder `0.1.4`, UI `1.0.5` or a documented replacement), verify which immutable assets actually remain available, and identify the manifest that can serve as the rollback baseline.

## 2. Open Cinema Release Readiness

- [x] 2.1 Make `version.py`, Python package metadata, runtime version reporting, and the `v*` tag check one consistent backend version contract while leaving the final `0.3.0` bump for release preparation.
- [x] 2.2 Correct backend metadata and distribution inputs, including supported Python declarations, dependency contracts, SPDX/license data and `LICENSE`, and all package data required at runtime.
- [x] 2.3 Include the required audio-orchestration contracts and other non-Python runtime resources in both wheel and source archives, and add archive-content tests that fail when required files or license material are missing.
- [x] 2.4 Add an isolated distribution smoke test that installs built artifacts without adjacent worktrees and verifies import, reported version, contract discovery, Django checks, and the orchestrator entry point.
- [x] 2.5 Add required branch/PR CI for the complete backend test suite, static/project checks, wheel and source builds, archive inspection, and isolated-install smoke; make release publication depend on equivalent gates at the tag commit.
- [x] 2.6 Harden the tag release workflow with tag/metadata agreement, wheel and source artifacts, per-artifact SHA-256 and portable provenance, and finalization of the coordinated manifest with the just-built Open Cinema artifact identity.
- [x] 2.7 Remove the obsolete Pulse-backend CamillaDSP ARM64 workflow and update current backend/deployment documentation so CamillaDSP 4 is described only as an independently pinned native PipeWire component.
- [x] 2.8 Rewrite the backend README to match the current native PipeWire/WirePlumber architecture, admin and on-box UI roles, processor model, supported platform, local development, full validation, immutable installation, and release/version workflow.

## 3. WyrePlumber 0.5 Artifact Readiness

- [x] 3.1 Remove WirePlumber 0.4 build/test dependencies from current workflows and define the supported WirePlumber 0.5 Linux/Python/architecture release matrix, including the Debian Trixie AArch64 appliance target.
- [ ] 3.2 Build native wheels and the source archive in WirePlumber 0.5 environments with unique target-qualified outputs, and prevent repeated source archives or flattened artifacts from silently overwriting one another.
- [x] 3.3 Add automated agreement checks for package metadata, installed runtime version, Git tag, Python ABI, CPU architecture, and `WIREPLUMBER_BUILD_API_FAMILY == "0.5"`.
- [x] 3.4 Add required branch/PR CI that builds, installs, and tests each supported wheel, runs the complete orchestration contract suite, inspects native linkage, and exercises a real WirePlumber 0.5 runtime where supported.
- [x] 3.5 Harden the tag workflow to reuse equivalent gates and publish wheels/source with SHA-256 files and portable commit/workflow/target provenance.
- [x] 3.6 Update the WyrePlumber README with the binding's current orchestration scope, WirePlumber 0.5 requirement, supported Python/platform matrix, source and wheel installation, development/test commands, runtime permissions, and release process.
- [x] 3.7 Run the full local WyrePlumber unit/integration/contract suite, build and install the current-host wheel in a clean environment, verify native imports/linkage/version reporting, and record the results.

## 4. PCM Auto Decoder Native Release Readiness

- [x] 4.1 Replace the Bullseye/PulseAudio devcontainer with a Debian Trixie environment containing only the required native PipeWire, system FFmpeg, Clang, and Rust build/runtime dependencies; remove the obsolete PulseAudio D-Bus entrypoint behavior.
- [x] 4.2 Add required branch/PR CI for formatting, Clippy, locked tests, offline fixture behavior, and release builds in the declared Debian Trixie targets.
- [x] 4.3 Rework the tag workflow to build natively on Trixie x86_64 and AArch64 runners/containers with `--locked`, eliminate duplicate and PulseAudio build dependencies, and emit unambiguous target-qualified archives.
- [x] 4.4 Make Cargo metadata, lock data, the binary's `--version`, archive names, release title, and Git tag agree, with a workflow check that rejects mismatches.
- [ ] 4.5 Inspect release linkage and the minimum runtime contract, requiring system PipeWire/FFmpeg libraries, rejecting `libpulse`, and testing the AArch64 binary on Debian Trixie before publication acceptance.
- [x] 4.6 Publish and verify per-archive SHA-256 and portable provenance, plus a downloaded-artifact smoke that exercises version output and a bounded looping offline decode fixture.
- [x] 4.7 Update the decoder README with its stable adaptive output contract, supported codecs/layouts, native PipeWire ownership, Trixie build/runtime dependencies, devcontainer and validation commands, release assets, installation, and version convention.

## 5. Open Cinema UI 2.0 Release Readiness

- [x] 5.1 Replace the ambiguous workspace release/version scripts with an explicit deterministic version command that updates the root, both applications, shared package, and lockfile to one supplied version without pushing implicitly.
- [x] 5.2 Add a version-consistency check covering every workspace manifest, the lockfile, runtime/build metadata, artifact names, and `v*` tag.
- [x] 5.3 Run `npm audit`, classify each finding by production reachability and severity, safely remediate release blockers, and record evidence for any accepted development-only finding without using an unreviewed forced major upgrade.
- [x] 5.4 Make lint, type checking, shared-package build, all unit tests, both application production builds, and dependency installation hard CI failures rather than advisory or silently skipped steps.
- [x] 5.5 Add a bounded Playwright release smoke that proves the administration application can boot and authenticate against its test contract and that the on-box placeholder application can boot, without expanding into deferred product UI fixes.
- [x] 5.6 Make the tag workflow run the same required gates, reject tag/version disagreement, and publish separate admin/on-box archives with SHA-256 and portable provenance.
- [x] 5.7 Add downloaded-archive verification for expected entry points, static asset completeness, the administration API-contract asset, version identity, and a served-build smoke.
- [x] 5.8 Update the UI README to distinguish the end-user administration console from the on-box placeholder, and document current architecture, environment configuration, development, audit/type/lint/unit/E2E validation, builds, deployment assets, workspace versioning, and release flow.

## 6. Curate Reviewable Source History

- [ ] 6.1 Recheck all four worktrees against the inclusion map after release-readiness edits, inspect every staged diff for secrets/generated/local/deferred content, and update the map for newly created files before committing.
- [ ] 6.2 Stage, review, and commit Open Cinema application/API/orchestration implementation and tests in coherent conventional commits without including deployment, documentation, or release metadata merely for convenience.
- [ ] 6.3 Stage, review, and commit Open Cinema deployment, contracts, documentation, OpenSpec history, and release-readiness work in separately understandable conventional commits.
- [x] 6.4 Stage, review, and commit WyrePlumber binding/runtime/tests and release-readiness work in coherent conventional commits, preserving unrelated user paths.
- [x] 6.5 Stage, review, and commit PCM Auto Decoder runtime/tests and release-readiness work in coherent conventional commits, preserving unrelated user paths.
- [x] 6.6 Stage, review, and commit Open Cinema UI application/shared/tests and release-readiness work in coherent conventional commits, preserving deferred UI/UX work as explicitly documented rather than silently dropping it.
- [ ] 6.7 Run each repository's complete gate set at the curated HEAD, record the commit SHAs and remaining intentionally excluded paths, and do not begin version tagging until every release-relevant worktree state is explained.

## 7. Publish and Verify Runtime Dependencies

- [ ] 7.1 Bump every WyrePlumber version surface to `0.2.0`, regenerate derived metadata, run its complete gates, review and create the conventional release-preparation commit, then push through the repository's normal integration path and wait for CI success.
- [ ] 7.2 Verify the accepted remote WyrePlumber commit and version surfaces, create and push `v0.2.0`, wait for its release workflow, and stop without reusing the tag if publication fails irrecoverably.
- [ ] 7.3 Download WyrePlumber `v0.2.0` assets from the public release into a clean directory; verify filenames, hashes, provenance, metadata, clean installation, native linkage, WirePlumber 0.5 reporting, and the Debian Trixie AArch64 wheel on the Pi.
- [ ] 7.4 Record the accepted WyrePlumber tag, commit, workflow run, artifact URLs, target selectors, and hashes for the coordinated manifest.
- [ ] 7.5 Bump Cargo, lock, runtime, and release metadata to PCM Auto Decoder `0.2.0`, run its complete gates, review and create the conventional release-preparation commit, then push through the normal integration path and wait for CI success.
- [ ] 7.6 Verify the accepted decoder commit and version surfaces, create and push `v0.2.0`, wait for its release workflow, and stop without reusing the tag if publication fails irrecoverably.
- [ ] 7.7 Download decoder `v0.2.0` assets from the public release; verify filenames, hashes, provenance, `--version`, native linkage, absence of PulseAudio, offline decoding, and execution of the AArch64 artifact on Debian Trixie.
- [ ] 7.8 Record the accepted decoder tag, commit, workflow run, artifact URLs, target selectors, and hashes for the coordinated manifest.

## 8. Publish and Verify Open Cinema UI

- [ ] 8.1 Apply the deterministic `2.0.0` workspace bump, regenerate the lockfile, run audit/type/lint/unit/build/E2E and version-consistency gates, review and commit the release preparation, then push through the normal integration path and wait for CI.
- [ ] 8.2 Verify the accepted remote UI commit and all version surfaces, create and push `v2.0.0`, wait for the release workflow, and stop without reusing the tag if publication fails irrecoverably.
- [ ] 8.3 Download both `v2.0.0` archives and their integrity/provenance records; verify hashes, contents, contract asset, version identity, and served admin/on-box smoke tests from the downloaded bytes.
- [ ] 8.4 Record the accepted UI tag, commit, workflow run, artifact URLs, application roles, and hashes for the coordinated manifest.

## 9. Publish Open Cinema and the Coordinated Manifest

- [ ] 9.1 Replace backend release resolution with verified WyrePlumber `0.2.0` artifacts/metadata while retaining an explicit local-directory override only for development, and update decoder/UI compatibility references to their verified releases.
- [ ] 9.2 Materialize and verify the previous known-good manifest or its documented replacement baseline, ensuring all rollback inputs are immutable, downloadable, digest-valid, and retained before candidate promotion.
- [ ] 9.3 Convert `deployment/release-manifest.yml` into the candidate immutable template with exact dependency tags, commits, artifact URLs, hashes, provenance, platform selectors, and contract versions; remove all dirty-tree, floating, editable, and mutable release inputs.
- [ ] 9.4 Implement and run manifest validation for schema completeness, version/tag agreement, hashes, provenance, platform/ABI selection, compatibility constraints, previous-manifest identity, and the absence of mutable sources.
- [ ] 9.5 Bump every Open Cinema version surface to `0.3.0`, regenerate lock/package data, run the complete backend suite and isolated builds using released dependencies, review and commit the release preparation, then push through the normal integration path and wait for CI.
- [ ] 9.6 Verify the accepted remote backend commit, candidate manifest, and version surfaces; create and push `v0.3.0`, then wait for the workflow to publish the backend distributions and finalized coordinated manifest without reusing a failed tag.
- [ ] 9.7 Download the `v0.3.0` backend artifacts, finalized manifest, checksums, and provenance; verify clean installation/version/contracts, validate every manifest entry and published byte, and record the accepted backend and manifest identities.

## 10. Immutable Appliance Smoke and Release Closure

- [ ] 10.1 Update deployment's release-mode pins, expected asset names, URLs, hashes, and compatibility data from the verified finalized manifest while preserving local-source inventory strictly as an explicit development mode.
- [ ] 10.2 Verify deployment syntax/tests and manifest preflight, and prove release mode downloads and digest-checks published artifacts without reading any adjacent repository working directory or editable package.
- [ ] 10.3 Apply the finalized immutable manifest to the existing Debian Trixie Raspberry Pi fixture through the deployment interface; record installed artifact hashes and exact Open Cinema, WyrePlumber, decoder, and UI versions.
- [ ] 10.4 Verify all released services reach readiness, native WyrePlumber/decoder linkage and contracts match the manifest, and the resolved PipeWire graph contains the expected decoder and CamillaDSP processing path.
- [ ] 10.5 Run a bounded audio-path smoke through the immutable TV/decoder/CamillaDSP/output chain and verify administrative readiness without treating deferred UI/UX details or performance measurements as release gates.
- [ ] 10.6 Preserve the exact finalized current and previous manifests with their resolvable artifacts, update deployment's rollback pointer without executing rollback, and keep the previous manifest current if any immutable smoke gate fails.
- [ ] 10.7 Create and commit release-closure evidence containing the four tags/commits, CI and release runs, artifact names/URLs/hashes/provenance, finalized and previous manifest identities, Pi results, README review, exclusions, and known limitations; push it through CI and strictly validate the completed OpenSpec change.
