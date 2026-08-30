# Admin system-control and audio-level acceptance — 2026-08-29

Target: Raspberry Pi 5 Model B Rev 1.1 at `192.168.1.37`, Debian 13,
PipeWire 1.4.2, WirePlumber 0.5.8, CamillaDSP 4.1.3, and PCM auto decoder
0.2.2.

## System controls

The appliance was first observed and benchmarked with host controls disabled.
After the allowlisted helper and exact sudo rules were enabled, the live API
advertised only these actions:

- restart Open Cinema;
- restart the audio orchestrator;
- reboot the appliance.

The Gunicorn unit retains its unprivileged service identity and all existing
filesystem restrictions. `NoNewPrivileges` is disabled only when the reviewed
root-helper path is installed because that one exact sudo transition otherwise
cannot execute; disabling appliance controls restores `NoNewPrivileges=true`.

Live results:

| Action | HTTP acceptance | Recovery result |
|---|---:|---|
| Restart Open Cinema | 202 in 42 ms | operation `succeeded`; new service instance observed |
| Restart audio orchestrator | 202 in 36 ms | operation `succeeded`; fresh ready projection observed |
| Reboot appliance | 202 in 34 ms | operation `succeeded`; API recovered in about 58 seconds |

The reboot changed the boot ID from
`04d933a2-68f0-4916-b2cc-6fdf36d54a4b` to
`23cb4e5a-c248-4ae0-99cf-7d2e55623db3`. After recovery, Open Cinema,
the orchestrator, Redis, nginx, PipeWire, WirePlumber, CamillaDSP, and the PCM
decoder were active, and the full Ansible compatibility/readiness gate passed.
Operation correlation IDs and requested/accepted/succeeded audit events remain
in the application database.

## Audio levels

Physical Pi projection exposed a runtime-specific issue that unit fixtures had
not reproduced: one node `Props` parameter contained both audio controls and a
second hardware-description value. The second value erased the readable volume
in endpoint projection. Projection now selects the most complete node control
value, with regression coverage. A second regression test and fix make endpoint
convergence tolerant of PipeWire float32 observations such as
`0.8500000238418579` for desired `0.85`.

With the exact candidate contract-gated and live reconciliation enabled, the
following authenticated API changes were applied and restored:

| Scope | Temporary value | Converged | Restored to `1.0` |
|---|---:|---:|---:|
| Master output | 0.90 | 13.00 s | 4.32 s |
| Main Speakers logical output | 0.85 | 8.54 s | 6.58 s |
| Active managed input | 0.90 | 8.53 s | 8.30 s |

Every check required desired, effective, and observed values to agree and
`applying=false`. No temporary audio-level intent remains. The active input in
this automated check was the looping managed debug source; physical TV input,
Bluetooth-headset volume, and human audibility remain an operator acceptance
step.

## Result

Automated appliance control, reconnect, readiness, and live level reconciliation
are accepted. End-user UI judgement and the remaining physical TV/headset audio
check are deliberately not claimed by this record.
