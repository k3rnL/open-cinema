## Why

Open Cinema now runs as a working headless audio appliance on the current Raspberry Pi 5 fixture, but the deployment still needs a small, explicit contract for reproducing that runtime and recovering it safely. Hardware characterization and coordinated component publication are independent concerns and should not obscure whether the appliance deployment itself is deterministic.

## What Changes

- Support the currently validated Raspberry Pi 5 8 GB appliance as the sole deployment target until the separate benchmark change establishes broader limits.
- Install and verify one coordinated, native-PipeWire stack with version-correlated, immutable component inputs in appliance mode while retaining an explicit local-source development mode.
- Preserve one documented headless PipeWire/WirePlumber service identity, least-privilege access, BlueZ roles, and stable managed-processor resources.
- Keep Ansible-owned static configuration separate from graph, endpoint, processor-profile, rule, scene, and override data owned by Open Cinema.
- Use upgrade-safe WirePlumber overlays, ordered readiness, authenticated management access, idempotent configuration, correlated diagnostics, backups, and coordinated rollback.
- Remove active legacy audio-protocol compatibility configuration from the appliance deployment.
- Move hardware benchmarks to `benchmark-raspberry-audio-appliance` and component commits, versioning, publication, and README work to `publish-coordinated-project-releases`.
- Defer clean-image installation and arbitrary upgrade-path qualification until the product is ready for a later fresh-install campaign.

## Capabilities

### New Capabilities

- `raspberry-audio-deployment`: Reproducible deployment, verification, and coordinated recovery of the current headless Raspberry Pi audio appliance.

### Modified Capabilities

- `wireplumber-runtime-control`: Remove the transitional compatibility-server
  allowance now that every managed processor uses native PipeWire I/O.

## Impact

- The `deployment/` Ansible inventory, roles, templates, compatibility manifest, preflight, readiness, diagnostics, backup, and rollback workflows are affected.
- `open-cinema`, `wyreplumber`, `open-cinema-ui`, and `pcm-auto-decoder` remain coordinated runtime inputs, but publishing their releases belongs to the separate release change.
- PipeWire, WirePlumber, BlueZ, Redis where enabled, CamillaDSP, the decoder, Open Cinema services, nginx, and the management UI share one deployment and rollback boundary on the current appliance.
- Existing acceptance evidence remains historical context; this change retains only residual work needed to close the narrowed deployment contract.
