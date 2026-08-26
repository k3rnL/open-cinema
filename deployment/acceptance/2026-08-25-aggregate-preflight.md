# Aggregate appliance preflight — 2026-08-25

Target: Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian Trixie/aarch64.

The dedicated preflight produced one structured production-classification
result at `/tmp/open-cinema-preflight-result.json`. The full installed-runtime
mode passed with:

- 8062 MB detected memory and 43751 MB free on `/`;
- installable distribution candidates for every runtime and local-build
  prerequisite;
- collision-free UID 999/GID 985 ownership;
- PipeWire 1.4.2 and WirePlumber 0.5.8 plus the dedicated user session;
- compatible Python, Redis, SQLite, nginx, BlueZ, FFmpeg, CamillaDSP, decoder,
  Django, Gunicorn, Celery, pyCamillaDSP, and WyrePlumber versions;
- audio API, desired-graph, orchestration, WyrePlumber runtime-value, and
  decoder protocol contracts matching the candidate release manifest;
- an installed release-manifest SHA-256 matching the controller candidate.

The task sequence performs every non-mutating probe before its single final
assertion, so one missing component cannot hide later incompatibilities.

## Negative fixture

A preflight-only run raised the memory floor to 999999 MB, the storage floor to
999999999 MB, and injected an incompatible UI DTO contract fixture. It failed
once with all three messages in the retained JSON and the play recap, without
running common, audio, processor, application, migration, or reconciliation
roles. The normal full-runtime preflight was then rerun to restore a passing
result.
