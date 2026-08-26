# Pi 5 8 GB initial deployment result — 2026-08-24

Status: **failed fixture; functional deployment evidence only**

## Setup observed

- Raspberry Pi 5 Model B Rev 1.1, 8063 MB RAM, four cores.
- Debian 13.2 Trixie, aarch64, kernel `6.12.47+rpt-rpi-2712`.
- 64 GB-class microSD (`/dev/mmcblk0`), ext4 root, about 50 GB free.
- Wi-Fi at `192.168.1.37`; wired-network latency budgets were not measured.
- Power supply, cooling hardware, case, storage rating, and ambient temperature
  were not recorded, so the physical fixture was incomplete.
- WONDOM GAB8 USB audio device exposed one 8-channel, 48 kHz output.

## Baseline and deployment observations

- Initial idle temperature: 43.3 °C.
- Initial throttling word after boot: `0x50000`, already showing historical
  undervoltage/throttling and therefore invalidating a comparable benchmark.
- Boot to multi-user target: 17.331 seconds.
- Package candidates and installed audio stack passed the selected families:
  PipeWire 1.4.2 and WirePlumber 0.5.8.
- The dedicated `opencinema` session owns PipeWire, WirePlumber, PipeWire Pulse,
  Django, and the observer. Independent PulseAudio is masked and absent.
- Runtime observation connected through WyrePlumber contract v1 and projected
  the WONDOM output. CamillaDSP internal buses remained visible to PipeWire but
  were excluded from endpoint candidates after a Pi-discovered fix.
- Current admin UI is reachable at `http://192.168.1.37/admin/`; live
  reconciliation and processor management remained disabled.

## Decoder build stress failure

The current decoder 0.1.4 source build was used as an incidental sustained CPU
fixture because the installed 0.1.3 binary lacks the managed status protocol.

| Observation | Temperature | `get_throttled` |
| --- | ---: | --- |
| Early four-core Rust compilation | 73.0 °C | `0x50000` |
| Soft-temperature limit reached | 82.3 °C | `0xd0008` |
| Current undervoltage and throttling | 83.4 °C | `0xd0005` |
| Before remote process termination | 85.1 °C | `0xf0008` |
| Immediately after termination | 76.3 °C | `0xf0000` |
| Later functional verification | 63.7 °C | `0xf0000` |

The build process group was terminated and no compiler remained. The existing
0.1.3 decoder binary was not replaced. No performance, capacity, or supported
platform conclusion may be derived from this run.

## Passed functional evidence

- SSH, passwordless sudo, Ansible connectivity, platform facts, and Trixie
  package compatibility.
- Headless audio session startup and an idempotent audio-role rerun with zero
  changes.
- Removal of the legacy system PulseAudio service and runtime socket.
- Backend/WyrePlumber local-source install, destructive legacy migration with
  retained rollback bundles, API/UI startup, and runtime observation.
- CamillaDSP 3.0.1 binary contract, stable PipeWire Pulse buses, and hardened
  non-started instance template.
- Physical endpoint versus internal processor-resource separation on real
  WirePlumber data.

## Required rerun conditions

Use a verified 5.1 V / 5 A (27 W) Pi 5 supply, active cooler or equivalent,
record the case and ambient temperature, reboot, and require an initial
`get_throttled=0x0`. Resume the decoder build and benchmark suite only if the
value remains free of current/historical undervoltage and throttling bits during
the workload.
