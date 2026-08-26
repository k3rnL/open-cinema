# Accepted local-product baseline — 2026-08-25

Status: **accepted for experimental Raspberry Pi deployment; immutable release identities pending**.

## Acceptance decision

The owner accepted the graph editor and endpoint-adapter UI as the deployment
baseline on 2026-08-24, including dashboard/navigation, endpoint discovery,
processor insertion and configuration, Save and Apply, validation and error
feedback, rule and graph views, live overlays, and the canonical local audio
scenario. Minor UI details may be improved later but do not block experimental
appliance deployment.

The detailed automated evidence is in
[`docs/audio-orchestration/ACCEPTANCE_REPORT.md`](../../docs/audio-orchestration/ACCEPTANCE_REPORT.md).
The accepted OpenSpec changes are archived at:

- `openspec/changes/archive/2026-08-24-wireplumber-desired-graph-orchestration`
- `openspec/changes/archive/2026-08-24-managed-audio-endpoint-adapters`

## Contract baseline

| Contract | Accepted value |
| --- | --- |
| Open Cinema audio API | `/api/audio/v1` |
| Orchestration schema | 1 |
| Desired-graph schema | 1 |
| UI orchestration DTO schema | 1 |
| WyrePlumber package | 0.1.0 development tree |
| WyrePlumber orchestration contract | 1 |
| WyrePlumber runtime-value schema | 1 |
| WirePlumber API family | 0.5 |
| PCM auto decoder | 0.1.4 development tree |
| Decoder status protocol | 2 |
| Decoder output contract | one stable adaptive native-PipeWire PCM output |
| CamillaDSP target | 4.1.3 native PipeWire |

## Repository identity at acceptance

The hashes below are the parent commits of the accepted dirty working trees;
they do **not** identify the complete accepted implementation. Task 1.3 and all
immutable release/promotion tasks remain open until reviewed commits or release
artifacts contain those working-tree changes.

| Component | Branch | Parent commit | Accepted tree state |
| --- | --- | --- | --- |
| Open Cinema backend and deployment | `pipewire` | `4a2ec1a3476e612977ec11e2408d3b85e2cb8ba4` | Modified and untracked implementation files |
| WyrePlumber | `pipewire-object-refactor` | `e58456fd9b1f94b778b39f5529ba10d16bdc68c3` | Modified and untracked implementation files |
| Open Cinema UI | `master` | `a1933d5eccc63f7c9f811424cca5dc167967a0da` | Modified and untracked implementation files |
| PCM auto decoder | `master` | `e1be22be3759dd67b0a3bd21384eaab33f87c2c2` | Modified and untracked implementation files |

## Accepted limitations to preserve or validate

- Production deployment must not use these parent hashes as if they contained
  the accepted implementation; local-source installation is experimental only.
- The remaining WyrePlumber host-native connection fixture and the decoder Rust
  suite require native/CI confirmation before immutable release publication.
- Raspberry Pi physical Bluetooth source/headset behavior, real endpoint
  switching, native decoder and CamillaDSP lifecycle, capacity, latency,
  temperature, throttling, storage behavior, and rollback remain unaccepted.
- The temporary `admin` / `admin` credential is limited to the private
  experimental appliance and must be replaced before supported or broader
  network exposure.
- Legacy audio data is intentionally deleted; no compatibility migration is
  required.
