## Why

Open Cinema now spans four independently built repositories, but the deployed appliance can only be reproduced and rolled back safely when their versions, native artifacts, documentation, and dependency pins are published as one coherent release set. The current development worktrees therefore need to be curated into reviewable history and released through each repository's own CI before deployment consumes immutable artifacts.

## What Changes

- Introduce a coordinated release contract covering Open Cinema `0.3.0`, WyrePlumber `0.2.0`, PCM Auto Decoder `0.2.0`, and Open Cinema UI `2.0.0`.
- Require repository metadata, package versions, Git tags, release assets, native ABI/architecture, hashes, provenance, and deployment-manifest entries to agree.
- Curate the existing dirty worktrees into intentional conventional commits without discarding user work, then validate, version, push, tag, and publish through each repository's established CI and release strategy.
- Repair release blockers in the backend, WyrePlumber Python binding, native decoder, and UI build/test pipelines; remove obsolete PulseAudio-era CamillaDSP release automation from the current backend release path.
- Bring every repository README up to date with its present architecture, supported platform, development workflow, validation commands, and release/install usage.
- Publish dependencies before consumers, verify the actual downloadable artifacts, and smoke-test an immutable coordinated manifest on the Raspberry Pi appliance.
- Retain the immediately previous coordinated manifest and artifacts as the input to deployment-owned rollback; this change proves release production and consumption but does not own appliance rollback execution.

## Capabilities

### New Capabilities

- `coordinated-project-releases`: Defines the observable integrity, ordering, validation, documentation, artifact, manifest, smoke-test, and retention guarantees for publishing a compatible multi-repository Open Cinema release set.

### Modified Capabilities

None.

## Impact

- Repositories: `open-cinema`, `wyreplumber`, `pcm-auto-decoder`, and `open-cinema-ui`.
- Release surfaces: package metadata, CI workflows, native build environments, tags, release assets, checksums/provenance, READMEs, and the appliance release manifest.
- Deployment consumes the resulting immutable manifest and owns rollback; product UI fixes, Raspberry Pi benchmarking, and clean-install/upgrade-independence validation remain outside this change.
