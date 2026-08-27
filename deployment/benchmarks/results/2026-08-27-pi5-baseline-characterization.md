# Pi 5 benchmark harness and baseline characterization — 2026-08-27

Status: **benchmark harness accepted for hardware characterization; baseline
characterized, not performance-accepted**.

This record closes the benchmark-only deployment/self-test and baseline cases
on the supported `pi5-8gb-gab8-native-v1` fixture. It does not freeze acceptance
criteria or replace the physical and workload campaigns that remain open.

## Fixture and run identity

- Run: `20260827T022258.981135Z-68ea7ba2b5b9`
- Mode: `characterization`
- Final status: `characterized`; both selected cases complete
- Fixture comparison: `supported-fixture`, with no mismatch reason
- Hardware/runtime: Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian 13 Trixie,
  AArch64, 27 W USB-C supply, active cooling, native PipeWire/WirePlumber;
  initial throttling and every measured throttling sample were clean (`0x0`)
- Processing boundary: one PCM Auto Decoder `0.2.2`, one CamillaDSP `4.1.3`,
  and exactly 18 of 18 Open Cinema-owned links
- Final attempts: three valid, zero invalid, zero superseded

The benchmark-only role installed the final harness with
`ok=17 changed=1 failed=0`; its immediate second application was idempotent at
`ok=17 changed=0 failed=0`. It did not redeploy the product or edit saved graph
intent. Every transition sample retained exact topology and processor
readiness.

Preparation froze the six benchmark contracts and recorded the three harness
implementation digests. Later run/finalize commands verified these SHA-256
identities before using the evidence:

| Input | SHA-256 |
| --- | --- |
| Benchmark runner | `9b1758d057bca034d6b2e34a49ba3a8347346562499aac0a90bcbab50a5ff662` |
| Intent adapter | `0c439aabaaab02a383480a9ef3e9893bc37811d6d13b7524251c3567ce9f1cd3` |
| Workload driver | `c981117758240eb149bbed116d3327578a90823f32be4abb230c095ed493e698` |
| Fixture contract | `cd40fa31fd446c209b67e91090e389a29c12bce0d571e847a4a795a3de501ee6` |
| Case contract | `57ebc3ff8203200cfe390258c939bfa3f96cf1a78def5f9303a41d745855c839` |
| Criteria policy | `3f91588dbd454d2c1cb2f21caf48ed95315e16cbde2ae100defe61e99ae1bb87` |
| Fixture schema | `8897f2a9a856076edfd0d3c9eccf986ba80b288ff92d07ecf70b4318ce651a9d` |
| Case schema | `a204070f43c65921e35deafcddba4ad1b7f5f0ff3243918c77e9cc479ddffbfb` |
| Evidence schema | `0b15f9dfbc3c38f9c17b1c34d20dac8094f338c0c47812fe2e32d673bf2a2c3f` |

## Sample accounting

The fresh run needed no retry:

| Case/unit | Sustained samples | Transition samples | Missed slots | Topology/processors |
| --- | ---: | ---: | ---: | --- |
| Fixture/topology sample | 1/1 | 5/5 | 0 | converged/ready |
| Collector warm-up | 60/60 | 300/300 | 0 | converged/ready |
| Collector measured repetition | 60/60 | 300/300 | 0 | converged/ready |

Completed samples and missed schedule slots are separate counters, and no
boundary is scheduled at or after the declared measurement end. The background
collector joined before workload stop or restoration. Sustained and transition
overhead intervals cover their probes through durable payload persistence;
their own interval records are written after collection.

An earlier diagnostic run is superseded rather than accepted because it
predated implementation-identity enforcement and measured only part of the
collector path. Its private raw data remains useful engineering history, but no
number from it is used below.

## Measured baseline result

Warm-up evidence is excluded. These final statistics combine the one-second
fixture sample with the measured 60-second collector repetition where the
metric exists.

| Metric (count) | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: |
| Appliance CPU (`n=60`) | 30.84% | 34.55% | 34.69% |
| Available memory (`n=61`) | 7,343,792 kB | 7,355,712 kB | 7,396,128 kB |
| Sustained collector batch (`n=61`) | 261.53 ms | 285.11 ms | 313.49 ms |
| Transition collector batch (`n=305`) | 163.15 ms | 198.02 ms | 254.87 ms |
| Transition-sample lateness (`n=305`) | 0.072 ms | 1.369 ms | 55.043 ms |
| Temperature (`n=61`) | 51.25 °C | 52.90 °C | 52.90 °C |

The CPU and interval figures characterize the deliberately intensive benchmark
collectors, including subprocess probes and durable evidence writes; they are
not uninstrumented appliance-idle measurements. Zero scheduled samples were
lost, the topology remained exact, and processors remained ready. This is a
characterization result, not a frozen performance threshold.

## Evidence integrity and privacy boundary

Finalization covered 55 redacted-export files. `SHA256SUMS` verifies completely,
and its detached SHA-256 is
`12fa1ede796199de5704af3a1c8dc8a4933a31a13db013ac9af555c318ac7f74`.
Raw samples and appliance object identifiers remain in the private target
evidence directory; this small report is the publication boundary.

After finalization, the appliance still reported eight of eight coordinated
system services and both user-session audio services active, aggregate
readiness `passed`, appliance-mode immutable input, exact 18-link convergence,
and the installed manifest digest
`c1838de6097050242413ab32684110287e50307513ba67b53e2619936aa38dd2`.

## Decision and remaining work

Benchmark deployment, frozen-input enforcement, preflight, resumption,
deadline/sample accounting, worker draining, redaction, checksums,
deterministic statistics, and the baseline campaign work on the supported
fixture. The functional TV, encoded processing, Bluetooth programme-source,
headset takeover/fallback, and reboot evidence is imported without inventing
timing values.

Still open are calibrated physical capture, decoder and format-transition
campaigns, CamillaDSP profile/failure campaigns, 20-cycle adaptive routing,
service recovery, boot/storage/event characterization, ten-minute soaks,
criteria freezing, acceptance reruns, and the final supported-platform report.
