## 1. Narrow and version the benchmark contracts

- [x] 1.1 Replace the speculative candidate-tier fixture matrix with a versioned `pi5-8gb-gab8-native-v1` contract covering Debian Trixie, 27 W power, active cooling, SPDIF/I2S input, WONDOM GAB8 output, one decoder, one CamillaDSP instance, native PipeWire, 48 kHz, and a 128-frame DSP period.
- [x] 1.2 Add a versioned case manifest that declares campaign, input and processor fixtures, warm-up, measured repetitions, duration, measurement boundaries, required metrics, restoration action, and supported/unsupported outcome for every case.
- [x] 1.3 Define and validate the raw evidence envelope for suite, campaign, case, and sample identifiers; monotonic and UTC timestamps; manifests; JSON Lines samples; logs; captures; invalidation; restoration; and checksums.
- [x] 1.4 Define separate characterization and acceptance criteria states so candidate budgets cannot pass a platform and frozen acceptance budgets cannot be changed by a running campaign.
- [x] 1.5 Add an imported-evidence index for the dated TV SPDIF, Bluetooth source, headset takeover/fallback, active-graph reboot, and processor-restart records, clearly marking their functional results and missing quantitative measurements.
- [x] 1.6 Rewrite the benchmark procedure around the one supported fixture, native PipeWire-only operation, raw-evidence retention, privacy redaction, and explicit exclusions for UI, clean installation, releases, other Pi tiers, multi-instance capacity, and advanced link shapes.

## 2. Build the repeatable target harness and collectors

- [x] 2.1 Update the benchmark Ansible playbook and roles to install the declared measurement tools and bounded helpers without redeploying the product, requiring a clean image, or installing/querying PulseAudio compatibility tools.
- [ ] 2.2 Implement a manifest-driven benchmark runner with `prepare`, `run-case`, `finalize`, and `restore` phases, resumable case status, explicit timeouts, and a unique evidence directory per run.
- [ ] 2.3 Implement run and sample identifiers plus boot-relative monotonic timestamps, UTC metadata, clock-calibration records, and guards against subtracting unsynchronized controller and appliance clocks.
- [ ] 2.4 Implement fixture preflight and fact collection for hardware revision, RAM, power/cooling declaration, OS/kernel, storage, network, audio interfaces, Bluetooth fixture metadata with redacted addresses, graph revision, processor configs, component/tool versions, and initial throttling state.
- [ ] 2.5 Implement one-second sustained collection for per-process and appliance CPU, RSS, available memory, temperature, clocks, throttling, service state, disk counters, filesystem space, and collector overhead/sample loss.
- [ ] 2.6 Implement 100–250 ms transition collection for PipeWire registry state, exact expected owned topology, decoder/CamillaDSP readiness, resolved-plan and reconciliation state, generation/sequence, retry state, and audio-restoration markers.
- [ ] 2.7 Collect native PipeWire xrun/drop facts, decoder and CamillaDSP underrun/overrun/queue facts, scoped service errors, and journals beginning at an explicit run marker.
- [ ] 2.8 Collect offered, processed, coalesced, retried, and dropped orchestration events together with SQLite latency/busy results, Redis observations, plan/audit/diagnostic growth, filesystem writes, and retained-record counts.
- [ ] 2.9 Implement final evidence redaction, schema validation, SHA-256 manifests, deterministic statistics, invalid-sample exclusion with reasons, and a small human-readable case summary.
- [ ] 2.10 Implement an interruption-safe restoration guard that snapshots active intent and service state, bounds fault injection to named services, restores the prior graph, and verifies exact topology plus static/dynamic state digests after every disruptive case.

## 3. Prepare deterministic audio and physical timing fixtures

- [ ] 3.1 Create or register checksummed PCM stereo/multichannel channel-identification, AC-3, E-AC-3, DTS, silence/no-carrier, and unsupported-format samples with generation provenance and `ffprobe` metadata.
- [ ] 3.2 Create checksummed, marker-bearing 2.0-to-menu, 5.1-to-menu, 7.1-to-menu, and representative cross-format transition sequences that expose decoder detection and stable-output behavior.
- [ ] 3.3 Define representative CamillaDSP 128-frame passthrough, stereo, multichannel, channel-adaptation, and production-like FIR/IIR profiles with workload metadata and configuration digests.
- [ ] 3.4 Select, document, and calibrate the physical programme generator and output-capture path, including channel, rate, conversion stages, clock relationship, loopback baseline, and timing uncertainty.
- [ ] 3.5 Implement waveform marker/cross-correlation analysis for end-to-end latency, audio-loss and restoration edges, unexpected silence, discontinuity, clipping, and audible-gap duration while retaining source/captured artifacts.
- [ ] 3.6 Add deterministic synthetic-waveform tests for latency/gap analysis, channel mapping, uncertainty propagation, missing markers, corrupted captures, and subjective-note separation.

## 4. Define bounded benchmark campaigns

