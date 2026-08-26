## Why

The current Raspberry Pi appliance has passed its core functional scenario, but short interactive observations do not establish repeatable performance limits or safe production defaults. A dedicated benchmark change is needed to characterize the one supported Pi 5 audio chain without coupling those measurements to deployment, UI, or release work.

## What Changes

- Define a repeatable hardware fixture and benchmark harness for the available Raspberry Pi 5 8 GB, Debian Trixie, 27 W supply with fan, WONDOM GAB8, and native PipeWire decoder-to-CamillaDSP chain.
- Preserve the already-passed TV, Bluetooth-source, headset-takeover, and headset-fallback scenario as functional evidence while repeating it to measure switch latency and audible gaps quantitatively.
- Exercise PCM, AC-3, E-AC-3, DTS, supported and unsupported input behavior, format transitions, and representative CamillaDSP 128-frame profiles.
- Measure end-to-end latency, audible gaps, reconciliation and processor timings, resource use, thermals, throttling, xruns, event handling, boot, persistence/storage behavior, and a practical soak of at least ten minutes.
- Derive conservative defaults and supported bounds from preserved raw results and publish a reproducible acceptance report.
- Exclude clean installation, management UI acceptance, coordinated releases, other Raspberry Pi tiers, multi-instance capacity, and advanced managed-link shapes.

## Capabilities

### New Capabilities

- `raspberry-audio-benchmarking`: Repeatable performance characterization, evidence retention, limit selection, and acceptance reporting for the supported single-chain Raspberry Pi 5 appliance fixture.

### Modified Capabilities

None.

## Impact

- Adds benchmark fixtures, measurement helpers, raw-result conventions, and an appliance acceptance report to this repository.
- Exercises the deployed Open Cinema orchestrator, WyrePlumber integration, PipeWire/WirePlumber, `pcm-auto-decoder`, CamillaDSP 4, BlueZ, and WONDOM GAB8 without changing their product contracts.
- Produces measured inputs for deployment defaults and future release decisions; it does not publish releases or broaden the supported hardware or processing capacity.
