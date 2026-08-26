# Orchestration database concurrency

The first appliance release uses SQLite with write-ahead logging (WAL), a
five-second bounded busy timeout, normal synchronous mode, foreign keys, and a
1,000-page automatic checkpoint. Every Django connection receives the same
policy. In-memory test databases cannot use WAL and are the only exception.

The API and singleton orchestrator may read concurrently. Write transactions
must contain database reads and writes only: runtime snapshots, WirePlumber
calls, Redis publication, processor communication, retries, and sleeps happen
outside `transaction.atomic()`. Optimistic versions on activations and logical
endpoints prevent a delayed request from overwriting newer desired state.

## PostgreSQL promotion threshold

The release soak test must measure transaction duration, time waiting for a
write lock, `database is locked` failures, reconcile throughput, and WAL size on
each supported Raspberry Pi tier. PostgreSQL becomes required before the next
release if any supported canonical workload has one of these results over a
30-minute run after a warm-up period:

- any operation exhausts the configured five-second busy timeout;
- write-lock wait p99 exceeds 250 ms or write-transaction duration p99 exceeds
  100 ms;
- database waiting consumes more than 10% of reconciliation wall time; or
- WAL checkpoints repeatedly exceed 100 MiB because readers prevent bounded
  checkpoint progress.

Those are release gates, not tuning suggestions. If they are crossed, adding a
longer SQLite timeout is not considered a production fix; the measured workload
must move to PostgreSQL and rerun the same acceptance suite.

## Retention and cleanup

The hourly `api.cleanup_audio_orchestration_data` job removes operational
history in bounded transactions. Plans and their completed transition journals
default to 30 days, audit events to 30 days, raw diagnostics to 24 hours, and
superseded runtime projections to 24 hours. All durations and the batch size are
deployment settings.

The settings are `OPEN_CINEMA_AUDIO_PLAN_RETENTION_DAYS`,
`OPEN_CINEMA_AUDIO_AUDIT_RETENTION_DAYS`,
`OPEN_CINEMA_AUDIO_DIAGNOSTIC_RETENTION_HOURS`,
`OPEN_CINEMA_AUDIO_RUNTIME_PROJECTION_RETENTION_HOURS`, and
`OPEN_CINEMA_AUDIO_RETENTION_BATCH_SIZE`. The same cleanup can be run manually
with `python manage.py cleanup_orchestration`; it is idempotent.

Cleanup never deletes graph definitions or revisions. It also excludes every
plan referenced as the current or previous plan by `AppliedPlanState`, retaining
the active state and one database-backed rollback target even when they are
older than the configured window. Current runtime projections and plans with an
unfinished transition are retained. Runtime projections remain diagnostic
caches; neither they nor Redis become desired-state authorities.
