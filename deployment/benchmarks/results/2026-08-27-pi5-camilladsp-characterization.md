# Pi 5 CamillaDSP characterization — 2026-08-27

Status: **control plane characterized; physical audio not measured and the
fixture is not performance-accepted**.

This record closes the declared CamillaDSP characterization campaign on the
supported `pi5-8gb-gab8-native-v1` fixture. It does not freeze acceptance
criteria. End-to-end latency, audible gaps, and physical output correctness
remain undecided until the programme-generator/output-capture path is
calibrated.

## Fixture and run identity

- Run: `20260827T162052.233835Z-b5722d5f5057`
- Mode: `characterization`
- Final status: `not-measured`; no incomplete case
- Fixture comparison: `supported-fixture`, with no mismatch reason
- Runtime: CamillaDSP `4.1.3`, PCM Auto Decoder `0.2.2`, native
  PipeWire/WirePlumber, initial throttling `0x0`
- Benchmark runner:
  `b4797d55ca7ad38cd70fdb9f9db61a57c649177eb1868d21b9d627a0848899e7`
- Intent adapter:
  `c80db3cf8b0945e19f0e50d3cccacde4468f286a5482ff18daf46aa62c4cd1d1`
- Workload driver:
  `521524a505d32e4b288d47e025d7f524178b44ac5fb41a061e95b8d33de114fc`

The run contains 54 immutable attempts: 9 warm-ups and 45 measured
repetitions. There are zero invalid, failed, interrupted, retried, or
superseded attempts. Every attempt restored the prior graph and exact engine
configuration. All 54 collected native-audio health and topology/readiness;
36 also collected sustained health and 30 collected transition timing. Every
attempt is `not-measured` only because calibrated physical audio was a required
but unavailable metric.

The 7.1-to-stereo channel-adaptation case is retained as
`fixture-unavailable`: it changes the fixed eight-channel processing bus and
needs a separately published topology-changing graph fixture.

## Executed matrix

| Case | Measured repetitions | Control-plane result |
| --- | ---: | --- |
| 128-frame passthrough profile | 5 | completed and restored |
| 128-frame stereo profile | 5 | completed and restored |
| 128-frame multichannel profile | 5 | completed and restored |
| 128-frame production FIR/IIR profile | 5 | completed and restored |
| Profile replacement | 5 | completed and restored |
| Bypass | 5 | completed and restored |
| Invalid configuration rejection | 5 | rejected without activation; restored |
| CamillaDSP control interruption | 5 | service returned and programme stream reattached |
| Restart and last-working rollback | 5 | service/profile returned and programme stream reattached |

The invalid candidate uses a negative chunk size. CamillaDSP 4.1.3 accepts
zero as an automatic/default chunk size, so the earlier zero-valued probe did
not test rejection. Diagnostic run
`20260827T144615.776876Z-9ff441a1a31e` is therefore superseded and is not
combined with this run.

## Measured control-plane observations

Warm-ups are excluded from these raw-evidence calculations. They are
engineering observations from `not-measured` envelopes, not frozen acceptance
thresholds.

| Metric | Count | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Managed compatible-profile activation | 30 | 38.652 s | 39.482 s | 39.514 s |
| Prior-intent/Camilla readiness restoration | 30 | 44.894 s | 45.853 s | 46.257 s |
| Transition-sample lateness | 13,500 | 0.107 ms | 0.165 ms | 114.206 ms |
| Production FIR/IIR CamillaDSP processing load | 300 | 3.477% | 4.892% | 7.791% |

Passthrough, stereo, and multichannel processing-load medians were 0.084%,
0.110%, and 0.137% respectively. CamillaDSP reported zero clipped samples,
and no native-health record reported a PipeWire maximum-error value.

The approximately 39-second activation and 45-second restoration paths are
stable but too slow for an interactive graph switch. They include the complete
managed desired-intent/reconciliation boundary rather than only the CamillaDSP
configuration call. They require optimization and a separate rerun before any
user-facing timing recommendation is frozen.

## Anomalies retained for disposition

1. During the five measured control-interruption samples, decoder queue
   overflows increased by 9,501 in aggregate. During the five restart/rollback
   samples they increased by 6,727. Compatible profile operations showed only
   small counter changes. This is consistent with the decoder continuing to
   produce while the downstream CamillaDSP nodes are absent, but it must be
   classified during anomaly review rather than treated as accepted behavior.
2. The deliberate service outages produced 558 transition records with
   non-converged exact topology and 56 native CamillaDSP records outside
   `running`/`paused`, as expected during recovery. The persisted processor
   readiness projection nevertheless remained `ready` in every transition
   record. Its freshness/meaning must be corrected or explicitly bounded
   before it can be an acceptance signal.
3. Physical audio is uncalibrated. No number in this record establishes
   end-to-end latency, audible-gap duration, channel correctness, clipping at
   the analogue output, or subjective quality.

## Evidence integrity and decision

The private raw and redacted evidence remain at the run path on the appliance.
Finalization verified 860 exported files. `SHA256SUMS` verifies completely and
its detached SHA-256 is
`1495d61888bdd7afd159388d2a418b12be7161f0083b96bb5c7e5f2ff9b95cfa`.

The managed profile, replacement, bypass, invalid-configuration, control-loss,
restart, last-working rollback, and post-sample restoration paths are exercised
on hardware. This closes characterization task 6.3, but the result remains
conditional on physical calibration and anomaly disposition. It does not
accept the platform or define release criteria.
