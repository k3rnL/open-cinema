# Open Cinema 0.3.2 coordinated release and appliance closure

Date: 2026-08-27 UTC

Status:

- **Coordinated publication accepted.** The four project identities are public,
  verified, and bound by one finalized manifest. Open Cinema and WyrePlumber
  are GitHub-immutable releases; the exact accepted UI and decoder bytes are
  mirrored into the immutable Open Cinema release.
- **Provisioned-fixture deployment accepted.** The manifest was installed,
  checked for readiness and idempotence, rolled back through the protected
  full-generation boundary, and reapplied on the supported Raspberry Pi.
- **Quantitative appliance characterization remains open.** The bounded
  listening tests below establish functional behavior; they do not establish
  statistical latency, transition-gap, resource, thermal, or soak limits.
- **Fresh-image installation and arbitrary upgrade paths are not claimed.**
  They were deliberately removed from this closure and remain future work.

This record is the publication-safe status addendum for the earlier
[release inventory](2026-08-26-coordinated-release-inventory.md),
[coordinated rollback rehearsal](../../deployment/acceptance/2026-08-26-coordinated-rollback.md),
[transition-baseline revalidation](../../deployment/acceptance/2026-08-26-transition-baseline-revalidation.md),
[TV input acceptance](../../deployment/acceptance/2026-08-26-tv-spdif-input.md),
[Bluetooth programme-source acceptance](../../deployment/acceptance/2026-08-26-bluetooth-programme-source.md),
[Bluetooth headset acceptance](../../deployment/acceptance/2026-08-26-bluetooth-headset-output.md),
[adaptive routing acceptance](../../deployment/acceptance/2026-08-26-adaptive-bluetooth-routing.md),
and [local product acceptance](../audio-orchestration/ACCEPTANCE_REPORT.md).
Those point-in-time records remain useful technical evidence, but their older
candidate, pending, and blocker wording is not the current release decision.

## Immutable coordinated identity

The retained release-mode input is
[`deployment/releases/open-cinema-0.3.2.yml`](../../deployment/releases/open-cinema-0.3.2.yml).
It is byte-for-byte identical to the manifest published by Open Cinema
`v0.3.2`; its SHA-256 is
`c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2`.
The public release contains 15 assets and GitHub reports it immutable. Failed
Open Cinema `v0.3.0` and `v0.3.1` attempts remain fixed and were not moved or
reused.

GitHub currently reports the source UI `v2.0.0` and decoder `v0.2.2` releases
as public, non-draft, and non-prerelease, but not release-immutable. Their
downloaded bytes and provenance were verified before publication and are
digest-identically mirrored by Open Cinema `v0.3.2`; appliance-mode URLs select
that immutable mirror rather than depending on mutable upstream release state.

