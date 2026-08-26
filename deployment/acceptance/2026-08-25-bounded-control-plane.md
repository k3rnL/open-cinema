# Bounded control-plane state — 2026-08-25

Target: Raspberry Pi 5 8 GB, limited-live rollout.

The appliance now declares and continuously verifies these limits:

| Component | Accepted policy |
| --- | --- |
| Redis | 128 MB `maxmemory`, 192 MB systemd `MemoryMax`, 256 clients, `noeviction`, no RDB saves, no AOF |
| SQLite | WAL, 5 s busy timeout, synchronous `NORMAL`, 1000-page automatic checkpoint |
| Celery worker | concurrency 1, prefetch 1, recycle after 100 tasks, 256 MB `MemoryMax` |
| Celery beat | 128 MB `MemoryMax` |
| Celery results | ignored for the retention workload; 3600 s expiry remains a defensive bound |
| Orchestration retention | plans 30 days, audit 90 days, diagnostics/runtime projections 24 hours, 1000-row batches |

The Redis override is a named systemd drop-in and leaves the distribution unit
and configuration file intact. Redis holds only reconstructable runtime/event
state; the authoritative desired graph remains in SQLite. A Redis restart
therefore repopulates its bounded projection without changing live audio intent.

After deploying the limits, the readiness transaction validated live Redis
configuration, unit memory ceilings, Django/Celery settings, SQLite PRAGMAs,
the active graph, and all previous appliance checks. The first coordinated run
ended `ok=124 failed=0`; its exact no-change rerun ended
`ok=119 changed=0 failed=0`.
