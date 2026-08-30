# Appliance system controls

The `/api/system/v1` API makes appliance observation and a deliberately small
set of administrative actions available to the end-user management console.
It is not a remote shell or a generic systemd API.

## Security boundary

The Django process owns a fixed registry containing only:

- restart the `open-cinema` service;
- restart the `open-cinema-orchestrator` service;
- reboot the appliance.

The browser can submit only a short-lived signed action token previously
advertised by that registry. Requests require an authenticated staff user,
normal CSRF protection, and a matching current boot identity. Duplicate
in-progress requests resolve to the existing operation. Arbitrary unit names,
commands, arguments, paths, and environment variables are never accepted.

A root-owned helper repeats the enum check and maps it to fixed `systemctl`
arguments. An exact sudoers entry permits the Open Cinema service identity to
execute that helper only. The API advertises an action as available only after
checking helper ownership, mode, executability, and non-interactive
authorization. Audit events record the actor, action, target, operation,
correlation, outcome, and bounded error code without command output or host
secrets.

The Gunicorn unit normally runs with `NoNewPrivileges=true`. Enabling appliance
controls sets that one unit property to `false`, because Linux otherwise blocks
the reviewed sudo transition before the helper can repeat its allowlist check.
The application remains the unprivileged `opencinema` identity, `ProtectSystem`
and its write-path allowlist remain active, home directories remain inaccessible,
and sudo authorizes only the six exact helper/check command lines. Disabling
controls restores `NoNewPrivileges=true` and removes both privileged files.

## Deployment

Controls are disabled by default:

```yaml
open_cinema:
  system_control:
    enabled: false
```

Set `open_cinema.system_control.enabled: true` in the reviewed appliance
inventory and run the normal site playbook. The role installs
`/usr/local/libexec/open-cinema-system-control`, installs and validates
`/etc/sudoers.d/open-cinema-system-control`, and performs `--check` for each
allowed action as the service identity. A failed check stops deployment before
the API can advertise the controls.

To remove the privilege, set the option back to `false` and rerun the role. It
removes both the sudo policy and helper; the dashboard then keeps the actions
visible as unavailable with the server-provided reason. This removal is
independent from the coordinated product rollback procedure.

## Operator behavior

Open Cinema restart and appliance reboot intentionally interrupt the initiating
HTTP session. The endpoint records and returns an accepted operation before the
helper performs the delayed action. The UI treats the disconnect as expected,
polls with bounded backoff, and requires a changed service-start marker or boot
identifier plus fresh health before reporting success. A timeout is reported as
unknown/failed rather than assuming that a network disconnect proves success.

The orchestrator restart does not change desired graphs or stored volume state.
On return, normal startup recovery obtains a fresh runtime generation,
reconstructs any uncertain transition, and reapplies only unconfirmed desired
state. An appliance reboot follows the same recovery path after PipeWire and
WirePlumber are ready.

Useful checks on the appliance are:

```bash
sudo -u opencinema sudo -n /usr/local/libexec/open-cinema-system-control \
  --check restart-open-cinema
sudo -u opencinema sudo -n /usr/local/libexec/open-cinema-system-control \
  --check restart-orchestrator
sudo -u opencinema sudo -n /usr/local/libexec/open-cinema-system-control \
  --check reboot-appliance
sudo journalctl -u open-cinema -u open-cinema-orchestrator -n 200 --no-pager
```

Never broaden the sudo entry to `systemctl`, add a client-supplied service
argument, or make availability depend only on the helper file existing.
