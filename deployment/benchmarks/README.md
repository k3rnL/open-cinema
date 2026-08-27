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

- `fixtures.yml` fixes the physical and runtime fixture plus each input and
  processor fixture's bounded automation binding. A `manual` binding is an
  unavailable automated case, not permission for the runner to guess at a
  Bluetooth or physical action.
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

Preparation also freezes the six benchmark contracts and records SHA-256
identities for the runner, intent adapter, and workload driver. Every
`run-case`, `--resume`, and non-finalized `finalize` command must still match
those frozen inputs. If contracts or implementation change, restore any active
run before preparing a new one; evidence from different harness versions is
never combined under one run identifier.

The supported Raspberry Pi fixture uses `wlan0` for controller access. Network
throughput and latency are outside the audio benchmark boundary, and Bluetooth
radio measurements remain separate from the controller-network declaration.

## Prepare the measurement tools

Run only the benchmark playbook. It installs bounded measurement helpers, the
target workload driver, and the checked-in checksummed media/profile fixtures;
it does not redeploy Open Cinema or modify the saved graph:

```console
cd deployment
ansible-playbook -i inventories/local.yml playbooks/benchmark.yml
```

The preparation role records `vcgencmd get_throttled` without demanding a new
image or erasing historical flags. Each run retains the initial and final value;
the case result or fixture comparison decides whether it is valid.

## Run the manifest-driven harness

Prepare a unique evidence directory for one case or a complete campaign. This
captures the fixture, component/tool versions, clock calibration, journal
marker, active intent, service state, exact owned topology, and static/dynamic
digests before any fault injection:

```console
sudo open-cinema-benchmark prepare --case-id decoder-pcm-stereo
# benchmark_run_id=20260826T200000.000000Z-0123456789ab
```

Execute and resume only cases selected during `prepare`:

```console
sudo open-cinema-benchmark run-case RUN_ID decoder-pcm-stereo
sudo open-cinema-benchmark run-case RUN_ID decoder-pcm-stereo --resume
```

Each retry receives a new immutable attempt directory. Failed, invalid, and
interrupted attempts remain in the run as evidence; resume never deletes or
overwrites their raw data.

On resume, benchmark crash journals are restored before input-drift checks. This
ensures a changed harness cannot strand a synthetic stream or temporary
CamillaDSP configuration while refusing to continue the old evidence run.

Every command and schedule is bounded by the checked-in case manifest. Runtime
fault injection is restricted to the exact systemd units allowed by the case's
restoration action. A disruptive sample restores the saved active graph through
OpenCinema's compare-and-swap activation service and restores the initial
service state. It then verifies exact stable topology plus static and semantic
user-intent digests on success, failure, timeout, or interruption. Generated
database sequence values are retained as observations, not rewritten by the
benchmark. Before mutating playback or CamillaDSP state, the workload driver
writes a private crash journal containing the owned process identity and exact
prior CamillaDSP configuration. Resume and the explicit restore guard clean
only marker-owned benchmark process groups and restore that configuration
before graph and service verification. If automatic restoration reports a
failure, stop and run the
explicit guard before doing anything else:

```console
sudo open-cinema-benchmark restore RUN_ID
```

### Executable workload boundary

For registered PCM and IEC-61937 cases, `run-case` verifies the fixture size and
SHA-256, loops it in real time through FFmpeg, and creates an ephemeral
`pw-cat` stream targeted only at the declared decoder or CamillaDSP capture
node. It stops that process on success, failure, timeout, and interruption. A
PipeWire or processor service fault also restarts the synthetic programme
stream so recovery is measured under audio rather than silence.

Startup succeeds only after the feeder and player are alive and PipeWire shows
an active link to the exact declared target. The runner repeats those checks
during sustained and transition sampling; an early process exit or lost link
fails the sample. Playback logs are retained inside the sample envelope,
checksummed, and included in the redacted export.

CamillaDSP profile cases read the current active configuration and apply only a
checked-in processing overlay. The active PipeWire capture/playback device
names, groups, and channel bus remain unchanged. The exact prior configuration
is restored before the graph/service restoration check. The 7.1-to-stereo
profile is deliberately unavailable because it changes the active output bus
and therefore needs its own published desired-graph fixture.

The automatically executable control-plane set includes PCM, AC-3, E-AC-3, DTS,
unsupported-carrier safe behavior, decoder failure recovery, compatible
CamillaDSP profiles/replacement/bypass/invalid-config rejection, CamillaDSP
control/restart recovery, the service recovery matrix, and the PCM, encoded,
and DSP soaks. Scheduled soak markers execute their declared stream switch,
stream refresh, or profile reapply/restore action; they are not passive labels.
Cases that require calibrated physical-audio capture still execute their safe
control-plane work, but remain `not-measured` until that capture is available.

The runner does not connect/disconnect a headset, start phone/TV programme
audio, remove the physical SPDIF carrier, reboot the appliance, inject product
event bursts, or apply a channel-count-changing graph. Those cases prepare as
`fixture-unavailable` with a reason until their physical/operator or product-API
driver exists. Also keep the physical TV source silent during synthetic decoder
playback; an unrelated carrier contaminates the sample and must be recorded as
invalid.

Finalization validates every sample envelope, applies frozen/candidate criteria,
excludes invalid samples from deterministic median/nearest-rank-p95/maximum
statistics, captures the unit-scoped journal after the explicit marker, and
creates a redacted export with `SHA256SUMS` and its detached digest:

```console
sudo open-cinema-benchmark finalize RUN_ID
```

Every envelope records `metricCoverage` for each required metric set. Missing
automated artifacts invalidate a sample; an unavailable required calibrated
physical capture produces `not-measured`. Neither state can characterize or
accept a run.

Collector evidence distinguishes completed samples from missed schedule slots.
The sustained and transition overhead distributions cover each probe through
durable persistence of its payload; interval-accounting files are written only
after the background collector has joined. On success, failure, timeout, or
interruption, that join completes before workload stop and appliance
restoration, so no collector can write into an already restored state.

Finalizing an incomplete or invalid run returns nonzero and leaves it resumable.
A characterization run can only become `characterized`; only a distinct run
using reviewed, frozen acceptance criteria can become `accepted`.

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
