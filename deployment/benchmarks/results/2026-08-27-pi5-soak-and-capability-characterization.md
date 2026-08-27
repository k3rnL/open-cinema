# Pi 5 soak and unavailable-capability characterization — 2026-08-27

Status: **PCM soak characterized; encoded and DSP soaks fail the candidate
zero-error rule; physical/operator-driven cases remain unavailable; the
fixture is not performance-accepted**.

## Run identity and scope

- Executable soak run: `20260827T215740.175036Z-14838bf45bc7`
- Unavailable-capability run: `20260827T214520.181329Z-87339a44cf2b`
- Mode: `characterization`
- Soak runner:
  `72c5e4b84a409698181ae819f5ddc049771b0e773675137bac3e4b375615e648`
- Intent adapter:
  `c80db3cf8b0945e19f0e50d3cccacde4468f286a5482ff18daf46aa62c4cd1d1`
- Workload driver:
  `21d02aa890f60bd0441d58b1c6b0e524e52602520ee1827188e8af08a8c94f50`

Each executable workload ran for one measured ten-minute interval after its
readiness gate. Each retained 600/600 sustained samples, 3,000/3,000 transition
samples, zero missed slots, all three scheduled mutations, exact final
topology, and ready final processors.

| Workload | Result | PipeWire error increment | CPU max | Temperature max | DB growth |
| --- | --- | ---: | ---: | ---: | ---: |
| PCM with reconciliation refresh | Characterized | 0 | 51.87% | 54.00 °C | 724,992 B |
| AC-3 with PCM/encoded edges | Invalid | 160 | 53.72% | 53.45 °C | 311,296 B |
| Production FIR/IIR DSP, 128 frames | Invalid / physical not measured | 89 | 69.63% | 57.85 °C | 733,184 B |

No soak recorded throttling, SQLite busy results, dropped orchestration events,
or retried orchestration events. Transition collector maximum durations were
709.39 ms, 582.90 ms, and 432.51 ms respectively; maximum scheduling lateness
was 4.76 ms. The DSP profile transitions produced 262 expected intermediate
non-converged observations, then restored the prior managed intent and exact
topology with verified static and dynamic state digests.

The candidate zero programme-audio PipeWire error-increment criterion is not
met by the encoded and DSP transition workloads. Those increments are retained
as product/runtime defects for investigation; they are not reclassified as
acceptable transition noise. DSP is independently `not-measured` for physical
audio because no calibrated output capture exists.

## Unavailable cases

The companion run records these outcomes without executing unsafe or invented
automation:

- headset takeover, fallback, and reconnection: continuous Bluetooth source,
  headset control, and physical gap capture are not automated;
- adaptive-routing soak: the same Bluetooth/operator boundary is unavailable;
- boot persistence: the TV programme source and reboot-spanning physical capture
  driver are unavailable;
- event/storage burst: no bounded endpoint/property burst product API driver
  exists yet.

The run finalized as `characterized` with zero attempts and all six cases
explicitly `fixture-unavailable`. This records the limitation; it does not
satisfy their physical or event-throughput measurements.

## Superseded harness attempt

Run `20260827T214535.188654Z-7aec716c6cee` is retained as an invalid harness
diagnostic. Scheduled mutations were synchronous and caused 8 missed sustained
and 39 missed transition slots. The runner now executes scheduled mutations in
a bounded joined worker. The replacement PCM run proves 600/600 and 3,000/3,000
collection across the same three mutations. The diagnostic attempt is not
aggregated with characterization results.

## Characterization-wide anomaly disposition

| Evidence | Disposition |
| --- | --- |
| Supported baseline run | Accepted characterization observation; no acceptance claim |
| Executable decoder matrix | Accepted characterization observation; physical carrier/7.1 cases remain fixture-unavailable |
| CamillaDSP queue overflow during outage | Product/runtime defect |
| CamillaDSP readiness projection remaining ready through native outage | Product defect |
| ~39 s managed activation and ~45 s restoration | Performance limitation requiring optimization |
| Recovery PipeWire errors, including measured WirePlumber samples | Product/runtime defect |
| Recovery readiness projection mismatch | Product defect |
| ~34.8 s combined recovery maximum | Performance limitation requiring optimization |
| First PCM soak attempt | Invalid harness sample; superseded by corrected run |
| Encoded and DSP soak error increments | Product/runtime defect |
| Missing calibrated waveform capture | Fixture defect/blocker |
| Bluetooth, boot, and event-burst automation gaps | Fixture/harness limitations |

No listed product defect is accepted for release. This disposition completes
characterization review but blocks criteria freeze and acceptance execution.

## Evidence integrity and decision

The soak diagnostic export contains 83 files and verifies against
`SHA256SUMS`; its detached digest is
`a9fe741f7606d98c6e0cd886d34ef7c5302e5ad443dfb85539ced25830cfe0bb`.
The unavailable-capability export contains 25 files and verifies completely;
its detached digest is
`a5950dc667f16a641f52e3fddf23c6794088bf3456ce7b380a21bba351fe1f7e`.

The executable ten-minute soak matrix is complete and every unavailable soak
has an explicit outcome. The Pi has ample thermal and CPU margin for the tested
single chain, but encoded/DSP transition errors, missing physical capture, and
missing boot/Bluetooth/event drivers prevent criteria freeze and platform
acceptance.

