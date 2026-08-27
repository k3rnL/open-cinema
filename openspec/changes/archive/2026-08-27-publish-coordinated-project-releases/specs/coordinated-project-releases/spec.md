## Purpose

Defines how independently built Open Cinema projects are published as one traceable, immutable, compatible release set that an appliance can verify and deploy safely.

## ADDED Requirements

### Requirement: Coordinated release identity
Each coordinated release SHALL declare exactly one accepted repository version and Git tag for every participating project, and each project's package metadata, runtime version report, tag, release title, and artifact metadata SHALL agree on that version. The first accepted release governed by this capability SHALL contain corrective Open Cinema `0.3.2`, WyrePlumber `0.2.0`, PCM Auto Decoder `0.2.2`, and Open Cinema UI `2.0.0`; Open Cinema's unpublished failed `v0.3.0` and `v0.3.1` tags, the decoder's unpublished failed `v0.2.0` tag, and the decoder's published-but-rejected `v0.2.1` tag SHALL NOT be moved, reused, or admitted to the tuple.

#### Scenario: All release identities agree
- **WHEN** a coordinated release candidate is inspected
- **THEN** every declared version matches its repository metadata, runtime report, Git tag, release record, and published artifact metadata

#### Scenario: A version surface disagrees
- **WHEN** any participating project's declared version differs from one of its version surfaces
- **THEN** the coordinated release is rejected before it becomes the appliance's current manifest

### Requirement: Repository validation gates
Each project release SHALL originate from an intentional, reviewable source history and SHALL pass that repository's required static checks, tests, builds, and packaging checks at the exact release commit. A coordinated release SHALL NOT be accepted when a required gate is absent, skipped without an approved rationale, or failing.

#### Scenario: Exact release commits pass their gates
- **WHEN** the four release commits are submitted for publication
- **THEN** their repository pipelines validate the same commits from which the release artifacts are built

#### Scenario: A required validation fails
- **WHEN** a required repository check fails or does not run for a release commit
- **THEN** publication or coordinated-release promotion stops with the failing project and check identified

### Requirement: Platform-compatible release artifacts
Published assets SHALL contain all runtime artifacts declared by the coordinated manifest and SHALL state their operating-system, CPU-architecture, language-runtime, and native-ABI compatibility. Native WyrePlumber artifacts SHALL target the supported WirePlumber 0.5 interface, and native PCM Auto Decoder artifacts for the Raspberry Pi appliance SHALL run against its declared Debian Trixie ARM64 runtime without undeclared host build dependencies.

#### Scenario: Appliance-compatible native assets are available
- **WHEN** the release manifest is resolved for the supported Raspberry Pi platform
- **THEN** it selects downloadable WyrePlumber and decoder artifacts whose declared architecture and native ABI match that platform

#### Scenario: Only an incompatible native asset is available
- **WHEN** an artifact has the wrong architecture, operating-system baseline, WirePlumber interface, or native ABI
- **THEN** manifest verification rejects that artifact before installation

### Requirement: Artifact integrity and provenance
Every immutable release input SHALL have a cryptographic digest and provenance that links the downloaded bytes to the project, source repository, exact release commit, tag, build workflow, and artifact name. Integrity verification SHALL occur before an artifact is admitted to a coordinated manifest or installed by deployment.

#### Scenario: Artifact bytes match recorded provenance
- **WHEN** a published artifact is downloaded for manifest assembly or smoke testing
- **THEN** its digest matches the recorded digest and its provenance resolves to the declared tagged source commit and build

#### Scenario: Artifact bytes or provenance do not match
- **WHEN** a digest differs or provenance cannot establish the declared source and build
- **THEN** the coordinated release is rejected without replacing the current known-good manifest

### Requirement: Current repository documentation
At each release tag, every participating repository SHALL provide a README that accurately describes that release's purpose, current architecture, supported runtime/platform, development and validation commands, installation or artifact-consumption path, and release/version convention. Current documentation SHALL NOT direct users through removed PulseAudio-era runtime paths.

#### Scenario: Documentation is checked at the release tag
- **WHEN** a maintainer follows each tagged README on a supported development or runtime platform
- **THEN** the described commands, components, supported versions, and installation or consumption paths agree with the released code and artifacts

#### Scenario: Documentation describes a removed runtime path
- **WHEN** a current README presents an obsolete PulseAudio-era path as supported
- **THEN** the affected project is not ready for coordinated release publication

