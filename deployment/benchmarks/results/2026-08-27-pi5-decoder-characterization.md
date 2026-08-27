# Pi 5 decoder characterization — 2026-08-27

Status: **automated decoder cases characterized; two manual fixtures remain
unavailable and the fixture is not performance-accepted**.

This record indexes the decoder characterization for the supported
`pi5-8gb-gab8-native-v1` fixture. It does not freeze acceptance criteria or
claim physical end-to-end timing.

## Fixture and run identity

- Run: `20260827T130415.615276Z-c251c6843ef4`
- Mode: `characterization`
- Final status: `characterized`
- Attempts: 36, with no invalid sample
- Benchmark runner:
  `e63c0a6998f36fc755955be6f63c4813f85f716897c20dddc26c0f46e3a9fe23`
- Intent adapter:
  `0c439aabaaab02a383480a9ef3e9893bc37811d6d13b7524251c3567ce9f1cd3`
- Workload driver:
  `c981117758240eb149bbed116d3327578a90823f32be4abb230c095ed493e698`

## Executed matrix

| Case | Result |
| --- | --- |
| PCM stereo bypass/stable output | Characterized |
| AC-3 5.1 | Characterized |
| E-AC-3 5.1 | Characterized |
| DTS 5.1 | Characterized |
| Unsupported encoded input | Characterized with its declared safe behavior |
| Decoder failure/recovery | Characterized and restored |
| No physical carrier | Fixture unavailable |
| Declared 2.0/5.1/7.1 physical transition matrix | Fixture unavailable |

All 36 executable attempts met the candidate zero PipeWire error-increment
condition. Across the valid measured samples, appliance CPU had a 15.426%
median, 37.887% nearest-rank p95, and 49.644% maximum. Temperature had a
47.40 °C median, 49.05 °C p95, and 51.25 °C maximum. Initial and measured
throttling remained `0x0`.

The no-carrier case requires control of the physical input carrier. The full
transition matrix also needs a desired graph that can inject the declared 7.1
edge into the deployed decoder contract. These are fixture limitations, not
decoder passes or regressions.

## Evidence integrity and decision

The redacted export contains 577 files. `SHA256SUMS` verifies completely and
its detached SHA-256 is
`f2dcf01d4c12edec5f0d565eb9cb9e4d44966a4eec0ca4a36050ca854f824624`.
The private raw evidence remains on the appliance.

PCM, AC-3, E-AC-3, DTS, unsupported-input safety, and decoder restart recovery
are characterized on the current native-PipeWire chain. Physical transition
timing and the unavailable carrier/7.1 fixtures remain outside this result.

