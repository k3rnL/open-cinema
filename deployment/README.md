# Open Cinema appliance deployment

This directory installs the coordinated Open Cinema audio appliance on the
supported Raspberry Pi platform. PipeWire provides the graph, WirePlumber owns
the session and device lifecycle, and the dedicated Open Cinema orchestrator
applies the saved desired graph through WyrePlumber.

The supported versions are defined once in `compatibility.yml` and enforced by
deployment preflight. See `SUPPORTED_PLATFORMS.md` for the production and
experimental platform policy.

## Installed components

- one persistent `opencinema` PipeWire/WirePlumber user session;
- BlueZ roles for receiving programme audio and driving Bluetooth headsets;
- the Django API, Redis, Gunicorn, and dedicated orchestration process;
- orchestrator-owned CamillaDSP and PCM decoder instance templates;
- nginx plus the simple and administration web interfaces.

CamillaDSP and decoder instances are not enabled by Ansible. The orchestrator
starts an instance only after resolving a desired graph and writing its owned
configuration beneath `/run/open-cinema`.

## Appliance prerequisites

- the currently provisioned Raspberry Pi 5 8 GB fixture;
- Raspberry Pi OS Lite 64-bit based on Debian 13 / Trixie;
- SSH and sudo access from the controller;
- Ansible Core 2.19 and the pinned collection from
  `collections/requirements.yml`;
- a finalized coordinated manifest containing immutable Open Cinema wheel and
  source distributions, the target WyrePlumber and pycamilladsp wheels, both UI
  archives, and native CamillaDSP and decoder archives.

This deployment reproduces the already provisioned fixture. A clean-image
installation and arbitrary upgrade-path qualification are intentionally
deferred.

Install the controller dependency:

```bash
ansible-galaxy collection install -r collections/requirements.yml
```

## Configure an appliance

Copy `inventories/example.yml` to the ignored `inventories/local.yml` and set
the target host. The local inventory is intentionally not tracked because it
contains controller paths and appliance-specific values. Override secrets in
that private file or Ansible Vault; do not deploy the example Django secret.

For an appliance install, set `open_cinema_release_manifest_source_path` to the
downloaded, finalized coordinated manifest and leave `install_from_local`
false. The manifest is the only release-identity authority: each selected
artifact carries its exact name, immutable HTTPS URL, SHA-256 digest,
platform/ABI selector, and portable provenance reference. Deployment does not
construct release URLs from inventory versions and does not clone a branch,
tag, or repository.

The checked-in `development-manifest.yml` is the deliberately mutable local
fixture. It has `input_mode: development`, identifies the four local projects
as mutable, and cannot be used when `install_from_local` is false. The separate
`release-manifest.yml` is reserved for the immutable release candidate and is
the non-deployable template finalized by the backend tag workflow. It contains
no dummy digest: the Open Cinema artifact identity is deliberately absent until
the tag workflow can bind the manifest to the wheel and source archive it just
built. Its `candidate_notice` is removed during finalization; the published
manifest contains only limitations that still apply to the supported release.
Accepted public manifests are retained byte-for-byte under `releases/` after
their downloaded artifacts and provenance pass verification. The current
appliance input is `releases/open-cinema-0.3.2.yml` (SHA-256
`c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2`);
this is also the checked-in release-mode default, and it contains no private
inventory or rollback-capsule path. An inventory override remains useful when
validating a future finalized manifest before promoting that default.
The publication and current provisioned-fixture result are summarized in the
[Open Cinema 0.3.2 closure](../docs/release-readiness/2026-08-27-open-cinema-v0.3.2-closure.md).

For development, all edited repositories may be synchronized directly:

```yaml
all:
  hosts:
    cinema_pi:
      ansible_host: cinema-pi.example.net
      ansible_user: pi
      install_from_local: true
      open_cinema_release_manifest_source_path: /absolute/path/open-cinema/deployment/development-manifest.yml
      local_source_path: /absolute/path/open-cinema
      local_wyreplumber_source_path: /absolute/path/wyreplumber
      local_open_cinema_ui_source_path: /absolute/path/open-cinema-ui
      local_pcm_auto_decoder_source_path: /absolute/path/pcm-auto-decoder
```

Development mode fingerprints the synchronized backend, binding, built UI, and
decoder inputs. The combined candidate digest and each individual SHA-256 are
reported as mutable, non-release identities; they are never presented as
published component provenance.

