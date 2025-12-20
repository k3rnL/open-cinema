# Open Cinema

Audio processing control system with CamillaDSP integration.

## Features

- 🎵 **Plugin-based audio backend system** - Extensible architecture for multiple audio backends
- 🔊 **PulseAudio integration** - Automatic device discovery and management
- 🎛️ **CamillaDSP control** - Full control over CamillaDSP via websocket API
- 📊 **Pipeline management** - Create, activate, and manage audio processing pipelines
- 🔄 **Device tracking** - Real-time tracking of connected audio devices
- 🌐 **REST API** - Complete HTTP API for all functionality

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/open-cinema.git
cd open-cinema

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

### Using the API

```bash
# Discover and populate audio devices
curl -X POST http://localhost:8000/api/devices/update

# List known devices
curl http://localhost:8000/api/devices

# Create a pipeline
curl -X POST http://localhost:8000/api/camilladsp/pipelines/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Pipeline",
    "input_device_id": 1,
    "output_device_id": 2
  }'

# Activate a pipeline
curl -X POST http://localhost:8000/api/camilladsp/pipelines/1/activate

# Check CamillaDSP status
curl http://localhost:8000/api/camilladsp/status
```

## Development

### Using the DevContainer

The project includes a complete development environment with PulseAudio and CamillaDSP:

```bash
# Open in DevContainer (VS Code or compatible IDE)
# Everything is pre-configured and will start automatically
```

### Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

### API Testing

Use the included `api_tests.http` file with IntelliJ IDEA/PyCharm HTTP client.

## Architecture

- **Django** - Web framework and REST API
- **CamillaDSP** - Audio processing engine
- **PulseAudio** - Audio backend (pluggable)
- **SQLite** - Database (configurable)

## Documentation

- [API Reference](api_tests.http) - HTTP test file with all endpoints
- [Changelog](CHANGELOG.md) - Version history
- [DevContainer Setup](.devcontainer/README.md) - Development environment

## Version

Current version: **0.0.1**

```bash
# Check version via API
curl http://localhost:8000/api/version
```

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
