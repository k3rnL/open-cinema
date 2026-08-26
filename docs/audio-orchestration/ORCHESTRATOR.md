# Dedicated orchestration process

`open-cinema-orchestrator` is the only process entry point intended to own live
audio orchestration. It initializes the same Django settings and models as the
web application, but it does not run inside Gunicorn or a Celery worker.

Development startup:

```bash
uv run open-cinema-orchestrator
```

Configuration/startup validation without entering the service loop:

```bash
uv run open-cinema-orchestrator --check
```

The process handles `SIGINT` and `SIGTERM` as graceful stop requests. Its
singleton controller lock ensures only one process owns live orchestration. A
second process reports `standby` with the active owner metadata and retries;
lock access failures report a distinct `failed` diagnostic.

The default lock is `/tmp/open-cinema-orchestrator-<uid>.lock`. Production
deployment should set `OPEN_CINEMA_ORCHESTRATOR_LOCK_PATH` to a service-owned
path under `/run/open-cinema/`.

While active, the process owns one WyrePlumber connection and atomically
replaces an immutable, monotonically versioned in-memory world snapshot. Redis
receives only a bounded, expiring UI projection; Redis is never read back as
the source of runtime truth. Projection size, endpoint count, key, and TTL are
configured through the `OPEN_CINEMA_RUNTIME_REDIS_*` settings.

Desired-state wake-ups use a separate lossy Redis Pub/Sub channel. The
orchestrator always polls every activation's monotonic desired-state version
from the database, including when no notification arrives, so Redis loss cannot
strand a committed graph activation.

Runtime, plan, progress, processor, and health updates use a bounded Redis
Stream with an approximate maximum length, per-event byte limit, and expiry.
Publishing failure is diagnostic only and never rolls back database or
in-memory state. Consumers recover from durable state and current snapshots;
the stream is not an event-sourced authority.

The in-process reconciliation queue is separately bounded by
`OPEN_CINEMA_AUDIO_RECONCILIATION_MAX_PENDING_GRAPHS` and
`OPEN_CINEMA_AUDIO_RECONCILIATION_MAX_CAUSES`. Repeated causes for one graph are
coalesced onto its newest generation. Exhausting the distinct-graph budget is an
explicit overflow and triggers recovery; it never creates an unbounded backlog.

## Lifecycle and recovery

Readiness requires the authoritative database plus a coherent PipeWire and
WirePlumber observation. Redis is optional: an outage reports `degraded` while
database polling and audio runtime observation continue. Liveness remains true
while the process is starting, ready, degraded, reconnecting, or stopping, and
becomes false only after it has stopped or encountered a terminal failure.

Every new WirePlumber connection starts with a full coherent snapshot before
pending desired state is scheduled. A closed runtime queue or failed initial
snapshot discards the connection and retries with bounded exponential jitter.
The wait is interruptible, so `SIGINT` and `SIGTERM` still stop promptly. The
defaults can be tuned with:

- `OPEN_CINEMA_RECONNECT_INITIAL_SECONDS` (default `0.25`)
- `OPEN_CINEMA_RECONNECT_MAX_SECONDS` (default `30`)
- `OPEN_CINEMA_RECONNECT_MULTIPLIER` (default `2`)
- `OPEN_CINEMA_RECONNECT_JITTER_RATIO` (default `0.2`)

Database failures make the orchestrator unready and pause new desired-state
scheduling, but the same runtime connection remains observable and database
polling retries on the next loop. Redis Pub/Sub reconnects lazily; lost wake-ups
remain harmless because the database polling interval is authoritative.
