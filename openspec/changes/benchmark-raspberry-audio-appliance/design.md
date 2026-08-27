## Context

The current appliance is a Raspberry Pi 5 Model B Rev 1.1 with 8 GB RAM, Debian Trixie, a 27 W supply, active fan, SPDIF-to-I2S input, WONDOM GAB8 output, PipeWire 1.4, one native PipeWire `pcm-auto-decoder`, and one CamillaDSP 4 instance. The canonical TV/Bluetooth/headset routing scenario and automatic processor recovery have passed interactive hardware testing. Existing evidence also selected a 128-frame CamillaDSP period subjectively and captured short resource and restart observations, but it explicitly does not provide percentile, latency, soak, storage, or capacity acceptance.

The repository already contains an initial `deployment/benchmarks` manifest, an Ansible preparation playbook, a live-graph sampler, and dated acceptance records. They are useful starting points but still describe multiple Pi tiers, multiple processor instances, UI acceptance, and conditional PipeWire Pulse collection. This change narrows and completes that infrastructure around the only available native-PipeWire fixture. See `proposal.md` for motivation and `specs/raspberry-audio-benchmarking/spec.md` for observable requirements.

## Goals / Non-Goals

**Goals:**

- Produce one command-oriented, manifest-driven benchmark workflow that is safe to rerun on the currently deployed appliance.
- Correlate physical audio behavior, PipeWire topology, orchestration state, service logs, and resource measurements under one run identifier and monotonic time base.
- Separate imported functional acceptance, exploratory characterization, and thresholded acceptance so earlier success is retained without inventing quantitative results.
- Preserve raw, machine-readable evidence outside Git while committing small manifests, checksums, summaries, and final conclusions.
- Leave the appliance in its previously active graph and service state after fault-injection cases.

**Non-Goals:**

- Provisioning or validating a fresh operating-system image, validating upgrade independence, or changing release artifacts.
- Testing the end-user UI, other Pi models or memory tiers, multiple decoder or CamillaDSP instances, arbitrary graph capacity, or new managed-link forms.
- Treating subjective lip-sync or noise estimates as physical latency measurements.
- Tuning DSP filters for a listening room or changing decoder, DSP, routing, and reconciliation contracts as part of the benchmark itself.

## Decisions

### 1. Replace the candidate-tier matrix with one versioned fixture contract

`deployment/benchmarks/fixtures.yml` will become the source contract for a single `pi5-8gb-gab8-native-v1` fixture. It will identify the Pi, power and cooling, Debian release, input and output hardware, one decoder, one CamillaDSP process, 48 kHz native PipeWire chain, 128-frame CamillaDSP period, storage, network, Bluetooth source and headset classes, sample inventory, workloads, repetitions, and preliminary budgets.

Every run will emit a resolved fixture manifest containing observed hardware and software facts. A comparison step will reject an acceptance label when a required fact differs, while still allowing the evidence to be retained as exploratory.

This is preferred to retaining a speculative multi-tier matrix because no measurements exist for the other tiers and the user explicitly deferred them. A free-form run notebook was rejected because it cannot reliably prove that two measurements used the same fixture.

### 2. Extend the existing preparation playbook but keep execution data-driven

The Ansible benchmark playbook will install only measurement tools and read-only/safely bounded helper commands. It will not redeploy the product, install compatibility audio servers, modify the saved graph, or require a clean image. A target-side runner will consume a checked-in case manifest and create a run directory under the existing benchmark-results root.

The runner will expose `prepare`, `run-case`, `finalize`, and `restore` phases. Preparation records facts and a restore snapshot; each case validates preconditions and writes its own status; finalization computes checksums and a summary; restoration re-establishes the saved graph and service state even after an interrupted case. Destructive failure cases will be explicit and bounded to named services.

Preparation also freezes every execution, criteria, and schema contract and
records SHA-256 identities for the runner, intent adapter, and workload driver.
Run, resume, and finalization reject any live/frozen contract or implementation
drift. Resume performs marker-owned crash-journal recovery before refusing a
drifted run, preventing temporary playback or CamillaDSP state from being
stranded by a harness update.

This reuses the current deployment and collection structure rather than introducing a second orchestration stack. Driving every case directly from Ansible was rejected because long-running audio collection, transitions, and cleanup are easier to correlate and resume on the target.

### 3. Use one evidence envelope and monotonic correlation clock

Each suite, campaign, and sample will receive stable identifiers. Target-side events will use boot-relative monotonic nanoseconds plus wall-clock UTC metadata. The envelope will contain:

- resolved fixture, component-version, graph-revision, processor-config, sample, and tool manifests;
- JSON Lines time series for process/system, thermal, storage, PipeWire, topology, application state, database, and event counters;
- scoped service journals and application diagnostics beginning at a run marker;
- audio captures or capture metadata, transition markers, case outcomes, invalid-sample reasons, and restoration status;
- SHA-256 checksums for every retained file and a manifest checksum for the bundle.

