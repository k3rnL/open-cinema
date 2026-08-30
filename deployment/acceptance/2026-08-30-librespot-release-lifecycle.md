# Librespot published-release lifecycle acceptance — 2026-08-30

Status: **passed for the clean local contract fixture**.

This record covers release provenance and plugin-platform lifecycle behavior.
Raspberry Pi audio and performance acceptance remain separate in the frozen
appliance plan.

## Published release identity

- Plugin: `open-cinema.librespot` version `0.1.8`
- Source commit: `d50279e434adb6710a9562de76b1260f68edf938`
- Tag: `v0.1.8`
- Release workflow: `33315590811`
- Release state: public, non-prerelease, and GitHub immutable
- Librespot: `0.8.0` from source commit
  `d36f9f1907e8cc9d68a93f8ebc6b627b1bf7267d`
- Option contract: 51 options, digest
  `64c3ec10242b4fdcc5c0bd90c2b08a861d6c3a39cc223f94f965b7526bba5b2c`

| Platform | Wheel SHA-256 | Size |
| --- | --- | ---: |
| Linux ARM64 | `f75bcde83c71aa227b8a894f7d27b84dede3cf3968d376d54ee3e987033632ed` | 9,379,688 bytes |
| Linux x86-64 | `800188da28447ee34fb575b41c880f30747867f7a669f0189d55b422ab47b8f7` | 9,586,179 bytes |

Both release wheels passed checksum verification, embedded-binary inspection,
and clean downloaded-wheel installation against the pinned Open Cinema host on
their native architecture. The first-party catalogue records the exact HTTPS
URLs, platform selectors, compatibility, permissions, and digests.

## Marketplace lifecycle

A fresh migrated Open Cinema fixture with editable plugins disabled exercised
the public catalogue path and downloaded bytes:

| Operation | Result |
| --- | --- |
| Install | Candidate generation activated; application restart required; startup verification succeeded with version `0.1.8`. |
| Enable / disable | Both completed hot; desired and observed states converged to started and stopped respectively. |
| Same-version update | A new generation was built from the public wheel; restart verification succeeded. |
| Invalid artifact digest | Download failed closed before generation activation; current pointer, installed version, provenance, and update token were unchanged. |
| Uninstall | Plugin-free generation activated; restart verification succeeded and the runtime entry point was absent. |
| Reinstall | Public wheel installed again; restart verification succeeded and the runtime was healthy and stopped by default. |

Startup initially exposed that generic entry-point discovery replaced stronger
catalogue acquisition provenance. The synchronization join now preserves the
existing URL, digest, release version, and resolved revision when the observed
distribution identity and version are unchanged. A regression test covers this
boundary, and the complete lifecycle was rerun through update and reinstall
with exact provenance retained.

## Verification

- Plugin release workflow: passed, including x86-64 and ARM64 downloaded-release smoke jobs.
- Catalogue, operation, overlay, and runtime focused suite: 54 tests passed before lifecycle execution.
- Provenance regression and related lifecycle suite: 38 tests passed.
- OpenSpec strict validation: passed.

No source build occurred during marketplace acquisition. No private inventory,
network, credential, secret, or temporary-path value is retained in this
record.
