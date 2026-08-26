# Service restart matrix — 2026-08-25

Status: **accepted for the experimental limited-live Raspberry Pi appliance**.

This matrix exercised the deployed active graph without a graphical login or a
manual Apply. Every disruptive case had to finish with the same two endpoint
candidates, four processor nodes, 18 `open-cinema.orchestrator` links, a
successful transition journal, and `AppliedPlanState.status=converged` with no
last error.

## Individual services

| Restart | Evidence | Result |
| --- | --- | --- |
| nginx | main PID `1248` → `1839`; `/admin/` and `/ui/` returned 200 | passed |
| Django/Gunicorn | main PID `1145` → `1865`; direct login response returned 200 after worker readiness | passed |
| Redis | main PID `1112` → `1999`; `PONG`; API and all 18 audio links remained available | passed |
| decoder | main PID `1277` → `2056`; stable processor identity rematched; journal generation 9 succeeded with 18 entries | passed |
| CamillaDSP | main PID `1292` → `2663`; runtime node IDs changed from `90/91` to `108/110`; journal generation 10 succeeded with 18 entries | passed |
| WirePlumber | main PID `1162` → `2750`; Wondom remained discoverable and all 18 links remained present | passed |
| PipeWire | main PID `5633` → `7878`; a new runtime generation, decoder process, CamillaDSP process, and 18-link graph were created | passed after recovery fixes |
| orchestrator | controller PID changed; connection-owned links were recreated from persisted desired state | passed |

The Gunicorn unit becomes `active` before its workers accept requests, so the
test deliberately used an HTTP state poll rather than treating systemd active
state as application readiness. This remains relevant to the broader readiness
aggregation tasks.

## PipeWire recovery defects found and corrected

The first PipeWire-only restart exposed two independent gaps:

1. A native runtime connection could become silently stale without delivering a
   closed event. The orchestrator now performs a cheap, five-second WirePlumber
   core round-trip. Failure enters the existing bounded reconnect path and
   obtains a fresh authoritative snapshot. Full captures remain mandatory at
   startup, after continuity loss, and after owned mutations; event queue
   overflow or a sequence gap also requests a resnapshot.
2. CamillaDSP can keep its process and control socket alive while its PipeWire
   nodes remain attached to the dead server. After a short registration grace,
   the processor controller now recycles only graph-assigned, orchestrator-owned
   instances whose complete stable node identities are absent. The recycle is
   bounded and occurs before route mutation.

On the accepted repeat at `21:37:20+02:00`, the orchestrator detected the stale
runtime in the same second, captured the replacement runtime at `21:37:21`, the
decoder restarted at `21:37:22`, and CamillaDSP was recycled at `21:37:24`.
Applied journal generation 14 then completed with 18 entries and no error.

After replacing the expensive periodic capture with the core round-trip, a
second accepted restart began at `22:30:12.962+02:00`. The old graph had zero
owned links after 120 ms, the connection failure was reported at
`22:30:13.044`, and the replacement connection captured its initial snapshot at
`22:30:13.338`. Decoder and CamillaDSP recycling completed at
`22:30:15.779` and `22:30:16.084`; all 18 links were present 8.721 seconds after
the restart request. The controller PID did not change, the Redis projection
ended connected with 18 links, and all three services remained active.

## Bounded controller shutdown follow-up

One deployment restart found the old controller blocked behind a `systemctl`
helper until its 20-second stop timeout. The unit used `KillMode=mixed`, which
signalled only the main process while the helper could wait on the same systemd
transaction that was stopping its parent unit. The unit now uses
`KillMode=control-group`, and decoder/CamillaDSP systemctl calls have explicit
five-second subprocess timeouts. The repeated controller restart stopped
cleanly from `22:29:30.459` to `22:29:30.835` (376 ms), without a timeout,
SIGKILL, or orphaned adapter process.