Bluetooth addresses, credentials, tokens, and unrelated journal data will be redacted before an evidence bundle is exported. Large captures and raw time series remain outside Git; the report commits stable artifact locations and checksums.

Wall-clock-only correlation was rejected because NTP adjustments can distort short transition timings. Independent controller and appliance clocks will not be subtracted unless a calibration and uncertainty are recorded.

### 4. Separate imported evidence, characterization, and acceptance

The dated TV SPDIF, Bluetooth programme source, Bluetooth headset, adaptive routing, reboot, and processor-restart records will be indexed as `imported-functional`. They establish that the scenario worked on this fixture but contribute no unmeasured latency percentile.

The first automated campaign is `characterization`: it checks collection quality, obtains distributions, exposes unavailable codec fixtures or physical measurement gaps, and cannot pass the platform. Candidate budgets in the current fixture file are hypotheses, not retroactive acceptance criteria. After review, one threshold set is frozen with rationale and safety margin. A separate `acceptance` campaign then runs unchanged cases against those frozen thresholds.

This avoids discarding successful interactive work and avoids moving pass criteria after seeing acceptance data. Treating the existing short observations as acceptance was rejected because they lack controlled repetitions and raw data.

### 5. Use deterministic media and an explicit availability outcome

Benchmark inputs will be generated or acquired once, probed, and addressed by digest. The inventory will contain PCM stereo and multichannel channel-identification material, AC-3, E-AC-3, DTS, silence/no-carrier, an unsupported encoded fixture, and scripted 2.0/5.1/7.1 or menu/movie transitions. Where patent/tooling constraints prevent generation, a legally supplied fixture can be registered by codec metadata and digest.

Every format case is classified before execution as `supported`, `unsupported-by-build`, or `fixture-unavailable`. Supported cases must meet functional and performance criteria. Unsupported cases pass only when the declared safe behavior and recovery occur. Fixture-unavailable is not silently passed and remains an acceptance limitation.

This is preferred to generating media opportunistically during each run, which makes results non-comparable and can confuse missing encoder support with decoder behavior.

### 6. Measure physical audio separately from control-plane milestones

Control-plane timing will be derived from correlated application, PipeWire, and service events. Physical end-to-end latency and audible-gap duration require a deterministic marker at the programme input and captured output waveform. The fixture manifest will name the reference generator/capture path, calibration, channel, sample rate, and measured uncertainty. Cross-correlation or marker-edge analysis will produce the physical timing values and retain the source and captured waveforms.

If the necessary physical capture path is unavailable, those samples remain `not-measured`; registry convergence or listener estimates cannot substitute for them. Listener notes remain useful annotations for pop, click, burst, voice mapping, and synchronization observations.

The controller will calculate median, nearest-rank p95, maximum, valid/invalid sample counts, and uncertainty. Endpoint switching will use at least one warm-up and 20 measured cycles in each direction. Restart and processor-reconfiguration cases will use at least one warm-up and five measured repetitions. Format-transition counts will be declared per transition edge and must support the reported statistic.

### 7. Organize the workload matrix into bounded campaigns

The suite will provide independently resumable campaigns:

1. `baseline`: idle facts, active graph, exact topology, native PipeWire-only checks, 60-second idle samples, and imported-evidence index.
2. `decoder`: PCM bypass, AC-3, E-AC-3, DTS, detecting/no-carrier, unsupported input, decoder failure, and representative 2.0/5.1/7.1/menu transitions.
3. `camilladsp`: 128-frame passthrough, stereo processing, multichannel processing, channel adaptation, production-like FIR/IIR workload, profile change, bypass, invalid config, control interruption, restart, and rollback.
4. `adaptive-routing`: Bluetooth source to main, headset takeover, repeated fallback, and reconnection with continuous captured programme material.
5. `recovery`: decoder, CamillaDSP, orchestrator, PipeWire, WirePlumber, and relevant combined restarts with exact expected owned-topology convergence.
6. `boot-persistence`: reboot with saved active intent and measure service milestones, exact topology, and physical audio restoration.
7. `event-storage`: repeated endpoint/property events while sampling offered, coalesced, processed, retried, and dropped events; SQLite latency/busy errors; database, audit, diagnostic and filesystem growth; and storage writes.
8. `soak`: at least ten minutes for each principal PCM, encoded multichannel, representative DSP, and adaptive-routing workload, with transitions scheduled inside the interval.

Cases that disrupt audio require an explicit case name and restoration guard. The matrix remains single-chain; it will not infer multi-instance capacity from spare CPU or memory.

