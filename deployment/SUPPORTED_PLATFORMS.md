# Supported appliance platform matrix

The first orchestration release targets **Raspberry Pi OS Lite 64-bit based on
Debian 13 (Trixie)** on the exercised Raspberry Pi 5 8 GB fixture. Linux must
report at least 7,500 MB of memory; this allows for the difference between the
board's nominal capacity and memory visible to the operating system. The
machine-readable source of truth is
[`compatibility.yml`](compatibility.yml); deployment preflight consumes that
file rather than duplicating version constants in tasks.

## Production matrix

| Layer | Supported range or target |
| --- | --- |
| Raspberry Pi | Pi 5 Model B 8 GB, at least 7,500 MB reported RAM |
| Operating system | Raspberry Pi OS Lite 64-bit, Debian 13 / Trixie |
| Architecture | `aarch64` |
| PipeWire | `>=1.4.0,<2.0.0` |
| WirePlumber | `>=0.5.8,<0.6.0`, API family 0.5 |
| WyrePlumber | `>=0.2.0,<0.3.0`, orchestration contract 1 |
| CamillaDSP / control client | `>=4.1.3,<5.0.0`, native PipeWire / pyCamillaDSP `>=4,<5` |
| PCM auto decoder | `>=0.2.2,<0.3.0`, native PipeWire, status protocol 2 |
| Python | `>=3.13,<3.14` |
| Django / Gunicorn / Celery | `>=6.0,<6.1` / `>=23,<24` / `>=5.6,<6` |
| Redis / SQLite / nginx | `>=8,<9` / `>=3.46,<4` / `>=1.26,<2` |
| BlueZ / FFmpeg libraries | `>=5.82,<6` / `>=7.1,<8` |
| Python installer | uv `>=0.9,<1` |
| Rust toolchain | `>=1.85,<2.0`, build hosts only |
| Node.js | `>=20,<23`, UI build hosts only |
| C toolchain | GCC/Clang-compatible `>=13,<15`, Make `>=4.3,<5`, pkg-config `>=1.8,<2`, build hosts only |

Raspberry Pi OS currently follows Debian Trixie, whose package set provides
WirePlumber 0.5, PipeWire 1.4, and Python 3.13. This keeps the production image
on distribution packages and aligns with the Python requirement already used
by Open Cinema deployment.

## Experimental paths

- Raspberry Pi 4 is experimental until its complete native audio fixture is
  characterized and accepted. Smaller Raspberry Pi 5 memory tiers are also
  explicit experimental paths and are deferred from production for the same
  reason.
- Raspberry Pi 3 Model B+ is experimental until decoder and CamillaDSP CPU,
  memory, latency, and thermal tests pass.
- Debian/Raspberry Pi OS Bookworm is experimental because its base package is
  WirePlumber 0.4. A deployment may opt into Bookworm only when it supplies and
  validates a compatible WirePlumber 0.5 backport.
- 32-bit `armhf` is unsupported because coordinated application and processor
  artifacts target `aarch64`.

## WirePlumber 0.4/0.5 boundary

Open Cinema selects the WirePlumber 0.5 API and configuration family. Version
0.4 is not accepted in production: it exposes a different development package
and uses Lua configuration locations that WirePlumber 0.5 no longer loads. The
WyrePlumber binding must therefore compile against `wireplumber-0.5`, and
deployment-owned configuration must use `wireplumber.conf.d/*.conf` fragments.

Run the dedicated preflight before deploying a coordinated release:

```bash
cd deployment
ansible-playbook -i inventories/local.yml playbooks/preflight.yml
```

The check reports the detected version and the required range. A Bookworm host
with the base WirePlumber 0.4 package is rejected; an experimental Bookworm path
must install a validated 0.5 backport and explicitly opt in.

## Resource policy

The initial production default permits one CamillaDSP instance and one native
PipeWire decoder instance. These are declared policy defaults, not graph-model
limits. The Pi 5 8 GB benchmark campaign must complete before performance limits
or broader capacity claims are added. Both processors use native PipeWire
resources in the supported appliance contract.

## Reference sources

- Raspberry Pi OS release and architecture information:
  <https://www.raspberrypi.com/documentation/computers/os.html>
- Debian Trixie WirePlumber package:
  <https://packages.debian.org/trixie/wireplumber>
- Debian Trixie PipeWire package:
  <https://packages.debian.org/trixie/pipewire>
- Debian Trixie Python package:
  <https://packages.debian.org/trixie/python/python3>
- WirePlumber 0.5 configuration migration:
  <https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/migration.html>
