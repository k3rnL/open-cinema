# Managed CamillaDSP profiles and instances

CamillaDSP is a processing stage selected by a resolved desired graph. It does
not own endpoint discovery, session policy, or durable route intent. Open Cinema
owns reusable profiles and instance lifecycle, while WirePlumber remains the
authority for the live PipeWire graph and routing.

## Profile contract

`CamillaDSPProfile` rows are immutable revisions. `profile_id` identifies the
stable lineage and `(profile_id, version)` is unique. A revision contains:

- schema version 1;
- typed, constrained parameters and defaults;
- declared input and output signal contracts;
- device-independent chunksize, resampler, filters, mixers, and pipeline;
- a canonical content digest and validation summary.

Concrete `devices.capture` and `devices.playback` sections are forbidden in a
profile. Parameter references use an object such as `{"parameter": "gainDb"}`;
arbitrary text interpolation is not supported. This keeps profile documents
safe to validate and reusable with different logical endpoints.

The generator combines a normalized profile with resolved capture/playback
endpoints, the effective PCM signal descriptor, graph parameter bindings, and
an explicit channel-adaptation decision. A channel-count change without a mixer
mapping is rejected. Both generated devices must use CamillaDSP 4's native
`PipeWire` backend and declare their stable node name, description, and group.

## Validation boundary

Generated configuration is eligible for an applied plan only after:

1. Open Cinema validates required devices, channel counts, mixer bounds,
   pipeline references, native PipeWire endpoints, and canonical JSON values.
2. `CamillaDSPBinaryValidator` runs the pinned engine with `--check` against a
   private temporary YAML file.
3. The live WebSocket control validates the document again immediately before
   activation or reconfiguration.

Validation failures are permanent configuration failures until the profile,
parameters, descriptors, or endpoints change. They never create runtime files
or start an instance.

## Stable native PipeWire resources

The appliance pins CamillaDSP 4.1.3 and generates one native capture node and
one native playback node for each managed instance:

| Role | Stable node name |
| --- | --- |
| Processor input | `opencinema.camilladsp.<n>.capture` |
| Processor output | `opencinema.camilladsp.<n>.playback` |

Both nodes share an instance-scoped group. CamillaDSP does not autoconnect them;
the resolved graph and WirePlumber own every upstream and downstream link.
Numeric PipeWire IDs may change after a restart, so reconciliation rematches the
stable node names, group, managed processor kind, instance, and port properties.

## Runtime ownership and lifecycle

For instance `room`, the driver exclusively owns:

- `/run/open-cinema/camilladsp/room.yml`;
- `/run/open-cinema/camilladsp/room.env`;
- `camilladsp@room.service` lifecycle.

Owned files start with `# open-cinema-owner: camilladsp-v1`, are replaced
atomically, and use mode `0600`. The driver refuses to overwrite or delete an
unmarked file and does not use process-name searches or persisted PIDs. Ansible
installs the template and runtime-directory policy but starts no unconfigured
instance.

The driver implements `prepare`, `activate`, `observe`, `reconfigure`,
`deactivate`, and `cleanup`. Repeated calls recognize the requested configuration
digest. Observation exposes connection, engine state, active and requested
digests, profile digest, input/output descriptors, stable stream correlation,
validation, warnings, readiness, and last failure.

## Safe reconfiguration

A rate or layout change contributes these reconciliation phases:

`prepare → suppress → configure → route → verify → unsuppress`

The driver refuses a material live reconfiguration unless the transition
context confirms output suppression. It validates before applying, waits for a
ready engine state, and restores both the previous active config and the owned
config file if activation fails. Failed rollback remains unready and must not be
unsuppressed by the transition coordinator.

## Resource policy

`camilladsp.instance_count` declares deployment capacity; the initial Raspberry
Pi default is one. The resolver represents each instance as a deterministic
`camilladsp:<n>` resource and allocates by descending graph priority followed by
stable node ID. Incompatible requests that exceed capacity receive
`resource_capacity_conflict`; an inactive bypass branch requests no instance.
Increasing capacity provisions additional stable node pairs and control ports but
does not change desired graph semantics.

The one-instance default is provisional until the hardware measurements in
`CAMILLADSP_BENCHMARK.md` are completed.

## Upstream compatibility references

- [CamillaDSP v4.1.3 release](https://github.com/HEnquist/camilladsp/releases/tag/v4.1.3)
- [CamillaDSP repository](https://github.com/HEnquist/camilladsp)
- [pycamilladsp v4.0.0](https://github.com/HEnquist/pycamilladsp/tree/v4.0.0)
