# Pi 5 service-recovery characterization — 2026-08-27

Status: **control-plane recovery matrix completed; candidate zero-error
criterion failed, physical audio not measured, and the fixture is not
performance-accepted**.

This record closes the declared individual and combined service-recovery
characterization on the supported `pi5-8gb-gab8-native-v1` fixture. It does not
freeze acceptance criteria. Exact topology recovered in every repetition, but
four attempts gained native PipeWire `ERR` counter values and therefore remain
invalid under the characterization hypothesis of zero programme-audio error
increments.

## Fixture and run identity

- Run: `20260827T204342.046868Z-ca25c0338b7b`
- Mode: `characterization`
- Final classification: `incomplete` / `invalid`; the runner deliberately left
  the run resumable after criteria evaluation
- Fixture comparison: `supported-fixture`, with no mismatch reason
- Runtime: CamillaDSP `4.1.3`, PCM Auto Decoder `0.2.2`, native
  PipeWire/WirePlumber, initial and measured throttling `0x0`
- Benchmark runner:
  `fed0fa3b05deab8011a69eb0e8cd46e6b68b53fb65c0bc78d8c6b00ee3728379`
- Intent adapter:
  `c80db3cf8b0945e19f0e50d3cccacde4468f286a5482ff18daf46aa62c4cd1d1`
- Workload driver:
  `21d02aa890f60bd0441d58b1c6b0e524e52602520ee1827188e8af08a8c94f50`

The run contains 42 immutable attempts: seven warm-ups and 35 measured
repetitions. Every attempt collected 60/60 sustained samples and 300/300
transition samples, for zero missed sustained or transition slots. Every
attempt ended with exact 18-link topology, processor readiness, and successful
restoration of the prior graph and service state. Physical audio was required
but unavailable, so no attempt can establish audible recovery.

## Executed matrix and topology recovery

Recovery is measured from the fault-injection marker to the first later sample
that has both exact owned topology and processor readiness. Warm-ups are
excluded. These are characterization observations, not accepted thresholds.

| Restart boundary | Measured | Invalid | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Decoder | 5 | 0 | 14.400 s | 14.800 s | 14.800 s |
| CamillaDSP | 5 | 0 | 10.800 s | 11.000 s | 11.000 s |
| Orchestrator | 5 | 0 | 22.600 s | 23.200 s | 23.200 s |
| PipeWire | 5 | 0 | 15.400 s | 16.000 s | 16.000 s |
| WirePlumber | 5 | 2 | 7.800 s | 8.400 s | 8.400 s |
| Decoder + CamillaDSP | 5 | 0 | 11.000 s | 11.400 s | 11.400 s |
| Decoder + CamillaDSP + orchestrator | 5 | 0 | 34.000 s | 34.800 s | 34.800 s |

Across all 35 measured repetitions the median topology recovery was 14.000 s,
nearest-rank p95 was 34.000 s, and maximum was 34.800 s. The three-service
boundary is consequently too slow for an interactive expectation and must be
optimized or explicitly treated as a long recovery path before acceptance.

A PipeWire restart terminates the old benchmark `pw-cat` stream by design. All
six PipeWire attempts retained that exit as
`interruptedByExpectedFault`, waited for the exact decoder capture node, then
attached a fresh programme stream. In the five measured repetitions, target
re-registration took a median 5.752 s and maximum 5.956 s. The warm-up took
5.764 s over 44 polls.

## Resource and collector observations

| Metric | Count | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Appliance CPU | 2,100 | 23.964% | 50.600% | 66.839% |
| Available memory | 2,100 | 7,219,864 kB | 7,236,224 kB | 7,282,624 kB |
| Temperature | 2,100 | 52.90 °C | 55.65 °C | 57.30 °C |
| Sustained collector, queue-inclusive | 2,100 | 364.009 ms | 390.160 ms | 1,259.433 ms |
| Transition collector, queue-inclusive | 10,500 | 54.827 ms | 92.587 ms | 868.669 ms |
| Transition-sample lateness | 10,500 | 0.116 ms | 0.170 ms | 13.616 ms |

The occasional queue-inclusive persistence duration above one second did not
block the next probe and caused no sample loss. The measured native-health
stream recorded no bounded `pw-top` timeout. Temperature remained well below
the 80 °C candidate bound and no throttling observation changed from `0x0`.

## Anomalies retained for disposition

1. Four attempts violate the candidate zero programme-audio PipeWire error
   increment: orchestrator warm-up `0013` gained 14, measured WirePlumber
   attempts `0027` and `0028` gained 31 and 42, and decoder+CamillaDSP warm-up
   `0031` gained 12. The two measured WirePlumber increments continued in
   observations after exact topology had returned, so they are not dismissed
   as a counter discontinuity at the intentional fault boundary. This is a
   product/runtime anomaly for task 7.1 disposition and blocks recovery
   acceptance.
2. The 35 measured repetitions contain 2,895 non-converged transition records
   during deliberate recovery, but only eight processor-readiness records were
   not ready. As in the CamillaDSP campaign, the persisted readiness projection
   can remain ready while the native topology is absent and is not sufficient
   as an acceptance signal by itself.
3. The full 18-link graph can encounter a generation-scoped stale node while
   links are created sequentially. A retained diagnostic attempt safely rolled
   back the first generation and began a fresh one, but a 30-second observation
   ended before the retry completed. The final matrix therefore uses the
   declared 60-second window without changing reconciliation policy.
4. Physical audio remains uncalibrated. The matrix cannot decide audible gap,
   pop/click/brief-noise behavior, analogue output correctness, or end-to-end
   recovery latency. Those fields remain `not-measured`; control-plane
   convergence is not a substitute.

## Harness findings retained during the campaign

Diagnostic runs are not aggregated with the final matrix. They exposed and
fixed: sequential sustained probes, persistence on the cadence path,
preflight work inside the timed window, repeated full-history event decoding,
an unbounded `pw-top` observation, expected `pw-cat` termination on PipeWire
restart, and replacement-stream attachment before target re-registration.
Their immutable raw directories remain on the appliance. The principal later
diagnostic identities are:

- `20260827T192332.786446Z-a8d4cfe948ee`
- `20260827T193301.667400Z-73eeadb93633`
- `20260827T194216.779365Z-4a24d45ee08e`
- `20260827T195830.693334Z-4bc52a195f61`
- `20260827T202011.704305Z-e39b65179b29`

## Evidence integrity and decision

Criteria evaluation intentionally refused to finalize an invalid campaign and
left it resumable. It nevertheless generated the complete redacted diagnostic
export. Both checksum layers verify: 739 exported files match `SHA256SUMS`, and
the detached manifest SHA-256 is
`d9a8a6c2e394888eb9f023d05da730f923edfa2c604b5c5e9846f1750522ccdb`.
The private raw evidence remains at the run path on the appliance.

The complete individual/combined service matrix, recovery correlation,
collector integrity, and restoration behavior are now characterized on
hardware. This closes task 6.5 with a failed candidate criterion and explicit
physical-audio limitation. It does not accept the recovery behavior; the
PipeWire error increments, readiness semantics, slow combined recovery, and
physical measurements must be dispositioned before criteria can be frozen.