- [x] 4.1 Define the baseline campaign for fixture validation, native PipeWire-only checks, exact active topology, imported evidence, idle health, and a 60-second collector-overhead sample.
- [x] 4.2 Define the decoder campaign for PCM bypass, AC-3, E-AC-3, DTS, detecting/no-carrier, unsupported input, decoder failure/recovery, stable single-output verification, and declared format/layout transition edges.
- [x] 4.3 Define the CamillaDSP campaign for every representative 128-frame profile, profile replacement, bypass, invalid configuration, control interruption, restart, last-working rollback, and audio/readiness restoration.
- [x] 4.4 Define the adaptive-routing campaign with continuous Bluetooth programme audio, headset takeover, headset-to-main fallback, and reconnection, using one warm-up plus at least 20 measured cycles in each switch direction.
- [x] 4.5 Define the recovery campaign for individual decoder, CamillaDSP, orchestrator, PipeWire, and WirePlumber restarts plus relevant combined processor/orchestrator boundaries, using one warm-up and at least five measured repetitions.
- [x] 4.6 Define the boot-persistence campaign from boot marker through ordered service readiness, exact topology convergence, saved graph/binding/profile verification, and captured programme-audio restoration without manual Apply.
- [x] 4.7 Define the event-and-storage campaign with bounded endpoint/property bursts and repeated transitions while measuring event accounting, convergence, SQLite contention, history/diagnostic growth, retention, and storage writes.
- [x] 4.8 Define at-least-ten-minute soak cases for principal PCM, encoded multichannel, representative DSP, and adaptive-routing workloads with scheduled transitions and full resource, thermal, audio-health, persistence, and storage sampling.

## 5. Verify and deploy the harness

- [x] 5.1 Add automated schema and cross-reference tests proving every required case has a compatible fixture, metric set, restoration action, sample count, duration, outcome class, and criteria mapping.
- [ ] 5.2 Add runner lifecycle tests for successful, failed, timed-out, invalid, resumed, and interrupted cases and prove finalization never treats incomplete evidence as accepted.
- [ ] 5.3 Add recorded-fixture tests for collectors, monotonic ordering, topology convergence, event accounting, redaction, checksum manifests, median/nearest-rank-p95/maximum calculations, and collector-overhead invalidation.
- [ ] 5.4 Exercise every disruptive campaign against a simulated or recorded service fixture and verify restoration runs on success, failure, timeout, and interruption before enabling it on hardware.
- [ ] 5.5 Deploy the benchmark-only roles to the Pi, run preflight and a short self-test, verify no product/static-state drift or sensitive-data leak, and record collector overhead before hardware characterization.

## 6. Run hardware characterization

- [ ] 6.1 Run and retain baseline characterization, reconcile observed fixture facts with the contract, validate initial power/thermal state, and link the previously passed functional evidence without assigning it new timing values.
- [ ] 6.2 Run all decoder and format-transition characterization cases, recording unavailable fixtures and unsupported-by-build behavior distinctly from regressions.
- [ ] 6.3 Run all CamillaDSP 128-frame profile, reconfiguration, invalid-config, control-loss, restart, and rollback characterization cases.
- [ ] 6.4 Run at least 20 measured headset-takeover and 20 headset-fallback cycles with continuous Bluetooth programme audio and physical switch/gap capture.
- [ ] 6.5 Run the individual and combined service recovery characterization matrix, correlating exact topology, registry convergence, physical audio restoration, retries, warnings, and brief noise artifacts.
- [ ] 6.6 Run boot-persistence and event/storage characterization, verifying saved intent and measuring boot readiness, event throughput, database contention, retention growth, diagnostic size, and bytes written.
- [ ] 6.7 Run every declared ten-minute-or-longer soak, retain full raw samples and captures, and disposition xruns, queue faults, convergence failures, resource drift, temperature, throttling, and storage anomalies.

## 7. Freeze criteria, accept the fixture, and publish results

- [ ] 7.1 Validate every characterization evidence bundle and disposition each anomaly as invalid/rerun, known limitation, product defect, fixture defect, unsupported case, or accepted observation.
- [ ] 7.2 Freeze conservative acceptance criteria from characterization evidence with declared safety margins, failure modes, rationale, and an immutable criteria digest before starting acceptance runs.
- [ ] 7.3 Rerun the baseline, decoder, CamillaDSP, adaptive-routing, and recovery campaigns unchanged against the frozen criteria and retain all valid and invalid samples.
- [ ] 7.4 Rerun boot-persistence, event/storage, and every required ten-minute soak unchanged against the frozen criteria and retain the complete evidence bundles.
- [ ] 7.5 Generate the acceptance summary from raw data and verify case classification, evidence paths/checksums, redaction, statistics, criteria digest, fixture/version identity, and restoration status independently.
- [ ] 7.6 Map measured results to conservative timing, retry, queue, history, retention, diagnostic, and canonical single-chain graph recommendations; leave every unmeasured or failed bound explicitly undecided.
- [ ] 7.7 Publish the Pi 5 8 GB single-chain report with methods, imported evidence, measured results, subjective observations, anomalies, limitations, unsupported and rejected cases, recommendations, and the overall accepted/conditional/not-accepted decision.
- [ ] 7.8 Update supported-platform and benchmark documentation to reference only conclusions justified by the final report, without claiming UI, clean-install, release, other-tier, multi-instance, or advanced-link acceptance.