## Validate and deploy

Run standalone platform/package preflight on an already prepared target:

```bash
ansible-playbook -i inventories/local.yml playbooks/preflight.yml
```

The standalone result is retained as
`/tmp/open-cinema-preflight-result.json`. It classifies the host as production,
explicitly experimental, or unsupported and reports every detected platform,
resource, repository, identity, audio-runtime, artifact, and manifest problem
in one run. To audit an already installed appliance as well, enable its full
runtime and schema-contract probes:

```bash
ansible-playbook -i inventories/local.yml playbooks/preflight.yml \
  -e open_cinema_preflight_require_runtime=true \
  -e open_cinema_preflight_require_full_runtime=true
```

Deploy the coordinated stack:

```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml
```

Before its first role, the site play validates that inventory mode matches the
manifest, rejects local-directory/editable/floating/latest/unpinned appliance
inputs, verifies artifact/provenance completeness, and resolves one compatible
artifact of each required kind for Debian Trixie AArch64, Python 3.13, and
WirePlumber 0.5. Artifact and provenance URLs must use the declared GitHub
repository and tag, except for components explicitly mirrored into the
finalized Open Cinema release; that coordinated release identity must match the
declared Open Cinema repository, tag, and commit. Unknown selector names and native assets missing
their architecture, ABI, or WirePlumber-family selectors are rejected. For the
first coordinated release it also verifies the private
replacement rollback capsule against its committed receipt, hashes, archive
inventory, permissions, and SQLite integrity before touching the Pi. The
receipt-bound Pi baseline must also exist with matching manifest/READY digests,
matching regular-file count, and immutable protection on every entry. Mutable
development runs perform that target check without opening or requiring the
controller capsule; appliance promotion verifies both copies. The capsule path
remains protected inventory and is never written to public evidence. Only
development mode permits local source directories.

The site play then installs PipeWire/WirePlumber and reruns aggregate preflight
with audio-session checks enabled, before any processor role, database
migration, or live reconciliation. Its final readiness role requires:

- the owned PipeWire socket and a healthy `wpctl status`;
- WyrePlumber orchestration contract v1 and its native binding;
- Redis, Django, the dedicated orchestrator, and the versioned API route;
- the pinned CamillaDSP and decoder binaries and stable processor buses;
- nginx and the API health endpoint;
- both web interfaces and every referenced asset through the appliance LAN
  address;
- anonymous diagnostic rejection, native CSRF/session login, schema metadata,
  authorized diagnostics, authenticated SSE transport through nginx, and any
  cursor-gap snapshot reported by the live event store. Cursor-gap generation
  itself remains covered by the application suite so deployment never creates
  or deletes user graph data merely to manufacture a readiness fixture.

Before replacing candidate application files, the play compares the candidate
content digest with the last passed contract-gate result. A changed candidate
stops the previous orchestrator, installs with processor management and live
reconciliation forced off, and probes the fully installed binding, backend,
processing-plugin, decoder, processor, and management-UI DTO contracts. Only a
zero-failure result at
`/var/lib/open-cinema/deployment-diagnostics/contract-gate-result.json` enables
the accepted full runtime for every active graph. An identical candidate reuses
the passed digest, still reruns the probes, and does not interrupt audio.

Set `readiness.verify_hardware_nodes: true` and list expected `wpctl status`
patterns only for a hardware acceptance inventory. The default does not pretend
that HDMI, USB, S/PDIF, or Bluetooth hardware exists on a generic target.

## Runtime ownership and ordering

The `opencinema` system user has a persistent systemd user manager through
linger. Its session exports:

```text
XDG_RUNTIME_DIR=/run/user/<uid>
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus
PIPEWIRE_REMOTE=pipewire-0
```

PipeWire and WirePlumber are user services. Django, the orchestrator,
CamillaDSP instances, and decoder instances are system services running as the
same identity. Every audio-attached system unit checks the exact user-session
socket before starting and has bounded startup, restart, and graceful shutdown
behavior.

Managed debug-file adapters use the explicit persistent root
`/opt/home-cinema/open-cinema/media/audio-adapters`. The runtime environment
pins this path in both source and wheel installs, and coordinated application
backups retain it, so installing a wheel cannot redirect existing looping or
recording devices into `site-packages`.

