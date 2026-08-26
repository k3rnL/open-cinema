# Upgrade-safety and permission audit — 2026-08-25

Status: **passed for the experimental Raspberry Pi appliance**.

## Distribution ownership

`dpkg --verify pipewire wireplumber` returned no modified package-owned files.
Open Cinema policy is confined to these root-owned, mode `0644` additions:

- `/etc/wireplumber/wireplumber.conf.d/90-open-cinema-bluetooth.conf`
- `/etc/wireplumber/wireplumber.conf.d/91-open-cinema-policy.conf`
- `/etc/systemd/user/pipewire.service.d/90-open-cinema.conf`
- `/etc/systemd/user/wireplumber.service.d/90-open-cinema.conf`

The audio role discovers only `*-open-cinema-*.conf` WirePlumber fragments and
removes managed names outside the current allowlist. PipeWire Pulse's drop-in
directory is removed when the coordinated manifest declares no compatibility
consumer. Distribution configuration and unit files are never replaced. This
completes task 7.4.

## Least-privilege paths

The audit found and corrected the live SQLite database from mode `0644` to
`0600`; deployment now enforces that mode after every migration decision.
End-of-play readiness verifies all of the following on every run:

- `.env`, SQLite, generated processor environment/configuration, rollback
  files, failure logs, and timestamped diagnostics are owned by
  `opencinema:opencinema` with mode `0600`;
- rollback, diagnostics, and processor runtime directories are mode `0750`;
- the latest readiness result and installed identity are mode `0640`;
- the service user's XDG runtime directory is mode `0700`; PipeWire's mode
  `0666` socket remains inaccessible to other users because that parent is
  private;
- the decoder control socket is owned by the service identity with mode `0750`;
- release configuration and systemd units are `root:root` mode `0644`;
- public UI files are limited to the `www-data`-owned web roots.

The validation covered every retained rollback entry, every diagnostic file,
and every current decoder/CamillaDSP runtime entry. The immediate identical
deployment rerun ended with `ok=144 changed=0 failed=0`. This completes task
7.5.

## Management API network boundary

The nginx site now permits `/api/` only from loopback and the inventory's
explicit `192.168.1.0/24` management LAN, followed by `deny all`. Deployment
rejects empty or all-address policies. Effective-configuration readiness found
both allow entries and the default denial, while the full LAN authentication,
schema, administrative diagnostics, and SSE recovery probes continued to pass.
The backend contract separately proves non-administrators cannot retrieve the
privileged bundle and receive redacted ordinary runtime projections. An
identical nginx/readiness rerun ended with `ok=83 changed=0 failed=0`. This
completes task 7.6.
