# Admin observation polling on Raspberry Pi 5

Date: 2026-08-29

Target: Raspberry Pi 5 Model B Rev 1.1, Debian Trixie AArch64, PipeWire 1.4.2,
WirePlumber 0.5.8. The local development generation was installed with the
system-control helper deliberately disabled.

## Method

The management session first loaded system overview, metrics, and component
inventory once. The benchmark then compared two equal 20-second windows:

- an idle window with no management requests;
- ten authenticated `GET /api/system/v1/metrics` requests at the dashboard's
  two-second cadence.

Measurements covered the Gunicorn master and descendants through `/proc`, root
filesystem allocation, system fork count, response latency, and process identity.
The system fork count is a host-wide counter, so the equal idle and polling
values are used to detect added subprocess pressure rather than attributing
unrelated host activity to Open Cinema.

## Results

| Measurement | Idle window | Polling window | Increment attributable to polling |
|---|---:|---:|---:|
| Open Cinema CPU time | 0.03 s | 0.10 s | 0.07 s over 20 s |
| Resident memory change | 0 B | 81,920 B | 81,920 B |
| Open Cinema disk reads | 0 B | 0 B | 0 B |
| Open Cinema disk writes | 0 B | 0 B | 0 B |
| Root filesystem allocation | 0 B | 4,096 B | 4,096 B host-wide |
| Host-wide forks | 13 | 13 | 0 versus idle |
| Response bytes | — | 1,759 B | 175.9 B/sample |
| Mean response latency | — | 15.58 ms | — |
| P95 response latency | — | 16.92 ms | — |

The Gunicorn process set remained stable at three processes with identical PIDs
before and after the benchmark. No control action was advertised while the
helper and sudo policy were absent.

## Decision

The two-second metric cadence is accepted. It consumed about 0.35% of one CPU
core above the equal idle window, retained about 80 KiB, performed no Open
Cinema disk I/O, introduced no detectable persistent process or fork overhead,
and completed well inside the two-second interval.
