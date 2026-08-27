## Purpose

Define reproducible performance and stability acceptance for the supported single-chain Raspberry Pi 5 audio appliance, with raw evidence from which conservative operating limits can be selected.

## ADDED Requirements

### Requirement: Benchmark scope is fixed and explicit
The benchmark suite SHALL identify the device under test as the available Raspberry Pi 5 8 GB running Debian Trixie with a 27 W power supply, active fan, WONDOM GAB8 output, native PipeWire routing, one `pcm-auto-decoder` instance, and one CamillaDSP instance. Results MUST NOT be represented as acceptance of another Raspberry Pi tier, operating system, output device, processing-instance count, UI workflow, or managed-link shape.

#### Scenario: Supported fixture is measured
- **WHEN** an acceptance benchmark begins on the declared fixture
- **THEN** the evidence records the hardware revision, memory, power, cooling, operating-system and kernel versions, audio interfaces, and all coordinated component versions

#### Scenario: Fixture differs from the supported scope
- **WHEN** any material fixture property differs from the declared fixture
- **THEN** the run is labelled exploratory and cannot replace the supported-fixture acceptance result

### Requirement: Runs are repeatable and evidence is auditable
The benchmark suite SHALL define repeatable samples, input material, graph and processor configurations, warm-up, run duration, repetition count, measurement boundaries, clocks, collection commands, and pass criteria before an acceptance run. It SHALL retain timestamped raw samples, logs, configuration and sample digests, environment metadata, summaries, and the exact invocation needed to reproduce each result. Preparation SHALL freeze and digest every benchmark contract, workload registry, physical-path declaration, and registry-referenced media, profile, and filter asset and SHALL record the runner, intent-adapter, and workload-driver implementation digests. Samples SHALL consume those frozen workload inputs. Run, resume, and finalization SHALL reject input drift instead of combining evidence across implementations.

#### Scenario: An acceptance run completes
- **WHEN** the harness finishes a benchmark case
- **THEN** it writes a uniquely identified evidence bundle containing raw machine-readable measurements, metadata, logs, digests, and a human-readable case summary

#### Scenario: A sample is incomplete or contaminated
- **WHEN** collection loses a required metric, the fixture changes, or unrelated workload invalidates a sample
- **THEN** the harness marks that sample invalid with a reason and does not silently include it in accepted statistics

#### Scenario: Benchmark inputs change after preparation
- **WHEN** a contract, schema, workload registry or referenced asset, runner, intent adapter, or workload driver differs from the identity frozen at preparation
- **THEN** the harness restores marker-owned temporary workload state, refuses to add or classify evidence under that run identifier, and requires a newly prepared run

### Requirement: Canonical adaptive routing remains accepted and becomes quantitative
The acceptance report SHALL import the existing successful TV-to-main-speakers, Bluetooth programme-source, headset takeover, headset removal/fallback, and active-graph reboot evidence as the functional baseline. It SHALL repeat the Bluetooth-to-headset and headset-to-main transitions enough times to report sample count, median, p95, and maximum route-switch latency and audible-gap duration without requiring graph reapplication.

#### Scenario: Prior functional evidence is imported
- **WHEN** the benchmark report establishes its functional baseline
- **THEN** it references the dated evidence for successful TV, Bluetooth, headset takeover, fallback, and reboot behavior instead of claiming that evidence was newly collected

#### Scenario: Endpoint priority changes repeatedly
- **WHEN** the headset connects and disconnects while a Bluetooth programme source is playing
- **THEN** every cycle records the requested and observed route, convergence result, switch latency, audible gap, errors, xruns, and any pop, click, or noise observation

### Requirement: Decoder formats and transitions are characterized
The benchmark suite SHALL exercise PCM, AC-3, E-AC-3, and DTS inputs that are supported by the decoder build, transitions among representative stereo and multichannel formats, detecting or unknown input, and at least one unsupported-format case. The report SHALL distinguish unsupported-by-design behavior from regression and SHALL verify that the decoder exposes one stable PipeWire output contract across supported transitions.

#### Scenario: Supported encoded and PCM cases run
- **WHEN** each available supported PCM or encoded fixture is played through the active chain
- **THEN** the evidence records detection time, selected format, decoded layout, stable output contract, convergence, audible result, processor health, and transition timing

#### Scenario: Input is unknown or unsupported
- **WHEN** the decoder cannot yet identify the input or the format is unsupported
- **THEN** the chain follows its declared silence, error, or recovery behavior without stale routing, uncontrolled noise, or processor crash, and the report records that behavior explicitly

#### Scenario: Programme format changes
- **WHEN** playback moves between representative 2.0, 5.1, and 7.1 content or returns to a menu format
- **THEN** the stable decoder output remains usable while detection, reconfiguration, audible gap, channel layout, and recovery are measured for the transition

### Requirement: CamillaDSP is measured at the selected native PipeWire period
The benchmark suite SHALL exercise the single CamillaDSP instance at a 128-frame processing period with representative passthrough, stereo, multichannel, channel-adaptation, and production-like filtering profiles whose filter sizes and configuration digests are recorded. It SHALL include profile replacement, bypass where supported, rejected invalid configuration, control interruption, processor restart, and rollback to the last working configuration.

Supported profile workloads SHALL be published as benchmark-only Open Cinema
profile and graph resources and selected through desired-intent activation.
They SHALL NOT compete with the orchestrator by installing a raw live
CamillaDSP configuration. The prepared user intent and engine configuration
MUST be restored and observed converged after every managed profile sample.

