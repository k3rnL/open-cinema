# Open Cinema

Audio processing control system with CamillaDSP integration.

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
  - [Installation](#installation)
  - [Using the API](#using-the-api)
- [Development](#development)
  - [Using the DevContainer](#using-the-devcontainer)
  - [Running Tests](#running-tests)
  - [API Testing](#api-testing)
- [Architecture](#architecture)
- [Plugin Development](#plugin-development)
  - [Audio Backend Plugins](#audio-backend-plugins)
  - [API Extension Plugins](#api-extension-plugins)
- [Documentation](#documentation)
- [Version](#version)
- [License](#license)
- [Contributing](#contributing)

## Features

- 🎵 **Plugin-based audio backend system** - Extensible architecture for multiple audio backends
- 🔊 **PulseAudio integration** - Automatic device discovery and management
- 🎛️ **CamillaDSP control** - Full control over CamillaDSP via websocket API
- 📊 **Pipeline management** - Create, activate, and manage audio processing pipelines
- 🔄 **Device tracking** - Real-time tracking of connected audio devices
- 🌐 **REST API** - Complete HTTP API for all functionality
- 🔌 **Plugin API extensions** - Plugins can register their own routes and models

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

## Plugin Development

Open Cinema supports two types of plugins that are automatically discovered at startup.

### Audio Backend Plugins

Create a new directory structure:

```
plugin/
└── myplugin/
    ├── __init__.py
    └── audio/
        ├── __init__.py
        └── backend.py
```

In `backend.py`:

```python
from core.audio.audio_backends import AudioBackend
from core.audio.audio_device import AudioDevice

class MyAudioBackend(AudioBackend):
    def get_name(self) -> str:
        return "mybackend"

    def discover_devices(self) -> list[AudioDevice]:
        # Implementation
        devices = []
        # ... discover devices
        return devices
```

Plugins are automatically discovered on Django startup.

### API Extension Plugins

API extension plugins allow you to add custom Django models and REST API endpoints to the application.

Create a plugin with models and API routes:

```
plugin/
└── myplugin/
    ├── __init__.py
    ├── models/
    │   ├── __init__.py
    │   └── mymodel.py
    └── api/
        ├── __init__.py
        └── plugin.py
```

**Step 1: Define Django models** in `models/mymodel.py`:

```python
from django.db import models

class MyModel(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'myplugin'
```

**Step 2: Create API plugin class** in `api/plugin.py`:

```python
from core.plugin_system.api_plugin import APIPlugin
from django.urls import path
from django.http import JsonResponse
from ..models.mymodel import MyModel

def my_view(request):
    """Standard Django view function"""
    return JsonResponse({'status': 'ok'})

def list_items(request):
    """Example: Query your model and return JSON"""
    items = MyModel.objects.all().values('id', 'name', 'created_at')
    return JsonResponse({'items': list(items)})

class MyAPIPlugin(APIPlugin):
    @property
    def plugin_name(self) -> str:
        """URL namespace: routes will be /api/plugins/myplugin/*"""
        return "myplugin"

    def get_urls(self):
        """Return list of Django URL patterns"""
        return [
            path('endpoint/', my_view, name='my-endpoint'),
            path('items/', list_items, name='list-items'),
        ]
```

**Step 3: Register as Django app** in `opencinema/settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'plugin.myplugin',  # Required for Django to find models
]
```

**Step 4: Create and apply database migrations:**

```bash
python manage.py makemigrations myplugin
python manage.py migrate
```

**How it works:**
- Plugin models are standard Django models that create database tables
- The `APIPlugin` class uses Django's URL routing system via `get_urls()`
- Views are standard Django view functions (can use `JsonResponse`, DRF, etc.)
- Routes are automatically registered under `/api/plugins/{plugin_name}/` at Django startup
- Plugin discovery happens in `api/apps.py` during the `ready()` lifecycle hook

**Example**: See `plugin/counter/` for a complete working example with models, API routes, and CRUD operations.

Your plugin routes will be available at:
- `/api/plugins/myplugin/endpoint/`
- `/api/plugins/myplugin/items/`

## Documentation

- [API Reference](api_tests.http) - HTTP test file with all endpoints
- [Changelog](CHANGELOG.md) - Version history
- [DevContainer Setup](.devcontainer/README.md) - Development environment
- [Deployment Guide](deployment/README.md) - Ansible deployment for Raspberry Pi

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