| Project or retained upstream pin | Version and tag | Commit | Accepted publication workflow |
| --- | --- | --- | --- |
| Open Cinema | `0.3.2` / `v0.3.2` | `4ccda8e6165da6484ac0b7590ca6f03f8f4226f6` | [run 33021891788](https://github.com/k3rnL/open-cinema/actions/runs/33021891788) |
| WyrePlumber | `0.2.0` / `v0.2.0` | `9d55ab1200ee7c484743fe57339a1f56d2c9fcd1` | [run 33015311435](https://github.com/k3rnL/wyreplumber/actions/runs/33015311435) |
| Open Cinema UI | `2.0.0` / `v2.0.0` | `f6f437809da0c646ca29f8a9e4e2725a51378b41` | [run 33010953333](https://github.com/k3rnL/open-cinema-ui/actions/runs/33010953333) |
| PCM Auto Decoder | `0.2.2` / `v0.2.2` | `5856a5ef035618a7284a91f80bdd4ac24afe3427` | [run 33013745740](https://github.com/k3rnL/pcm-auto-decoder/actions/runs/33013745740) |
| CamillaDSP native PipeWire binary | `4.1.3` / `v4.1.3` | `05e9cfcdf43c0dfe078ed3feb8af4c8bd701fd74` | [upstream run 24210343960](https://github.com/HEnquist/camilladsp/actions/runs/24210343960) |
| pycamilladsp | `4.0.0` / `v4.0.0` | `fdc0d163e02dd73206a493402b43c83502ad83d7` | rebuilt and verified by [Open Cinema run 33021891788](https://github.com/k3rnL/open-cinema/actions/runs/33021891788) |

The accepted branch and tag gates for the four project releases were:

| Project | Accepted branch CI | Accepted publication run |
| --- | --- | --- |
| Open Cinema | [CI 33021740577](https://github.com/k3rnL/open-cinema/actions/runs/33021740577) on `master` | [Release 33021891788](https://github.com/k3rnL/open-cinema/actions/runs/33021891788) on `v0.3.2` |
| WyrePlumber | [CI and release 33015142690](https://github.com/k3rnL/wyreplumber/actions/runs/33015142690) on `master` | [CI and release 33015311435](https://github.com/k3rnL/wyreplumber/actions/runs/33015311435) on `v0.2.0` |
| Open Cinema UI | [CI 33010439755](https://github.com/k3rnL/open-cinema-ui/actions/runs/33010439755) on `master` | [Release 33010953333](https://github.com/k3rnL/open-cinema-ui/actions/runs/33010953333) on `v2.0.0` |
| PCM Auto Decoder | [native CI 33012341581](https://github.com/k3rnL/pcm-auto-decoder/actions/runs/33012341581) on `master` | [release 33013745740](https://github.com/k3rnL/pcm-auto-decoder/actions/runs/33013745740) on `v0.2.2` |

The root README of each released project was reviewed against its accepted
architecture, supported platforms, installation/runtime dependencies,
development and complete gate commands, artifact names, version convention,
and release workflow. Open Cinema's deployment README was additionally reviewed
for immutable appliance mode, explicit mutable development mode, readiness,
backup/rollback, processor topology, and the campaigns excluded below. No
known README mismatch remains in the accepted release scope.

### Final source-worktree boundary

The Open Cinema commits deliberately exclude seven preserved user entries:
the three staged-but-worktree-deleted `plugin/pipewire/**` files and the
`.openspec.yaml` plus `proposal.md` in each of
`additional-managed-link-shapes` and `multi-instance-audio-processing`.
The ignored private appliance inventory also remains controller-local and is
not publication evidence. WyrePlumber is at `ca32c740d5eb60093a3608545e5ab48015c216a4`
on the feature checkout (one commit ahead of that branch's remote tracking
point and equal to remote `master`), with `.codex/`, `oui.py`, the three named
API example documents, three example/demo scripts, and six scratch test scripts
still untracked and excluded. Open Cinema UI and PCM Auto Decoder are clean on
remote `master` at `394612720755f913da77dcc0ca6407595a77a32e` and
`94e25cecde7692c4f3cb862ae14703c95ae8faf7`, respectively; those two
post-release documentation/workflow commits do not redefine the accepted tag
identities above.

### Verified appliance artifacts

The hashes below are the selected AArch64/Trixie appliance bytes and their
portable provenance, not mutable source-tree identities.

| Artifact | SHA-256 |
| --- | --- |
| [`open_cinema-0.3.2-py3-none-any.whl`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open_cinema-0.3.2-py3-none-any.whl) | `6f4eec04e5b01c5aa50188c06c480c0c43b711417537d8175eb9d34854763d23` |
| [`open_cinema-0.3.2.tar.gz`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open_cinema-0.3.2.tar.gz) | `4ccd9c4624b75e6c50b9107bc56e2735872a138ee7f835e8481277909105bdc4` |
| [Open Cinema provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/provenance.json) | `6f66c0a819eacc3811f66f9d4928290dd7d1ff9fd0c6514884d00c270dc1f621` |
| [`wyreplumber-0.2.0-cp313-cp313-linux_aarch64.whl`](https://github.com/k3rnL/wyreplumber/releases/download/v0.2.0/wyreplumber-0.2.0-cp313-cp313-linux_aarch64.whl) | `cfb92cd7f407c87717f1f539ff3e04573d0cd2224ef744f8efb847a7938e05fd` |
| [WyrePlumber appliance-wheel provenance](https://github.com/k3rnL/wyreplumber/releases/download/v0.2.0/wyreplumber-0.2.0-cp313-cp313-linux_aarch64.whl.provenance.json) | `ade1107162e1624afa12e101dd4a542d402af372acffdb69999ad8d7a552e858` |
| [`open-cinema-admin-v2.0.0.tar.gz`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open-cinema-admin-v2.0.0.tar.gz) | `47d215f08a4740e47b7009abb6f0814f94d5330af222c4d98b90caf7ec057ea7` |
| [Administration UI provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open-cinema-admin-v2.0.0.tar.gz.provenance.json) | `19ce3f8ae3ccd83eab6e1457e26e582b523af83a5a07408082e84ef58f710b1c` |
| [`open-cinema-ui-v2.0.0.tar.gz`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open-cinema-ui-v2.0.0.tar.gz) | `91980a2c0ac72fe54ae04ba84340fddf89a5edeb3fc40b99cb296748e63d8560` |
| [On-box UI provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open-cinema-ui-v2.0.0.tar.gz.provenance.json) | `c7f39366661c9ba8c251a43bc79a76981153e095a898510a777ea38161c6a200` |
| [`pcm-auto-decoder-v0.2.2-debian-trixie-aarch64-unknown-linux-gnu.tar.gz`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/pcm-auto-decoder-v0.2.2-debian-trixie-aarch64-unknown-linux-gnu.tar.gz) | `7831af706c22198dbb531682264b7eedf88fc693c459d5f4c8c05e154d5e616e` |
| [PCM Auto Decoder provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/pcm-auto-decoder-v0.2.2-debian-trixie-aarch64-unknown-linux-gnu.tar.gz.provenance.json) | `1ebe283c5ce274ed6bbdc1481a5b8fc9a82098f5b133f4dc02ae40a031a84f49` |
| [`camilladsp-linux-pipewire-aarch64.tar.gz`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/camilladsp-linux-pipewire-aarch64.tar.gz) | `ca8b6cc32bda29bd7cb38f7bcda5fcc6f5e69690b3d0efaa23b6c3c05c45696c` |
| [CamillaDSP provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/camilladsp-provenance.json) | `8041db74691ae0ac68f87e21859c024c61c2aaeb5d47858f1e456319655f0387` |
| [`camilladsp-4.0.0-py3-none-any.whl`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/camilladsp-4.0.0-py3-none-any.whl) | `f0fc1186698a5591d5d39e095bd5f48e25b2def6f4e9fb7d2a29a00074f277e3` |
| [pycamilladsp provenance](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/pycamilladsp-provenance.json) | `9ea92a5400609c9d43b1bc89be7f4ea03420143f33315e03c68e9a8de80a4030` |
| [`open-cinema-coordinated-manifest.yml`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/open-cinema-coordinated-manifest.yml) | `c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2` |
| [`checksums.sha256`](https://github.com/k3rnL/open-cinema/releases/download/v0.3.2/checksums.sha256) | `c7c07331b13cd4d385b2cc0f228078a40a3c4858ed3e0f8706add794777780b8` |

The published runtime tuple remains immutable. Deployment and evidence
hardening discovered while closing the physical appliance belongs to later
source history; it does not retag or silently replace any `v0.3.2` artifact.

## Accepted Raspberry Pi appliance

| Boundary | Accepted identity |
| --- | --- |
| Hardware | Raspberry Pi 5 Model B Rev 1.1, 8 GB, with active cooling and the accepted power supply |
| Operating system | Debian 13 (Trixie), AArch64, kernel `6.18.39+rpt-rpi-2712` |
| Audio session | PipeWire `1.4.2`, WirePlumber `0.5.8`, BlueZ `5.82`, dedicated headless Open Cinema identity |
| Open Cinema stack | Open Cinema `0.3.2`, WyrePlumber `0.2.0`, management/on-box UI `2.0.0` |
| Processing | PCM Auto Decoder `0.2.2` with status protocol 2 and one stable output; CamillaDSP `4.1.3` with pycamilladsp `4.0.0` |
| Active route | One applied decoder/CamillaDSP graph, exactly 18 of 18 Open Cinema-owned PipeWire links |

After the controller and appliance rebooted, the retained immutable manifest
recovery apply reported `ok=302 changed=5 failed=0`; its immediate complete
rerun reported `ok=302 changed=0 failed=0`. The later recovery-boundary reseed
described below also ended with an ordinary `ok=302 changed=0 failed=0` run: no
processor stop, replacement recovery boundary, archive extraction, or
audio-graph mutation was needed for the identical candidate. Aggregate
preflight, installed component/contract probes, authentication and security
checks, the API/UI checks, processor correlation, and final readiness all
passed.

The 18-link topology comprised two selected-source channels into the adaptive
decoder, eight stable decoder-output channels into CamillaDSP, and eight
CamillaDSP channels to the main output. The looping debug adapter remained
available from persistent runtime media rather than package contents, and the
saved graph returned to exact convergence after deployment.

## Deployment requirement-to-evidence map

| Deployment delta requirement | Automated output or retained evidence | Closure result |
| --- | --- | --- |
| Supported appliance target is explicit and enforced | The finalized [appliance manifest](../../deployment/releases/open-cinema-0.3.2.yml), [compatibility matrix](../../deployment/compatibility.yml), aggregate preflight, and accepted hardware table above agree on Pi 5 8 GB, Trixie, AArch64, power, cooling, memory, storage, and service identity. | Accepted for this fixture only. |
| One coherent native audio runtime | Final apply installed the manifest-selected application, UI, binding, decoder, CamillaDSP, proxy, and state services; post-closure audit found all eight system and both user-session audio services active. | Accepted. |
| Immutable, version-correlated appliance inputs | The retained manifest pins every selected URL, digest, producer identity, platform, and contract; installed probes and the on-host manifest digest matched it. UI and decoder bytes resolve through the immutable coordinated mirror described above. | Accepted; explicit development mode remains mutable/non-release. |
| Consistent headless service identity | The declared ownership/runtime boundary in [group variables](../../deployment/inventories/group_vars/all.yml) and the [readiness permission probes](../../deployment/roles/readiness/tasks/main.yml) passed without a graphical login or competing session. | Accepted. |
| Static configuration and dynamic intent remain separate | The no-op apply did not mutate graph intent. Rollback and forward reapply preserved graph revisions, bindings, profiles, activation, overrides, and their semantic digest while [transition backup](../../deployment/roles/transition-backup/tasks/main.yml) retained static and dynamic state as distinct artifacts. | Accepted. |
| WirePlumber overlays preserve distribution ownership | The [PipeWire/WirePlumber role](../../deployment/roles/pipewire-wireplumber/tasks/main.yml) reconciles named Open Cinema fragments and service drop-ins; deployment tests reject whole-file ownership of distribution configuration. | Accepted. |
| Bluetooth roles are explicit | The retained [phone source](../../deployment/acceptance/2026-08-26-bluetooth-programme-source.md), [headset output](../../deployment/acceptance/2026-08-26-bluetooth-headset-output.md), and [adaptive fallback](../../deployment/acceptance/2026-08-26-adaptive-bluetooth-routing.md) hardware records cover discovery, takeover, and return to main output. | Functionally accepted; quantitative cycle timing remains open. |
| Managed processors expose stable native resources | Installed decoder/CamillaDSP contract probes passed; restart evidence rematched stable managed identities, and the final graph contained the exact 18-link decoder/DSP/output topology. | Accepted for one decoder and one CamillaDSP instance. |
| Correlated health and readiness | Aggregate readiness correlated the audio socket, WirePlumber contract, database/state services, processors, API, both UI builds, nginx, diagnostics, and installed identity; the final and post-closure results were `passed`. | Accepted. |
| Secure native management entry | The [product acceptance](../audio-orchestration/ACCEPTANCE_REPORT.md) and deployment readiness checks cover session login, CSRF, anonymous diagnostic rejection, authorization/redaction, configured network boundary, schema metadata, and read-only SSE transport. | Accepted for the controlled appliance network. |
| Ordered startup and recovery | The privacy-safe [restart matrix](../../deployment/acceptance/2026-08-25-service-restart-matrix.md) and [interrupted-transition record](../../deployment/acceptance/2026-08-25-interrupted-transition-recovery.md) retain boot, PipeWire/WirePlumber, processor, orchestrator, and partial-transition recovery evidence; the post-closure audit again found the full route converged. | Accepted. |
| Provisioned-appliance idempotence | Immediate final-manifest reruns reported `changed=0`, retained readiness, and did not stop processors or mutate the audio graph. | Accepted on the provisioned fixture; fresh-image and arbitrary-upgrade claims remain excluded. |
| Coordinated rollback boundary | The privacy-safe [rollback rehearsal](../../deployment/acceptance/2026-08-26-coordinated-rollback.md), [retained-boundary revalidation](../../deployment/acceptance/2026-08-26-transition-baseline-revalidation.md), forward reapply, state/audit correlation, checksum-verified selection, explicit recovery-boundary reseed, and post-acceptance window closure cover failure retention, exact restore, wheel/source binding variants, malformed historical data, and recovery procedure. | Accepted; one verified mutable and one verified protected recovery point retained. |

## Protected rollback and forward recovery

| Recovery identity | Retained identity and verification |
| --- | --- |
| Active mutable recovery point | A private schema-2 manifest/READY snapshot of the accepted `open-cinema-0.3.2` generation, including its application/venv, database, dynamic intent, both UIs, managed static state, processor binaries/runtime, and installed manifest SHA-256 `c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2`. |
| Protected baseline | Privacy-safe identity `protected-first-release-replacement`: a private full-generation manifest/READY boundary whose receipt, capsule digest/size, complete artifact set, nested archives, and read-only SQLite integrity were reverified before mutation. Its appliance identifier and retrieval locator are intentionally not public. |

The immutable-candidate rehearsal restored the selected protected generation
as one boundary and passed with `ok=120 changed=14 failed=0`. Forward reapply
of `v0.3.2` then passed with `ok=294 changed=3 failed=0`; its immediate rerun
was a no-op at `ok=294 changed=0 failed=0`. Normal readiness passed in both
directions.

The rollback verifier checked every declared regular artifact and checksum
before mutation. The restore boundary covered the application environment,
web builds, processor binaries and generated configuration, managed static
state, installed manifest, SQLite database, and user-owned audio intent. The
intent digest matched after both directions across graph definitions and
revisions, activations, endpoint bindings, processor profiles, managed
adapters, and manual overrides. The audit sequence did not regress; only
permitted reconciliation activity could append to history.

Transition-manifest schema 2 represents wheel-only WyrePlumber installations
without inventing a redundant source archive. In appliance mode the exact
binding is already inside the archived application environment and must pass
an installed-version/import/contract probe before that generation is accepted
as recoverable. A source archive remains required for a development generation
that was installed from a separate source tree. The rollback reader continues
to accept the older schema-1 full-generation boundary and validates the READY
record against the schema-specific artifact set.

The first explicit rollback-window closure completed with
`ok=301 changed=6 failed=0` and removed 27 stale experimental bundles. Later,
the checksum-selection hardening correctly identified that its nominal mutable
entry was an older partial directory without a manifest, READY marker, or full
archive set. Readiness withdrew the correlated closed-marker claim rather than
guessing that directory was recoverable; the protected baseline remained
verified and untouched.

An explicit, default-off recovery maintenance transition then snapshotted the
currently accepted `v0.3.2` generation through the normal quiesce, complete
backup, install, contract-gate, and readiness path. Only after both the new
schema-2 mutable bundle and protected baseline passed every regular-file and
digest check did closure delete the single already-non-restorable partial
directory and write a replacement window record. That run reported
`ok=351 changed=29 failed=0`. The first ordinary run refreshed only the
readiness marker; the next ordinary run was a full no-op at
`ok=302 changed=0 failed=0`.

The final audit found exactly two verified and zero rejected bundles, with one
selected mutable recovery point and one protected exception; both correlate to
the window record. It also found the installed appliance-mode manifest at the
finalized digest, aggregate readiness `passed`, all eight system and both user
audio-session services active, and all 18 graph-owned links present. The 27
older stale bundles and the later malformed partial directory are not
individually recoverable; the two retained verified recovery points remain
available.

One earlier operator invocation inherited the private development-mode override
and was rejected by the release safety gate before application, UI, processor,
database, or graph mutation. The appliance inventory was then corrected to
select the immutable retained manifest by default, and the successful closure
above used that exact release input. This is retained as evidence that a
development identity cannot silently pass as the accepted appliance release.

The first coordinated release still depends on its protected replacement
baseline because the older public tuple cannot restore this native PipeWire
stack. That recovery material remains private and retained; this public record
intentionally contains no retrieval locator or appliance-specific recovery
identifier. A later release must use the immediately previous finalized
coordinated manifest instead. Operators must continue to select rollback data
explicitly, verify it before mutation, and require a fresh readiness result
before accepting either direction.

## Functional audio evidence versus quantitative benchmarks

The owner accepted these bounded, real-hardware functional checks:

- TV PCM traversed the physical SPDIF/I2S input, adaptive decoder, native
  CamillaDSP processing, and main output and was audible on the connected
  speakers.
- A supported encoded movie input decoded through the same stable processor
  output and produced the expected programme audio. Unsupported formats remain
  explicit rather than being presented as successful decode paths.
- After the decoder buffering correction, the owner reported that visible
  lip-sync delay was gone or materially reduced. One aligned diagnostic capture
  measured 64 ms from raw TV input to CamillaDSP output, but that single
  internal-path observation is not an end-to-end display-to-speaker latency
  distribution.
- A Bluetooth phone automatically played through the main speakers; connecting
  the accepted headset moved programme audio to it; disconnecting the headset
  restored the main output. The user confirmed the complete TV, Bluetooth, and
  headset policy as working without graph edits.
- The final headset direction changes were manually observed at about four
  seconds. A later encoded-format transition included a short audible blank
  estimated by the user at roughly 0.5–1 second. Neither observation used
  calibrated capture or enough repetitions to support a percentile claim.

These checks close the functional smoke boundary for this provisioned fixture.
The subsequent
[benchmark harness and baseline characterization](../../deployment/benchmarks/results/2026-08-27-pi5-baseline-characterization.md)
matched the supported fixture and completed a fresh identity-bound one-second
sample plus 60-second warm-up and measured samples without loss or retry. The
run retained three valid attempts, zero invalid attempts, the exact runner,
adapter, workload-driver and contract hashes, and a detached digest covering
55 redacted export files. An older pre-identity diagnostic run is superseded
and contributes no accepted statistic. This characterization does **not**
close the separate benchmark plan. Still
unmeasured are calibrated end-to-end and per-stage latency distributions,
p50/p95/p99 audible transition gaps, at least 20 headset cycles, the complete
repeated codec matrix, CPU/memory/thermal and xrun limits under load,
fault-recovery timing, boot and storage effects, and long-duration soaks.

## Closure decision and continuing boundaries

The `v0.3.2` publication and deterministic deployment of the already
provisioned Raspberry Pi 5 fixture are accepted. Recovery stays fail-closed:
missing or drifted protected state blocks mutation, a failed candidate retains
diagnostics and the previous live boundary, and no workflow guesses a rollback
generation.

This decision deliberately leaves the following outside its claim:

- fresh-image installation and generalized upgrade reproducibility;
- Raspberry Pi models, memory tiers, distributions, or architectures beyond
  the supported Pi 5 8 GB Trixie/AArch64 fixture;
- unsupported encoded formats or arbitrary processor combinations; and
- the quantitative campaigns tracked by the appliance benchmark change.

Those limitations are future qualification work, not hidden failures of the
accepted coordinated release or its bounded functional appliance smoke.
