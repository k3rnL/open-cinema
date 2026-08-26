# Transition rollback baseline revalidation

Verification time: 2026-08-26T19:45:43Z

Fixture: Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian 13 `trixie`,
`aarch64`

Scope: verification of the appliance-local bundle named by
`2026-08-26-coordinated-rollback.md`. No service, live runtime resource,
database payload, or retention record was changed. Remote output was passed
through the required Bluetooth-address redaction filter. The SQLite integrity
probe's nominal read-only open briefly created `db.sqlite3-shm` and an empty
`db.sqlite3-wal` beside the WAL-mode snapshot. Both were absent in the initial
inventory, were removed immediately by exact path, and the final file inventory
and database SHA-256 were verified to match their original state.

## Exact retained boundary

The expected bundle is still present at:

```text
/var/lib/open-cinema/rollback/transition-20260826T002452-ebd7b2b6d014
```

Its manifest identifies:

```text
schema: 1
kind: open-cinema-coordinated-transition-backup
bundle id: transition-20260826T002452-ebd7b2b6d014
restore strategy: coordinated-full-generation
previous candidate: d28911c2f9d7959d650c4b4a3234cd228de67c80e51e7cc05ba5a8977cac26f3
candidate: ebd7b2b6d014478de99f262215b030491cc8696c211d8662d50932384972bc85
release-manifest SHA-256: bb3473c9962db902fb29b7d1ad6b151e5ae41d7ec5c5d236860e605c1a1c58a2
audio-intent SHA-256: bb39f864e6e33338b992a01bd9b2169bab4421ae7cc8ef209fa7851853d09d33
```

The root and nested inventory directory are owned by
`opencinema:opencinema` with mode `0750`. Every retained file is owned by the
same identity with mode `0600`; recursive mode checks found no exceptions. The
parent `/var/lib/open-cinema` and rollback root are also private `0750`
directories.

## Files and integrity

The manifest, `READY` marker, and live bytes agree on exactly these nine
restore artifacts:

| Artifact | SHA-256 | Read-only verification |
|---|---|---|
| `application.tar.gz` | `ee867765a792437009a55a85614e8dd413b889f37b83c71732f2b1b8ab4e3613` | readable, 22,416 members |
| `db.sqlite3` | `0935849a87c9848359b2d353ea69668c48b2bfc7c783287653063df8e48e1396` | `PRAGMA quick_check` returned `ok` |
| `dynamic-state.json` | `0469a79b17a9718e4bdfbfb8eba70dc4c526d8f7530af7c8125548892a31b394` | digest valid |
| `managed-static.tar.gz` | `81aac0da2fb6e0695b567e96e9622a40f4fe01a1858f93aa27e6df0fd4826313` | readable, 20 members |
| `processor-binaries.tar.gz` | `341f66179a64b8bec09c0f0f4abc59d6b4309836105f30eef372dcdf7fbf69cc` | readable, 2 members |
| `processor-runtime.tar.gz` | `44fab18ecae6af0c39028312f31a2b5296a9ce270cc0f6af75c38fd5d1948efa` | readable, 5 members |
| `release-manifest.yml` | `bb3473c9962db902fb29b7d1ad6b151e5ae41d7ec5c5d236860e605c1a1c58a2` | digest correlated by the bundle manifest |
| `web.tar.gz` | `17d04f3df65bf8d4b420aef8b4c2374f112d4117f2cb42ed870cae6b45b01275` | readable, 12 members |
| `wyreplumber.tar.gz` | `0928feb35d96f723d730831615404e8c72c2f4140bcbc6cdde242a6417704159` | readable, 290 members |

All six tar archives passed a complete table-of-contents read. No archive had
an absolute member or a member containing parent traversal. The bundle also
retains the private transition manifest and marker, the prior contract-gate
and readiness results, and controller snapshots of inventory, group variables,
compatibility data, and the candidate manifest. The inventory directory has
one historical `rollout-stages.yml` snapshot in addition to the files required
by the current restore role; it is inert retained evidence and not a restore
input.

The remaining nine private metadata/evidence files complete the observed
18-file inventory:

| File | Observed SHA-256 |
|---|---|
| `manifest.yml` | `8bb5c2b83c0ef8c16844aa10d577cfd6b91c814bf968a9372850ee72852a073b` |
| `READY` | `9ad6568efb9be626db9e000d44e0bc24f64c6648637a441e75595ab6d829525f` |
| `contract-gate-result.json` | `23f9880b4bcb5dd1180bfe71541d14ea563d61dab438bf0bf608b2749bdd4d1f` |
| `readiness-result.json` | `fa2edd6b26f9481d5895f970076737cc057cb3e4675f4edded4edd6fdd90d357` |
| `inventory/inventory.yml` | `5778bab07c3de4523c29aaa429a1beda3821041407dd675f41db9b9ab797a1d0` |
| `inventory/group-vars-all.yml` | `b05a9dbea4605221f5f001a9c68c63b14f8d09e414fff376fbd4531d946d0182` |
| `inventory/compatibility.yml` | `26fd806f63b0f4526b7fa1aab4d83380d747765aab11a99129763648227afdd5` |
| `inventory/candidate-release-manifest.yml` | `bb3473c9962db902fb29b7d1ad6b151e5ae41d7ec5c5d236860e605c1a1c58a2` |
| `inventory/rollout-stages.yml` | `f373365d96d218a6ad99d24a58a05687eb13e851840ff454b328df85283ac565` |

Only the nine restore artifacts in the first table are committed by both the
bundle manifest and `READY`; the hashes in this second table are revalidation
observations, not claims that the older bundle schema protects those metadata
files transitively.

## Previous-generation identity

The retained release manifest is
`open-cinema-experimental-2026-08-25`, status `experimental`,
`promotable: false`. It records Open Cinema `0.2.0`, WyrePlumber `0.1.0`, the
management UI `1.0.5-development`, and PCM Auto Decoder `0.1.4` as
`local-dirty-tree` with `immutable: false`. CamillaDSP `4.1.3` is the one
component recorded as an immutable upstream release asset. The old manifest
does not contain the newer explicit `input_mode` field or a runtime-profile
value.

The full-generation bundle nevertheless freezes the exact application,
binding, UI, decoder/processor, configuration, and database bytes behind the
validated content digests. Together with the successful exact rollback and
forward rehearsal in `2026-08-26-coordinated-rollback.md`, it remains a valid
temporary, deployment-owned known-restorable baseline for this one appliance.

## Retention decision and blockers

This verification does **not** complete coordinated-release task 9.2 or the
immutable-candidate deployment rollback tasks:

- the only verified copy is appliance-local, so it is not independently
  downloadable or resilient to appliance/storage loss;
- its internal component identities are mutable development-tree identities,
  not published immutable inputs;
- neither `open-readiness.yml` nor `rollback-window.yml` currently pins this
  exact bundle;
- the deployment default keeps rollback-window closure disabled, but a future
  accepted run with `open_cinema_close_rollback_window=true` intentionally
  deletes every bundle except the newly selected one.

Before candidate promotion, preserve a digest-verified copy outside the
appliance (or publish an equivalent immutable replacement), record its durable
location and retention policy, and prevent rollback-window closure from
pruning this exact bundle until the new immutable release has passed appliance
smoke and become the next known-good boundary. Until then, release promotion
must remain blocked and the OpenSpec checkboxes remain open.
