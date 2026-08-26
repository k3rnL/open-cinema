## Coordinated implementation baseline

Captured on 2026-08-22 before implementation began. Commit hashes identify the
code baseline; working-tree changes are deliberately not included in those
hashes and must be preserved during implementation.

| Component | Repository / location | Branch | Baseline commit | Working tree at capture |
| --- | --- | --- | --- | --- |
| Open Cinema backend | `git@github.com:k3rnL/open-cinema.git` | `pipewire` | `4a2ec1a3476e612977ec11e2408d3b85e2cb8ba4` | Modified; contains the user's in-progress PipeWire integration and untracked files |
| Ansible deployment | `deployment/` in the Open Cinema backend repository | `pipewire` | `4a2ec1a3476e612977ec11e2408d3b85e2cb8ba4` | Shares the backend working tree; it is not a separate Git repository in this workspace |
| WyrePlumber | `https://github.com/k3rnL/wyreplumber.git` | `pipewire-object-refactor` | `e58456fd9b1f94b778b39f5529ba10d16bdc68c3` | Modified; contains the user's SPA parameter work and untracked experiments/documentation |
| Open Cinema UI | `git@github.com:k3rnL/open-cinema-ui.git` | `master` | `a1933d5eccc63f7c9f811424cca5dc167967a0da` | Clean |
| PCM auto decoder | `git@github.com:k3rnL/pcm-auto-decoder.git` | `master` | `e1be22be3759dd67b0a3bd21384eaab33f87c2c2` | Clean |

### Scope note

The owner explicitly expanded implementation scope to the adjacent coordinated
repositories. The UI and WyrePlumber changes may therefore be developed and
verified locally before replacing development path pins with released artifacts.

### Legacy data decision

On 2026-08-23 the sole owner confirmed there are no other users and no legacy
device, backend-preference, AudioPipeline, direct CamillaDSP, decoder-state, or
Pulse module records that require preservation. The implementation therefore
deletes those models, tables, APIs, jobs, dependencies, and UI paths directly.
No analyser, conversion, review UI, compatibility response, or data rollback is
part of the product boundary.

### Development WyrePlumber pin

Open Cinema now requires `wyreplumber==0.1.0`; `uv` resolves it from the
adjacent `../wyreplumber` working tree during coordinated development. The
source was validated on 2026-08-22 with 195 tests on both the legacy build
boundary and the production WirePlumber 0.5.8 / PipeWire 1.4.2 boundary, and
its built wheel reports orchestration contract 1 and build API family 0.5.

This local source pin is permitted only for development. Before deployment it
must be replaced by an immutable commit or released artifact made from that
tested working tree; the baseline commit in the table above predates the
orchestration contract and must not be deployed as the pin.

### Headless deployment implementation

The deployment now creates one lingering `opencinema` user manager for
PipeWire, WirePlumber, and the conditional PipeWire Pulse protocol bridge. All
system services that attach to audio use the same UID, XDG runtime directory,
user D-Bus address, and explicit PipeWire/Pulse sockets. The old independent
PulseAudio role and daemon are deleted and masked.

Open Cinema configuration is installed through named WirePlumber 0.5 fragments
and systemd drop-ins. BlueZ enables both programme-source (`a2dp_sink`) and
headset-output (`a2dp_source`) roles. Redis, Gunicorn, orchestration, Celery
retention worker/scheduler, nginx, and managed processor units have bounded
restart/start/stop behavior. End-of-play readiness validates the user audio
session, WyrePlumber contract, live Redis runtime snapshot, API route,
processor contracts, and both web applications.

Because legacy data is intentionally discarded, the schema migration applies
directly. Deployment still creates a pre-migration rollback bundle for the
coordinated release (database, generated processor configuration, component
versions, and exact migration plan) and retains that bundle plus journals on
failure; this is operational rollback, not a legacy-data conversion path.

The Debian Trixie development image was built and started on 2026-08-23 with an
isolated D-Bus/PipeWire/WirePlumber session and Redis 7.4.2. Its WyrePlumber
native binding reported contract 1/API family 0.5 and captured the deterministic
TV, speakers, and headset fixture nodes without using the host audio session.
Ansible Core 2.19.2 parsed both playbooks with the pinned `ansible.posix` 2.1.0
collection, and the deployment contract suite passed.

Tasks 20.1 and 20.3 deliberately remain open: current coordinated changes are
still uncommitted working trees, so no immutable accepted release revision can
be honestly pinned, and Bluetooth/HDMI/USB node verification requires the
target Raspberry Pi hardware.

### Software acceptance

The executable acceptance pass now covers the canonical TV, Bluetooth,
headset, and headset-removal sequence; PCM/AC-3/E-AC-3/DTS decisions coupled to
generated CamillaDSP configurations; missing endpoint/processor recovery;
endpoint, scene, volume, and mute override lifetime; the full software fault
matrix; ownership and generation fencing; and security/boundary behavior.

[`docs/audio-orchestration/ACCEPTANCE_REPORT.md`](../../../docs/audio-orchestration/ACCEPTANCE_REPORT.md)
maps every specification requirement to automated evidence, a deployment or
hardware check, or an explicit limitation. Tasks 21.7 and 21.8 remain open
because final appliance limits must be based on measurements from each
supported Raspberry Pi tier rather than desktop/container results.

The final backend pass at this checkpoint completed 695 tests, Django system
checks, migration drift checks, formatting checks, deployment diff checks, both
Ansible syntax checks, and strict OpenSpec validation. OpenSpec progress is
191/201. The ten remaining tasks are the target-hardware timing/capacity work,
immutable release installation, physical BlueZ/node verification, staged
appliance rollout and checkpoint, default enablement, and removal of the
temporary feature/Pulse bridge only after no processor depends on it.
