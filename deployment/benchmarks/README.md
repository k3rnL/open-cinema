# Raspberry Pi 5 single-chain benchmark procedure

This directory benchmarks one fixture only:
`pi5-8gb-gab8-native-v1` in `fixtures.yml`. It is the available Raspberry Pi 5
8 GB appliance on Debian Trixie with the 27 W supply and active fan, the
SPDIF/I2S input, WONDOM GAB8 output, one `pcm-auto-decoder`, one CamillaDSP 4
instance, native PipeWire at 48 kHz, and the selected 128-frame DSP period.

Results from another fixture are exploratory. This work does not accept the
management UI, installation from a clean image, releases, another Pi tier,
multiple processor instances, arbitrary graph capacity, or advanced link
shapes.

## Contracts and evidence

- `fixtures.yml` fixes the physical and runtime fixture plus registered and
  pending audio/profile inputs.
- `cases.yml` defines the bounded campaigns, workload and carrier state,
  repetitions, duration, boundaries, metrics, outcome class, timeout, and
  restoration action for every case.
- `criteria-policy.yml` prevents characterization hypotheses from passing the
  platform. Acceptance remains disabled until reviewed thresholds are frozen
  and addressed by SHA-256 before a separate run.
- `imported-evidence.yml` indexes the dated functional TV, Bluetooth, headset,
  reboot, and processor-restart records. Those records contain no benchmark
  latency or percentile values.
- `evidence-envelope.schema.json` and `evidence-envelope.template.yml` define
  the suite/campaign/case/sample identity, UTC and boot-relative monotonic
  clocks, workload declaration, artifacts, invalidation, restoration, and
  checksums required for an exported sample.

Raw journals, time series, and audio captures stay under the restricted target
result directory. Commit only small redacted summaries, stable raw paths, and
checksums. Never copy Bluetooth addresses, credentials, or tokens into a report.

## Prepare the measurement tools

Run only the benchmark playbook. It installs bounded measurement helpers and
the checked-in contracts; it does not redeploy Open Cinema or modify the saved
graph:

```console
cd deployment
ansible-playbook -i inventories/local.yml playbooks/benchmark.yml
```

Audio fixture generation is explicit and optional:

```console
ansible-playbook -i inventories/local.yml playbooks/benchmark.yml \
  -e open_cinema_generate_benchmark_fixtures=true
```

The preparation role records `vcgencmd get_throttled` without demanding a new
image or erasing historical flags. Each run retains the initial and final value;
the case result or fixture comparison decides whether it is valid.

## Declare carrier state for every live-graph sample

The sampler has no implicit workload. Programme audio must declare a present
carrier:

```console
sudo open-cinema-measure-live-graph \
  --case-id decoder-pcm-stereo \
  --workload-state programme-audio \
  --carrier-state present \
  60
```

An unplugged or unclocked SPDIF/I2S input is a separate characterization case,
not a programme-audio pass:

```console
sudo open-cinema-measure-live-graph \
  --case-id decoder-no-carrier-safe-silence \
  --workload-state no-carrier \
  --carrier-state absent \
  60
```

The command retains `pipewire-error-counters.json` and TSV with first, last,
delta, observed increment, and counter-reset values for every PipeWire object.
Programme-audio samples fail when an object gains errors. A declared no-carrier
sample retains starvation behavior as characterization instead of applying the
programme-audio zero-error rule.

This bounded sampler is characterization-only. It never emits an acceptance
`passed` status because it does not resolve the complete case manifest, frozen
criteria, exact topology/readiness envelope, restoration result, and checksums.
Only the future manifest-driven finalizer may classify a complete evidence
bundle against frozen acceptance criteria.

Successful and failed commands print `benchmark_evidence_directory=...`.
Unexpected failures and signals also leave `run-status.txt` in that directory.
Do not discard a failed bundle; classify its anomaly or invalidation reason.

From the controller, use the checked-in wrapper so redaction cannot hide a
remote nonzero status:

```console
deployment/benchmarks/run-live-graph-remote erwandaniel@appliance \
  --case-id decoder-no-carrier-safe-silence \
  --workload-state no-carrier \
  --carrier-state absent \
  60
```

The wrapper enables pipeline-status propagation, redacts hardware addresses and
common secret assignments, and returns the remote sampler's status unchanged.

## Campaign order

1. Validate the resolved fixture, exact native topology, imported evidence, and
   60-second collector overhead.
2. Run decoder, CamillaDSP, adaptive-routing, recovery, boot-persistence, and
   event/storage characterization exactly as declared in `cases.yml`.
3. Run each principal soak for at least ten minutes with controlled programme
   input. A missing carrier invalidates an active-audio soak.
4. Disposition every anomaly, then freeze conservative criteria with rationale
   and a digest. Characterization never becomes acceptance retroactively.
5. Repeat the unchanged required campaigns against the frozen criteria and
   generate the final report from retained raw evidence.

Control-plane timestamps never substitute for physical audio timing. Until a
generator/capture path is calibrated with its clock relationship and
uncertainty, latency and audible-gap metrics remain `not-measured`; listener
notes remain subjective observations.
