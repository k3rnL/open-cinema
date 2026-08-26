# Managed adaptive decoder

Open Cinema manages one `pcm-auto-decoder` process per resolved decoder resource.
The process is a media processor, not an audio-session policy owner: WirePlumber
still discovers its streams and Open Cinema still decides how those streams are
routed.

## Stable contract

The driver uses decoder protocol version 2 over an NDJSON Unix socket. Every
status carries the managed instance ID, process-local sequence, UTC timestamp,
lifecycle, detection mode, carrier descriptor, codec, actual decoded-frame
descriptor, confidence, stable native PipeWire node names, and structured
errors. On initial connection, reconnect, or an event sequence gap, the driver
sends `getStatus` and rebuilds state from the complete response.

The decoder projection deliberately keeps these values separate:

- transport: the captured carrier (`pcm`, `iec61937`, or `unknown`) and its PCM
  sample representation;
- content: plain PCM or an encoded codec such as AC-3, E-AC-3, or DTS;
- decoded output: rate, sample format, channel count, and layout observed from an
  actual FFmpeg frame.

This projection becomes the ordinary version-1 `SignalDescriptor`, so resolver
and plugin code do not consume decoder-specific log strings.

## Lifecycle and ownership

`DecoderDriver` implements the common processing hooks:

- `prepare` atomically creates `/run/open-cinema/decoder/<instance>.env` with mode
  `0600`, a fixed owner marker, the instance identity, and decoder arguments;
- `activate` starts the prepared instance idempotently;
- `observe` distinguishes inactive process, status-channel failure, protocol
  failure, degraded decoder status, and healthy status;
- `reconfigure` replaces configuration and restarts the same instance;
- `deactivate` stops the instance without deleting desired configuration;
- `cleanup` removes the environment file and socket only after validating the
  fixed Open Cinema owner marker and matching instance ID.

An existing unowned environment file is never overwritten, and cleanup refuses
an unowned path without stopping its process. Instance IDs accept a safe explicit
identifier or are deterministically derived from the graph node ID; transient
PIDs and PipeWire numeric IDs are never durable identity.

Production uses `SystemdDecoderProcessManager` with
`pcm-auto-decoder@<instance>.service`. Development uses
`SubprocessDecoderProcessManager`. Both share the same configuration, status,
health, correlation, and cleanup tests.

## Runtime configuration

The processing request accepts the following management values in
`plan.driverConfiguration`. Direct `configuration` values remain supported by the
driver contract harness, but graph policy and resolved runtime bindings should be
kept separate in normal planning:

```json
{
  "instanceId": "tv-main",
  "binaryPath": "/usr/local/bin/pcm-auto-decoder",
  "captureDescriptor": {
    "sampleFormat": "S16LE",
    "rate": 48000,
    "layout": {"channels": 2, "positions": ["FL", "FR"]}
  },
  "outputDescriptor": {
    "sampleFormat": "FLOAT32LE",
    "rate": 48000,
    "layout": {
      "channels": 8,
      "positions": ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"]
    }
  },
  "chunkFrames": 512,
  "detectionWindowMs": 250,
  "encodedConfirmations": 2,
  "startupTimeoutSeconds": 5
}
```

The driver serializes these typed values into individual command tokens. The
systemd template adds `--instance-id` and `--status-socket`; callers cannot add
competing values.

## Native PipeWire I/O

The release decoder opens one native PipeWire capture node and one stable native
PipeWire PCM output node. PCM input is copied to that output; supported encoded
carriers are decoded into the same output. Format transitions therefore change
reported content and decoded descriptors without replacing the downstream
endpoint or requiring a different desired graph.

The decoder gives its capture and output nodes stable names derived from the
managed instance ID and publishes the same identities through protocol version
2. Open Cinema correlates those names and managed properties in the runtime
inventory and never stores PipeWire numeric object IDs.

The processor never chooses physical targets or creates route links. WirePlumber
and the Open Cinema reconciliation plan connect the stable capture and output
resources, including when their numeric identifiers change after a process or
audio-session restart.