### Requirement: Immutable coordinated manifest
The release process SHALL produce a machine-readable coordinated manifest that pins every project and external runtime input by immutable version or revision, artifact location, digest, platform selector, and compatibility relationship. A manifest SHALL be internally complete and SHALL NOT depend on editable working directories, floating branches, mutable latest URLs, or unpinned dependency resolution.

#### Scenario: Manifest resolves a complete appliance stack
- **WHEN** deployment resolves the coordinated manifest for a supported platform
- **THEN** every required component maps to one immutable, digest-verified input with compatible dependency constraints

#### Scenario: Manifest contains a mutable or incomplete input
- **WHEN** a manifest entry uses a floating reference, lacks a digest, lacks a required platform asset, or violates another entry's compatibility constraint
- **THEN** manifest validation fails before deployment is permitted to consume it

#### Scenario: Independently published bytes are mirrored by the coordinated release
- **WHEN** the coordinating workflow retains a verified UI, decoder, CamillaDSP, or Python-client artifact in its immutable release
- **THEN** the manifest selects the digest-identical coordinated URL while preserving provenance to the producing repository, tag, commit, workflow, and artifact identity

### Requirement: Dependency-ordered publication
Projects SHALL be published in an order that makes every pinned dependency and required artifact available and verified before a consuming project or the coordinated manifest is promoted. A consumer release SHALL reference only dependency artifacts that are already verified and downloadable, and the appliance manifest SHALL select them through either an immutable producing release or a digest-identical immutable coordinated mirror.

#### Scenario: Dependencies publish successfully
- **WHEN** all lower-level project artifacts have passed post-publication verification
- **THEN** dependent projects and finally the coordinated manifest may be published with digest-pinned dependency references that resolve through an immutable selected publication surface

#### Scenario: Dependency publication is incomplete
- **WHEN** a required dependency tag, release record, artifact, digest, or verification is missing
- **THEN** dependent publication pauses and no complete coordinated release is announced

### Requirement: Post-publication artifact verification
Release acceptance SHALL exercise the artifacts fetched from their published locations rather than substituting local worktrees or pre-publication build outputs. Verification SHALL cover package metadata, version reporting, import or startup behavior, native linkage where applicable, and the project's principal testable runtime entry point.

#### Scenario: Published project artifact passes its smoke test
- **WHEN** an artifact is downloaded from the release location into a clean verification environment
- **THEN** its identity, integrity, load or startup behavior, native linkage, and principal entry point satisfy the release contract

#### Scenario: Published bytes differ from locally tested output
- **WHEN** the downloadable artifact fails a smoke check even though a local build passed
- **THEN** the downloadable artifact result is authoritative and coordinated release promotion stops

### Requirement: Appliance manifest smoke test
Before coordinated release closure, the supported Raspberry Pi appliance SHALL consume the immutable manifest through the deployment interface, verify all inputs, start the released service set, and demonstrate service readiness and an audio-path smoke test. Release work SHALL supply and verify the manifest; deployment SHALL remain responsible for installation orchestration and rollback behavior.

#### Scenario: Immutable release set runs on the appliance
- **WHEN** deployment applies the candidate coordinated manifest to the supported Raspberry Pi
- **THEN** all released services report the declared versions, reach readiness, and pass the defined audio-path smoke test without using repository working directories

#### Scenario: Appliance smoke test fails
- **WHEN** installation, version verification, readiness, or the audio-path smoke test fails
- **THEN** the candidate is not closed as the current coordinated release and deployment retains authority to restore the previous manifest

### Requirement: Previous release retention
Closing a coordinated release SHALL retain the immediately previous known-good manifest and all artifacts needed to resolve it. Retention SHALL be verified before the new manifest is promoted and SHALL expose the previous manifest as the input for a deployment-owned rollback exercise.

#### Scenario: New coordinated release is promoted
- **WHEN** the candidate manifest completes all release and appliance smoke gates
- **THEN** the former current manifest remains immutable, resolvable, digest-verifiable, and available to deployment as the previous release

#### Scenario: Previous release cannot be resolved
- **WHEN** any artifact required by the previous known-good manifest is unavailable or fails integrity verification
- **THEN** the candidate release cannot be closed until retention is restored or an explicit replacement rollback baseline is validated