### 8. Collect high-rate transitions and low-rate sustained health

Transition campaigns will collect application/PipeWire topology and process readiness at 100–250 ms cadence where tool overhead permits. Sustained workloads will sample CPU, RSS, available memory, temperature, clocks, throttling, disk counters, database sizes, and service health once per second. PipeWire xruns and processor queue/underrun/overrun counters will be captured from their native sources, not inferred from CPU.

The runner records completed samples separately from missed schedule slots and
never schedules a boundary at or after the declared measurement end. Sustained
and transition collector intervals include probes through durable payload
persistence and are summarized separately. Interval records themselves are
persisted after the background worker joins. The worker must join before
workload stop, restoration, or finalization even when the case deadline has
expired, preventing post-restoration writes and mutable workload overlap.

The harness will measure its own idle overhead and record sample loss. If collection overhead materially changes the workload or misses required samples, the case is invalid and must be rerun with a justified collection profile.

This two-rate approach preserves transition visibility without burdening every ten-minute soak with unnecessary high-rate subprocess polling.

### 9. Derive recommendations only through an evidence mapping

The report will map each configurable timing, retry, queue, history, retention, diagnostic, or graph bound to the cases that exercise it. A recommendation records measured p95 and maximum, safety margin, failure mode, operational trade-off, and intended configuration key. Values without a direct measurement remain undecided; current values can remain operational but are not described as benchmark-supported.

The graph bound is limited to the accepted canonical single chain and event pressure tested here. General subgraph depth, arbitrary graph size, advanced link forms, and instance capacity remain outside this change.

This is preferred to selecting broad limits from idle CPU headroom or software-only unit tests.

### 10. Generate summaries from raw data and review anomalies explicitly

A deterministic summarizer will validate the evidence schema, flag missing metrics, compute distributions, evaluate frozen criteria, and render per-case tables plus an overall report skeleton. Human review adds subjective observations, hardware caveats, unsupported-format interpretation, and the final decision without editing computed values.

Every anomaly receives a disposition: invalidate and rerun, accepted known limitation, product defect, fixture defect, or unsupported case. The final decision can be `accepted`, `conditionally accepted`, or `not accepted`; it cannot be accepted while a required case is missing or failing.

Hand-maintained summary arithmetic was rejected because it is hard to reproduce and easy to detach from the underlying samples.

## Risks / Trade-offs

- **[Physical loopback or capture hardware is unavailable]** → Keep control-plane data but mark physical latency and gap cases not measured; do not claim final acceptance until a calibrated capture path is recorded.
- **[Bluetooth radio conditions cause high variance]** → Record device firmware, codec, adapter, distance and radio context; use 20 cycles per direction and retain every valid sample rather than selecting favorable trials.
- **[Some encoded fixtures cannot be generated with installed tools]** → Register pre-generated, probed, checksummed material or report `fixture-unavailable`; never reinterpret absence as a decoder pass.
- **[Fault injection leaves audio unavailable]** → Snapshot active intent, guard destructive operations by case ID, enforce timeouts, and run restoration plus exact-topology verification after every case and on interrupted-run recovery.
- **[Measurement overhead distorts results]** → Benchmark the collector, use separate transition and sustained cadences, report lost samples, and invalidate overloaded runs.
- **[Harness or contract changes split a run across implementations]** → Freeze and hash all contracts plus the runner, adapter, and workload driver at preparation; reject drift and require a newly prepared run after safe restoration.
- **[A ten-minute soak misses rare long-term faults]** → Treat ten minutes as practical initial acceptance, publish the duration prominently, and retain a reusable harness for later longer campaigns.
- **[Existing candidate budgets conflict with observed behavior]** → Treat them as characterization hypotheses, freeze reviewed thresholds before the independent acceptance campaign, and preserve both versions with rationale.
- **[Sensitive device identifiers leak through evidence]** → Redact Bluetooth addresses, tokens, credentials, and irrelevant journal fields before export; validate redaction in the finalization step.

## Migration Plan

1. Narrow and version the fixture/case/evidence schemas while retaining links to existing dated functional records.
2. Extend benchmark preparation, target runner, collectors, restoration guard, waveform analyzer, and summarizer with automated tests using recorded fixtures.
3. Calibrate the physical generator/capture path and run a short harness self-test to measure collection overhead and validate redaction.
4. Run the characterization campaigns, preserve raw evidence, and review anomalies and unavailable cases.
5. Freeze conservative acceptance thresholds and their evidence/rationale in a versioned criteria file.
6. Run the independent acceptance campaign without changing cases or criteria, then publish the report and recommended defaults/bounds.
7. If the harness changes appliance state unexpectedly, run restoration, compare the saved-intent and static-state digests, and remove only benchmark-owned helpers; no product database migration is involved.