Distribution unit files and WirePlumber defaults are never edited. Open Cinema
uses `/etc/systemd/user/*.service.d/90-open-cinema.conf` and
`/etc/wireplumber/wireplumber.conf.d/9*-open-cinema-*.conf`, so package upgrades
retain the appliance policy without replacing vendor configuration.

## Upgrade backups and coordinated rollback

Legacy audio rows are intentionally not migrated. Before replacing any
previously accepted candidate, deployment creates a private
`transition-<timestamp>-<candidate-digest>` directory under
`/var/lib/open-cinema/rollback`. It is marked `READY` only after recording and
checksumming the complete recovery boundary:

- the stopped SQLite database and a digest of user-owned graph intent;
- the complete application/virtual environment, including an exact
  wheel-installed WyrePlumber binding, plus a separate binding source archive
  when the previous generation actually has one;
- both packaged web applications;
- CamillaDSP and decoder binaries plus their generated runtime configuration;
- the installed release manifest, contract-gate result, and readiness result;
- the controller inventory, group variables, compatibility contract, candidate
  release manifest, and managed static configuration.

Transition-manifest schema 2 makes the separate WyrePlumber source archive
conditional. A release-mode generation is recoverable when its archived
application environment contains the exact binding version, native API,
orchestration contract, and runtime-value schema, and its resolved virtual
environment is inside the application archive. It therefore does not need a
duplicate source tree. A development generation records that mode explicitly
and requires a real non-symlink binding source directory. Rollback accepts both
schema 2 and the retained schema-1 full-generation boundary, and in either case
requires READY to match the declared artifact set exactly.

Readiness chooses an active rollback identity only from immediate directories
whose manifest, READY record, regular-file boundary, deployment-mode/source
relationship, and every artifact digest verify. A partial or malformed newer
directory cannot displace a valid recovery point. Explicit window closure
validates active and protected bundles before pruning, verifies the retained set
afterward, and writes its correlated release/digest marker last. A later
unchanged deployment preserves that closed marker while all identities still
match.

An initial installation has no accepted generation to preserve and therefore
does not manufacture an empty rollback bundle. An identical candidate reuses
its passed contract gate and does not stop audio or create another bundle.
Because the historical public releases cannot restore the native PipeWire
stack, `0.3.2` uses a one-time private replacement baseline. Its privacy-safe
receipt is retained in `rollback-baselines/`; the capsule itself stays in the
protected controller store and immutable appliance directory. Later releases
must instead retain the immediately previous finalized coordinated manifest.
The verified baseline identity is excluded from permission rewrites and
rollback pruning in both development and appliance modes. Missing, mutable, or
digest-drifted target state blocks before mutation and must be restored manually
from a retained private copy; deployment does not rehydrate it automatically.

Schema transitions also retain their migration plan and a bounded online
SQLite backup. The plan, SQLite integrity check, Django migration-history
check, backup, and migration apply all use declared timeouts. SQLite is copied
with its `.backup` command after application writers stop, so WAL state is
captured consistently. A migration failure writes one private correlated JSON
result containing every command's output and timeout status plus matching
service logs.

If migration fails, deployment stops before restarting services and retains the
bundle plus journal output under
`/var/lib/open-cinema/deployment-diagnostics`. If final readiness fails, it also
stops and retains the same rollback data. The entire candidate mutation phase
has an outer failure boundary as well: install, handler/restart, contract, and
readiness failures produce a private `candidate-<timestamp>.json` plus matching
service log. That record names the failed task, candidate digest, retained
rollback bundle, related detailed diagnostics, and observed service states.

Rollback always requires the exact bundle ID; it never guesses the newest
directory and never deletes another recovery point:

```bash
ansible-playbook -i inventories/local.yml playbooks/rollback.yml \
  -e open_cinema_rollback_bundle_id=transition-YYYYMMDDTHHMMSS-<digest>
```

