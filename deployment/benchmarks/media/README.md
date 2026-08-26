# Deterministic audio fixtures

This directory contains only synthetic audio. No film, music, speech, or other
third-party programme material is used. `generate_fixtures.py` creates:

- marker-bearing stereo, 5.1, and 7.1 PCM channel-identification material;
- AC-3, E-AC-3, and DTS IEC-61937 streams derived from that PCM;
- an intentionally unsupported AAC IEC-61937 stream;
- controlled silence and a zero-byte no-carrier sentinel;
- 2.0, 5.1, 7.1, menu, cross-format, and adaptive disconnect/reconnect
  sequences.

`manifest.json` records the exact generator and probe versions, commands,
format metadata, file sizes, and SHA-256 digests. Regeneration is intentionally
separate from benchmark execution: an acceptance run consumes registered
bytes; it does not generate new media opportunistically.

Generate with FFmpeg/FFprobe 6.1.1, then verify without multimedia tools:

```console
python3 deployment/benchmarks/media/generate_fixtures.py
python3 deployment/benchmarks/media/generate_fixtures.py --verify
```

Different encoder versions may produce different compressed bytes. Such bytes
are a new fixture revision and must not silently replace this manifest.

The CamillaDSP configurations under `camilladsp/` are synthetic workloads, not
room correction. Their manifest records the 48 kHz/128-frame contract, channel
shape, filter workload, configuration digest, and FIR coefficient digest.

`physical-path.yml` records the selected measurement boundary and the missing
fixture facts needed for physical calibration. The software analyzer is tested
at sample precision, but physical latency stays `not-measured` until the actual
generator, capture ADC, clock relationship, loopback baseline, and uncertainty
are recorded on the appliance fixture.
