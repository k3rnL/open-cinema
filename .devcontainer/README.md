# Development Container Setup

This devcontainer provides a complete development environment with:
- PulseAudio with pipe sources/sinks
- CamillaDSP audio processor
- CamillaGUI (optional web interface)
- Django application

## Services Started on Boot

### PulseAudio
- Runs with pipe source (stereo input) at `/tmp/pa.input`
- Pipe sink (6-channel output) at `/tmp/pa.output`
- Format: 48kHz, S16LE input / FLOAT32LE output
- Unix socket for native protocol

### CamillaDSP
- Websocket enabled on port `1234`
- Listens on all interfaces (`0.0.0.0`)
- Default config: `/etc/camilladsp/default.yml`
- Upmixes stereo input to 6-channel output

### CamillaGUI (Optional)
- Web interface on port `5005`
- May not be available if systemd isn't running

## Testing the Setup

Once the container starts, you can:

1. **Check PulseAudio devices:**
   ```bash
   pactl list sources short
   pactl list sinks short
   ```

2. **Test CamillaDSP websocket:**
   ```bash
   curl http://localhost:1234
   ```

3. **Use Django API:**
   ```bash
   # Start Django server
   python manage.py runserver

   # Discover devices
   curl -X POST http://localhost:8000/api/devices/update

   # Get devices
   curl http://localhost:8000/api/devices
   ```

## CamillaDSP Configuration

The default configuration (`camilladsp/default.yml`) provides:
- Stereo (2ch) input from PulseAudio pipe
- 6-channel output to PulseAudio pipe
- Simple upmixer that maps:
  - Front L/R: Direct from input L/R
  - Center: Mix of L+R (-6dB)
  - LFE: Mix of L+R (-12dB)
  - Rear L/R: Attenuated input L/R (-3dB)

## Ports Exposed

- `1234`: CamillaDSP websocket
- `5005`: CamillaGUI web interface
- `8000`: Django application (when running)

## Modifying CamillaDSP Config

You can:
1. Edit `camilladsp/default.yml` and rebuild the container
2. Use the Django API to create and activate pipelines (runtime configuration)

The Django API approach is recommended for production use.