The installed unit graph also confirms the intended readiness chain. PipeWire's
user unit pulls its socket and WirePlumber, while WirePlumber orders after
PipeWire. The orchestrator orders after Redis and `user@999.service`, then gates
startup on the exact PipeWire socket, Redis `PONG`, and its Django/configuration
check. Managed decoder and CamillaDSP instances order after the orchestrator,
exist only when their per-instance environment is present, and independently
gate on the same PipeWire socket. Gunicorn and the bounded Celery workloads
order after Redis; nginx can continue serving the management UI and diagnostics
when the API or audio runtime is degraded. An automated deployment test rejects
sleep/pause-based correctness outside the measurement harness. Together with
the accepted reboot and restart cases, this completes task 6.1.

Before activation, Ansible now runs `systemd-analyze verify` over the application
units and the headless PipeWire/WirePlumber user units. CamillaDSP and decoder
templates retain their existing verification. End-of-play readiness also opens
an independent WyrePlumber connection, performs a core sync, captures a native
runtime snapshot, and requires a connected positive generation. These checks
and the live restart evidence complete tasks 6.2 and 6.3 for the current
experimental appliance.

End-of-play readiness now also verifies persisted orchestration state rather
than relying on active processes alone. It opens the database, rejects pending
migrations, requires every enabled graph's applied plan to be converged at the
current desired-state version with no retained error, and rejects pending or
running transition journals. It separately requires exactly one orchestrator
process and matches that PID against the exclusive controller lock document.
On the accepted deployment, the readiness command reported one active graph,
one converged graph, zero pending migrations, and zero unfinished transitions;
PID `45413` matched the lock owner. An immediate identical Ansible rerun ended
with `ok=80 changed=0 failed=0`. This completes task 6.4.

The readiness role now emits a single correlated JSON result containing the
release-manifest digest, complete component identities, named contract results,
service states, controller identity, processor versions, and persisted/runtime
convergence facts. A harmless missing-hardware-fixture injection exercised the
failure path after all normal checks passed: the retained result named
`__OPEN_CINEMA_MISSING_FIXTURE__`, preserved the exact assertion, linked its
timestamped service log, and showed all follow-up service, WirePlumber, Redis,
orchestration, runtime-projection, and API probes healthy. A normal run restored
the passing result, and its immediate repeat completed with
`ok=51 changed=0 failed=0`. This completes task 6.7.

LAN-level web readiness now uses `192.168.1.37`, not only loopback. It loaded
both UI entry points and all five referenced JavaScript, CSS, and SVG assets;
this exposed and removed the stale Vite placeholder icon before acceptance. It
then proved anonymous diagnostics return 403, authenticated through the native
CSRF-protected `admin` session, validated API/schema v1 and privileged
diagnostics through nginx, and opened the SSE endpoint with a stale graph
cursor. The stream returned `Open-Cinema-Event-Gap: true` and a replacement
snapshot before logout. The exact UI/readiness play rerun ended with
`ok=71 changed=0 failed=0`. This completes task 6.6.

## Relevant combinations

Restarting the complete `user@999.service` session changed its manager PID from
`1124` to `8089`. PipeWire and WirePlumber returned without a login, the
orchestrator reconnected at `21:38:02`, and it recycled decoder and CamillaDSP at
`21:38:04` and `21:38:05`. Journal generation 15 converged with all 18 links.

The selected database is embedded SQLite rather than a separately restartable
daemon. Its equivalent database-restart case therefore checked
`PRAGMA quick_check=ok` and `journal_mode=wal`, restarted every persistent
database consumer (`open-cinema`, orchestrator, Celery, and Celery beat), and
required fresh handles plus API and audio readiness. The API returned 200,
Redis returned `PONG`, a second quick check returned `ok`, and journal generation
16 converged with 18 entries and no last error.

These tests cover task 6.9 for the currently selected SQLite deployment.
Power-loss-style controller interruption is covered separately in
`2026-08-25-interrupted-transition-recovery.md`.
