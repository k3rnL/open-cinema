# Pi 5 live graph no-carrier characterization — 2026-08-26

Status: **invalid as a programme-audio soak; retained as no-carrier characterization**

The existing target-side sampler ran for 600 seconds against the active native
PipeWire graph. No controlled programme fixture was active, so the run cannot
establish PCM or movie-mode audio health. It is retained because it exposed the
specific starvation behavior that the benchmark harness must classify instead
of folding it into an accepted workload.

## Fixture and evidence

- Raspberry Pi 5 Model B Rev 1.1, 8 GB, Debian Trixie, aarch64;
- kernel `6.18.39+rpt-rpi-2712`;
- 27 W supply and active fan from the accepted fixture declaration;
- run ID `20260826T185024Z-live-graph`;
- raw directory `/var/lib/open-cinema/benchmark-results/runs/20260826T185024Z-live-graph` on the appliance;
- 600 one-second system samples from `2026-08-26T18:50:24Z`;
- saved graph remained converged with exactly 18 Open Cinema-owned links.

Key raw-file SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `manifest.txt` | `70900ae7fd04f416cd03a3e6244ffcd3916e1e8b16dfbbd3d7829bae856e8295` |
| `summary.txt` | `83e7549ca7c6438e8c4c496ddcdb5a81b2f3cf49f3c8497bde3aadc49b46c37c` |
| `system-samples.csv` | `18cb4ef0a15212e195381c3e1cbcac507bd375854556338a860263405fc198de` |
| `pidstat.txt` | `0c6b3c26da0d09c33856e0987ae93927338356fda71d2742ca7ff07b31dfd4ed` |
| `pw-top.txt` | `560c8b048ea5cccc39053067b23d628b1ff193662f510239a3e556ff12b1ec33` |
| `decoder-before.ndjson` and `decoder-after.ndjson` | `2c6c9dcf04884e378ffc0154b12f0f38897ae3e3157f33495884e9a59e098dbc` |
| `journal.txt` | `b921b10af7f60eefdc8f43c5ccc18a60d68410bafdfef916ce268af185382973` |

## Valid resource observations

| Metric | Result |
| --- | ---: |
| Temperature | 45.0–51.0 °C |
| Throttling | `0x0` before and after |
| Minimum available memory | 6,488,048 KiB |
| Maximum one-minute load | 0.48 |
| Orchestrator CPU, average / maximum | 1.213% / 2.000% |
| Decoder CPU, average / maximum | 2.333% / 4.000% |
| CamillaDSP CPU, average / maximum | 3.332% / 5.000% |
| Orchestrator maximum RSS | 91,696 KiB |
| Decoder maximum RSS | 35,360 KiB |
| CamillaDSP maximum RSS | 14,096 KiB |
| SQLite size change | 0 bytes; `quick_check=ok`, WAL before and after |
| Redis logical memory change | +29,696 bytes |

## Why the audio result is invalid

PipeWire error counters increased while the physical input had no controlled
programme carrier:

| Runtime object | Error-counter increment |
| --- | ---: |
| CamillaDSP capture | 139 |
| physical I2S input | 86 |
| CamillaDSP playback | 12 |
| decoder capture | 2 |
| decoder output | 2 |
| WONDOM GAB8 output | 0 |

CamillaDSP logged 66 `buffer empty, outputting silence` warnings. The decoder
status did not change sequence or add errors during the run; its before and
after status files are byte-identical. The retained status already contained
recoverable output-queue underrun history from before the measurement.

This is consistent with an inactive or unclocked physical programme input, not
with a valid steady programme workload. The sample therefore fails the existing
zero-error acceptance check and must not be used to claim decoded-audio, DSP,
latency, gap, or xrun acceptance.

## Harness follow-up

- Require and record the expected carrier/workload state before starting a
  programme-audio soak.
- Report first/last/delta per PipeWire object instead of comparing only the
  largest aggregate error counter.
- Preserve a failed run's directory and summary path in normal command output.
- Propagate the remote failure through controller-side redaction pipelines.
- Add an explicit no-carrier case whose safe-silence behavior is evaluated
  separately from active-audio zero-error criteria.
