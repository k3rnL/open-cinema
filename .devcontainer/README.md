# Isolated orchestration development environment

The development container mirrors the production ownership model without using
the host's PipeWire, D-Bus, or Redis sockets. It runs Debian Trixie with a
private runtime directory, private session bus, PipeWire, WirePlumber 0.5,
and a pinned Redis sidecar.

Three deterministic PipeWire fixtures are created inside the container: a TV
source, main speakers, and a headset. The adjacent WyrePlumber and PCM decoder
repositories are mounted at `/wyreplumber` and `/pcm-auto-decoder`, so Open
Cinema's local dependency and the decoder's versioned NDJSON fixtures are used
directly.

After opening the container:

```bash
uv sync --locked
uv run python manage.py migrate
wpctl status
uv run pytest
```

The session environment is already set:

```text
XDG_RUNTIME_DIR=/tmp/open-cinema-runtime
DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/open-cinema-runtime/bus
PIPEWIRE_REMOTE=pipewire-0
OPEN_CINEMA_DECODER_FIXTURES=/pcm-auto-decoder/tests/fixtures/codec_status.ndjson
```

The regular unit/integration suite supplies the full CamillaDSP driver fake.
For manual service-availability or decoder status-socket experiments, use the
included helpers:

```bash
/usr/local/lib/open-cinema-dev/fakes/fake_camilladsp.py --port 1234

/usr/local/lib/open-cinema-dev/fakes/replay_decoder_status.py \
  --fixture "$OPEN_CINEMA_DECODER_FIXTURES" \
  --socket /tmp/open-cinema-runtime/decoder-fixture.sock
```

`fake_camilladsp.py` is deliberately only a TCP availability fake; it does not
claim protocol fidelity. Protocol behavior remains covered by the in-process
test double. Audio service logs are written beneath
`/tmp/open-cinema-runtime` if startup fails.
