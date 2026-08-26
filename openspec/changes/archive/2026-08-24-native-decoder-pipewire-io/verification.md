# Integrated verification

Validated on the Raspberry Pi at `192.168.1.37` with the temporary native
PipeWire decoder build and the official CamillaDSP 4.1.3 aarch64 binary. The
CamillaDSP archive SHA-256 was
`ca8b6cc32bda29bd7cb38f7bcda5fcc6f5e69690b3d0efaa23b6c3c05c45696c`.

## Live identities

The live PipeWire registry exposed the following stable identities. Numeric
IDs and object serials were observed only as ephemeral diagnostic data and are
not persisted by Open Cinema.

- `open-cinema.decoder.e2e.capture`, group `open-cinema.decoder.e2e`, processor
  kind `adaptive-decoder`, instance `e2e`, port `capture`
- `open-cinema.decoder.e2e.output`, group `open-cinema.decoder.e2e`, processor
  kind `adaptive-decoder`, instance `e2e`, port `output`
- `opencinema.camilladsp.fixture.capture`, group
  `opencinema.camilladsp.fixture.group`
- `opencinema.camilladsp.fixture.playback`, group
  `opencinema.camilladsp.fixture.group`

## Transition evidence

One explicitly linked stereo S16/48 kHz IEC-61937 fixture traversed the native
decoder and the eight-channel CamillaDSP PipeWire capture/playback pair. The
status sequence was:

1. PCM, with no decoded descriptor
2. detecting AC-3
3. decoding AC-3 as F32 planar, 48 kHz, 6 channels, 5.1
4. PCM, with the decoded descriptor cleared atomically
5. detecting DTS
6. decoding DTS as F32 planar, 48 kHz, 6 channels, 5.1

Every state retained the same emitted descriptor: F32LE, 48 kHz, 8 channels,
7.1. CamillaDSP produced non-zero processed output through its eight playback
ports. The live ffmpeg DTS encoder emitted 5.1(side) from its 7.1 source, so
the live evidence does not claim a decoded 7.1 DTS frame. Deterministic Rust
tests separately cover position-preserving 7.1 input mapping, a stable output
identity, silent transition windows, and exclusion of encoded carrier bytes
from the PCM output.

The only status error was a recoverable `output_queue_underrun` accumulated
while the temporary decoder output was clocked before a fixture source was
connected. No fatal decoder, PipeWire, or CamillaDSP error occurred during the
transition sequence.

The run exposed and fixed two defects before acceptance: encoded payload
extraction now uses the configured carrier format rather than the adaptive
output format, and returning to PCM clears the previous decoded descriptor in
the same status update.