#### Scenario: Representative profiles run under programme audio
- **WHEN** each declared CamillaDSP profile is active for its benchmark interval
- **THEN** the evidence records configuration digest, channels, sample rate, filter workload, processing time, CPU, memory, xruns, latency, and audible health

#### Scenario: CamillaDSP configuration or process fails
- **WHEN** an invalid configuration, control interruption, or process restart is injected
- **THEN** the chain reaches its declared safe state, recovers or rolls back, and records failure-detection, suppression, readiness, restoration, and audible-gap timings

### Requirement: Timing boundaries are measured consistently
The benchmark suite SHALL measure end-to-end input-to-output latency with a reproducible signal method and declared uncertainty. It SHALL separately measure endpoint-switch latency, audible gaps, decoder detection and reconfiguration, CamillaDSP prepare/configure/readiness, graph reconciliation, and recovery after individual and combined decoder, CamillaDSP, orchestrator, PipeWire, and WirePlumber restarts.

#### Scenario: End-to-end latency is sampled
- **WHEN** a timing signal traverses the full physical or documented equivalent input-to-output chain
- **THEN** the report gives sample count, method, clock relationship, uncertainty, median, p95, and maximum latency for the relevant PCM and movie-mode workloads

#### Scenario: Runtime transition is measured
- **WHEN** a route, format, profile, reconciliation, or restart transition occurs
- **THEN** the raw evidence correlates request, discovery, decision, mutation, readiness, exact owned-topology convergence, audio loss, and audio restoration timestamps

### Requirement: Resource, thermal, and runtime health is sampled
The benchmark suite SHALL collect per-process and appliance CPU, resident memory, available memory, temperature, clock, throttling state, PipeWire xruns or drops, processor underruns or overruns, reconciliation retries, event counts, queue pressure, and relevant service errors during every sustained workload and transition campaign. Event-throughput tests SHALL preserve the offered, processed, coalesced, retried, and dropped event counts. The harness SHALL distinguish completed samples from missed schedule slots, SHALL NOT schedule a sample at or after the measurement end, and SHALL measure sustained and transition collector intervals through durable payload persistence. Any background collector SHALL join before workload stop or appliance restoration, including after timeout or interruption.

#### Scenario: Sustained workload is active
- **WHEN** a benchmark workload passes warm-up and enters its measurement interval
- **THEN** timestamped resource, thermal, audio-health, topology, and service-health samples are collected at a declared cadence and summarized with appropriate percentiles and maxima

#### Scenario: Endpoint events are burst or repeated
- **WHEN** the harness generates the declared connect, disconnect, property-change, or reconciliation event sequence
- **THEN** the report correlates event load with convergence latency, queue behavior, retries, drops, CPU, and memory without counting coalesced events as lost events

#### Scenario: Collection reaches a deadline or fails
- **WHEN** a foreground or background collector fails, is interrupted, or reaches its bounded deadline
- **THEN** completed and missed counts reflect only their actual outcomes, the background worker is fully joined, no collector writes after restoration begins, and the sample retains an explicit invalidation reason

### Requirement: Boot, persistence, storage, and soak behavior is characterized
The benchmark suite SHALL measure cold service boot to complete audio readiness with an active saved graph and SHALL verify that the graph, endpoint bindings, processor configuration, and accepted active state survive the documented reboot path. Every principal workload SHALL include a practical steady-state interval of at least ten minutes, and the suite SHALL sample database contention, plan and audit growth, diagnostic retention, storage writes, and convergence during repeated transitions.

#### Scenario: Appliance boots with saved intent
- **WHEN** the supported fixture boots with the accepted graph saved and its endpoints available
- **THEN** the evidence records service milestones, readiness failures or retries, time to exact topology, time to restored audio, and persistence correctness without graphical login or manual Apply

#### Scenario: Ten-minute soak runs
- **WHEN** a principal workload remains active for at least ten minutes with its declared transition and event schedule
- **THEN** the report records stability, audio-health errors, convergence failures, resource drift, temperature, throttling, database latency, retained-record growth, and bytes written over the full interval

### Requirement: Defaults and bounds are derived conservatively
Timing defaults, retry and queue bounds, retention limits, diagnostic limits, and supported graph bounds SHALL be proposed only when the benchmark directly exercises the relevant behavior. Each selected value SHALL cite measured worst-case or percentile evidence, declared safety margin, rationale, and the configuration location that would enforce it; unmeasured limits SHALL remain explicitly undecided.

#### Scenario: Evidence supports a default
- **WHEN** all cases relevant to a proposed default or bound pass their predeclared criteria
- **THEN** the report recommends a conservative value with its evidence references, safety margin, trade-off, and verification case

#### Scenario: Evidence is absent or fails
- **WHEN** a limit was not measured or its acceptance criteria fail
- **THEN** the report leaves the value unsupported or recommends a safer restriction and does not infer capacity from idle or short-run observations

### Requirement: Acceptance reporting is complete and honest
The final report SHALL link every summarized result to raw evidence and classify each case as passed, conditionally accepted, failed, unsupported by the current build, or not measured. It SHALL document limitations, anomalies, rejected configurations, subjective observations separately from measured values, and the exact scope supported by the result.

#### Scenario: Acceptance report is reviewed
- **WHEN** all required benchmark campaigns have completed
- **THEN** the report includes fixture and version manifests, methods, criteria, results, raw-artifact paths and checksums, conservative recommendations, limitations, anomalies, and an overall single-chain Pi 5 acceptance decision

#### Scenario: An audible artifact lacks an objective measurement
- **WHEN** a listener reports a gap, noise burst, pop, click, or synchronization issue that the harness did not measure
- **THEN** the report retains it as a subjective observation and does not convert it into an invented duration or passing quantitative result
