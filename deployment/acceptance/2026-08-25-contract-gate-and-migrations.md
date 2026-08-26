# Candidate contract gate and bounded migration acceptance

Date: 2026-08-25

Host: Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian 13 `trixie`, aarch64

Release stage: experimental `limited-live`, exact graph allowlist

## Implemented boundary

The site play fingerprints the coordinated manifest and, for a local
development deployment, the synchronized Open Cinema, WyrePlumber, management
UI, and decoder source trees. A candidate whose digest has not already passed
the installed gate stops the previous controller before candidate files change.
The first candidate environment permits observation and shadow resolution but
forces processor management and live reconciliation off.

After the UI and decoder are installed, the gate checks:

- PipeWire, WirePlumber, Python, Redis, SQLite, nginx, BlueZ, FFmpeg,
  CamillaDSP, and decoder version ranges;
- WyrePlumber orchestration and runtime-value contracts;
- backend audio API, desired-graph, and orchestration schema versions;
- decoder status protocol v2;
- processing-plugin and processing-driver contracts, including discovery
  failures and incompatible installed plugins;
- the management UI's packaged audio API and DTO contract;
- the installed coordinated-manifest digest.

Only a zero-failure aggregate result renders the selected processor/live flags.
The passed candidate digest is retained at
`/var/lib/open-cinema/deployment-diagnostics/contract-gate-result.json` with
mode `0600` and ownership `opencinema:opencinema`.

## Positive, negative, and recovery evidence

The first complete candidate run passed the installed contract gate and full
end-of-play readiness. An injected processing-contract incompatibility then
produced the expected play failure:

```text
failures=["acceptance injection: incompatible processing contract"]
PLAY RECAP: ok=46 changed=7 failed=1
```

While rejected, the appliance state was:

```text
open-cinema.service: active
open-cinema-orchestrator.service: active
nginx.service: active
redis-server.service: active
OPEN_CINEMA_AUDIO_PROCESSOR_MANAGEMENT=false
OPEN_CINEMA_AUDIO_LIVE_RECONCILIATION=false
GET /admin/: 200
contract-gate-result.json: status=failed, mode=0600
```

A clean contract-gate rerun passed and restored the accepted limited-live
stage. The final installed evidence was:

```text
contract gate: passed, failures=0
candidate digest: recorded and matched by the immediate idempotency rerun
readiness: passed, rollout=limited-live, failures=0
processor management: true
live reconciliation: true
```

An immediate complete rerun did not stop or restart audio and reported:

```text
PLAY RECAP: ok=288 changed=0 failed=0
```

This proves the candidate gate is fail-closed without sacrificing an unchanged
playbook's idempotency.

## Migration evidence

Every migration subprocess is bounded with `timeout`, a TERM signal, and a
separate kill grace. Before applying a pending transition, deployment runs
SQLite `PRAGMA quick_check`, asks Django's migration loader to verify consistent
history and target leaf versions, stops the application generation, and creates
an online SQLite `.backup` in the coordinated rollback bundle. Rescue output is
correlated into one private JSON result with the plan, schema and integrity
preflights, backup result, migration output, timeout policy, rollback identity,
and matching service log path.

The exact production command shapes were rehearsed against an isolated
temporary database on the Pi. The source and backup both passed integrity and
contained the same complete migration history:

```text
source_check=ok backup_check=ok source_migrations=75 backup_migrations=75
```

The live database was not modified by this rehearsal. Local verification also
passed all 796 backend tests and the Ansible site syntax check.
