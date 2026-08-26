# Static deployment and dynamic audio acceptance — 2026-08-25

Target: Raspberry Pi 5 8 GB at `192.168.1.37`, limited-live rollout.

## Service-account access

The `opencinema` identity is UID 999/GID 985 and belongs only to its primary
group plus `audio` and `video`; it is not a root-group member. Readiness now
continuously verifies:

- read/write access to every exposed `/dev/snd` character device as
  `opencinema`;
- the dedicated PipeWire core, metadata registry, WirePlumber graph, and user
  D-Bus as `opencinema`;
- system-bus visibility of BlueZ objects as `opencinema`;
- the backend, orchestrator, CamillaDSP, and decoder system units all declare
  `User=opencinema`;
- the WyrePlumber contract can create an independent connection, synchronize,
  capture a current snapshot, and release it without root.

The live check passed for three ALSA cards, the headless D-Bus session, BlueZ,
PipeWire/WirePlumber, and the active managed graph. Processor lifecycle remains
bounded by the dedicated polkit rule rather than general sudo access.

## Ansible ownership boundary

An automated source audit scans every deployment YAML, template, filter, and
Python file. It rejects ORM mutations of graph definitions/revisions,
activations, endpoint bindings, CamillaDSP profiles, or manual overrides; audio
API mutation calls; and direct SQL writes to application/orchestration tables.
Ansible owns installation and static appliance policy only. The only Django
state mutations it performs are schema migration and temporary administrator
provisioning.

## Management Apply without Ansible

An authenticated HTTP session used the same `/api/audio/v1` activation route
as the Refine management UI to apply published revision
`e2d1560d-7d25-4fdd-b928-7ec747135b34` of graph
`fcf61f7f-f841-4cc9-aa2d-11ae0892c021`. No playbook ran during the operation.

- desired-state version advanced from 5 to 6;
- the plan entered `converged` with no error;
- plan creation at `21:16:58.763530Z` and applied-state update at
  `21:16:59.687377Z` give 923.847 ms control-plane convergence;
- both logical endpoints retained runtime nodes 83 and 49;
- decoder and CamillaDSP retained `decoder:0` and `camilladsp:0`;
- the effective plan digest remained
  `d68b066d6d074bef7ca305ddf301024f22c1b30641f4e9506dfcd5373444153b`.

SHA-256 output for every `*open-cinema*` file below `/etc/wireplumber` and
`/etc/systemd/system` was captured immediately before and after Apply and was
byte-for-byte identical. This proves a UI Apply changes dynamic desired/applied
state without rewriting Ansible-owned policy or requiring deployment.

## Diagnosable degraded mode

The backend readiness contract always reports desired editing separately from
live-control safety. The management dashboard and graph editor display its
blocker text while keeping graph navigation, draft creation, Save, validation,
and diagnostics reachable. Apply and Deactivate are disabled both inside the
editor and in the graph-list action column whenever `liveControlsAvailable` is
false. UI tests cover both locations. The rebuilt administration bundle was
deployed through nginx and the coordinated LAN readiness pass loaded its new
asset plus the authenticated readiness/diagnostic APIs successfully.
