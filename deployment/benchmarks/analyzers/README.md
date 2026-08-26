# Waveform analysis

`analyze-waveform` compares marker-bearing signed 16-bit PCM WAV source and
capture files. It reports:

- sample-exact marker latency using normalized cross-correlation;
- calibration-corrected latency and root-sum-square uncertainty;
- audio-loss/restoration edges and unexpected-silence gap durations;
- clipping and discontinuities;
- channel mapping from the channel-identification tone windows.

Example:

```console
deployment/benchmarks/analyzers/analyze-waveform \
  deployment/benchmarks/media/generated/pcm-stereo-channel-id.wav \
  /restricted/evidence/captured-output.wav \
  --evidence-dir /restricted/evidence/waveform-analysis \
  --maximum-lag-ms 2500 \
  --analyze-channel-mapping
```

The evidence directory receives content-addressed copies of both waveforms and
`waveform-analysis.json`. Optional listener observations are accepted through
`--subjective-notes`; they remain under `subjectiveNotes` and never become an
objective duration.

The tool refuses compressed, truncated, non-16-bit, or rate-mismatched WAV
files and missing/low-correlation markers. It does not resample, because doing
so would change the timing evidence. Hardware acceptance also requires the
physical calibration fields in `../media/physical-path.yml`; the analyzer's
synthetic unit tests are not a substitute for that loopback measurement.