The rollback play verifies every artifact checksum before mutation, checkpoints
the failed candidate database, stops all database writers and managed
processors, restores the application, binding, web builds, processor binaries,
runtime configuration, managed static files, release evidence, and database as
one generation, loads the restored installed manifest as the readiness identity,
then runs the normal end-of-play readiness checks. Historical contract-gate and
readiness snapshots remain supplemental bundle diagnostics rather than hashed
restore artifacts: rollback never restores or trusts them. It reconstructs the
minimal gate identity from the checksum-verified rollback manifest, while
readiness publishes a fresh result for the restored runtime. It also
requires the restored graph/endpoint/profile/activation/adapter/override digest
to match the pre-transition digest. The result is written privately to
`/var/lib/open-cinema/deployment-diagnostics/rollback-result.json`.

Every readiness run publishes one machine-readable result at
`/var/lib/open-cinema/deployment-diagnostics/readiness-result.json`. A passing
result correlates the release-manifest digest and component identities with all
readiness contracts, service states, controller ownership, and runtime/database
convergence facts. A failure replaces that latest result and also retains a
timestamped JSON copy plus its matching journal log. Failed loop items and any
additional service, WirePlumber, Redis, orchestration, projection, or API probe
failures are reported separately in `failedChecks`.

The successful installed identity is also written to
`/var/lib/open-cinema/deployment-diagnostics/installed-release.yml`. Appliance
records include the selected artifact hashes and exact installed package/binary
probes. Development records include the individual local source digests and an
explicit `mutable_install: true`; both records retain the installed coordinated
manifest SHA-256 for diagnostics and rollback.

Experimental deployments retain every recovery bundle. Only a later explicitly
accepted run with `open_cinema_close_rollback_window=true` may keep the selected
pre-deployment bundle plus any manifest-verified protected first-release
replacement, remove other recovery points, and write
`/var/lib/open-cinema/rollback/rollback-window.yml`. A failed deployment never
reaches that closure step.

If checksum verification proves that an older experimental bundle is partial
or malformed and no verified mutable recovery point remains, an operator may
run one deliberate maintenance transition with
`open_cinema_reseed_rollback_boundary=true`. This snapshots the currently
installed accepted generation, exercises the normal quiesce/install/gate/
readiness path even though the candidate digest is unchanged, and produces a
new checksum-verified recovery point. Keep the option false for ordinary
reconciliation; close and prune the window only in the same reviewed run after
the new bundle and every protected exception verify.

## Service and diagnostic commands

```bash
sudo systemctl status open-cinema open-cinema-orchestrator redis-server nginx
sudo systemctl status 'camilladsp@*.service' 'pcm-auto-decoder@*.service'
sudo -u opencinema XDG_RUNTIME_DIR=/run/user/$(id -u opencinema) \
  systemctl --user status pipewire wireplumber
sudo -u opencinema XDG_RUNTIME_DIR=/run/user/$(id -u opencinema) wpctl status
sudo journalctl -u open-cinema-orchestrator -n 200 --no-pager
sudo python3 -m json.tool /var/lib/open-cinema/deployment-diagnostics/readiness-result.json
sudo python3 -m json.tool /var/lib/open-cinema/deployment-diagnostics/rollback-result.json
```

The appliance is served at `/ui/` and `/admin/`. The management console redirects
anonymous browsers to its own `/admin/login` route and authenticates through a
Django session; visiting Django admin first is not required. The experimental
inventory currently provisions `admin` / `admin`. Replace that password through
Ansible Vault, or disable `open_cinema.default_admin.enabled`, before exposing or
promoting the appliance. `/api/audio/v1/` is the only audio configuration API;
CamillaDSP loopback control ports and processor Unix sockets are internal
implementation interfaces.

Nginx also enforces `open_cinema_management_api_networks` before proxying any
`/api/` request. The common default permits loopback only; each appliance
inventory must add its bounded management LAN and cannot use `0.0.0.0/0` or
`::/0`. The current private appliance supplies its controlled LAN only through
the ignored inventory. UI assets may remain reachable while the API is degraded
or denied, but configuration and diagnostic calls cannot cross this boundary.

## Contract-gated runtime activation

The appliance inventory declares one full runtime: API, observation, shadow
resolution, processor management, and live reconciliation are the accepted
capabilities, and live reconciliation covers every active graph. Deployment has
no selectable stage or per-graph scope.

A changed candidate starts with API, observation, and shadow diagnostics
available while processor management and live reconciliation remain false. The
contract gate enables those two mutation capabilities only after every binding,
backend, processor, decoder, and UI contract probe passes. Failed probes retain
the diagnosable non-live runtime and the coordinated rollback boundary.
