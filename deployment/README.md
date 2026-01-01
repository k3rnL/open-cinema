# Open Cinema Deployment

Ansible playbooks for deploying the complete Open Cinema stack to Raspberry Pi.

## Components Deployed

- **PulseAudio** - System-wide audio server
- **CamillaDSP** - Audio processing with PulseAudio support (built from source)
- **Open Cinema API** - Django REST API with Gunicorn
- **nginx** - Web server and reverse proxy
- **Open Cinema UI** - React-based user interface (served at `/ui`)
- **Open Cinema Admin** - React-based admin interface (served at `/admin`)
- **PCM Auto Decoder** (optional) - Existing decoder service

## Prerequisites

### Control Machine (Your Computer)
- Ansible 2.10+
- SSH access to Raspberry Pi

### Target Machine (Raspberry Pi)
- Raspberry Pi 3/4/5 with ARM64 processor
- Raspberry Pi OS 64-bit (Bookworm or newer)
- SSH enabled
- Sudo access
- Internet connection

## Quick Start

### 1. Prepare Inventory

Copy the example inventory and configure for your Pi:

```bash
cd deployment
cp inventories/example.yml inventories/local.yml
```

Edit `inventories/local.yml`:

```yaml
all:
  hosts:
    cinema_pi:
      ansible_host: 192.168.1.100  # Your Pi's IP
      ansible_user: pi              # Your SSH user
```

### 2. Configure Variables

Edit `group_vars/all.yml` to customize:

- `open_cinema.repo`: Your GitHub repository for the API
- `open_cinema.version`: API version to deploy
- `open_cinema.django.secret_key`: Generate a secure key
- `open_cinema_ui.version`: UI release version (from k3rnL/open-cinema-ui)
- `camilladsp.build_from_source`: Set to `true` (required for ARM64 with PulseAudio)

### 3. Deploy

Deploy the complete stack:

```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml
```

Or deploy specific components:

```bash
# Only PulseAudio and CamillaDSP
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags audio

# Only the Python application
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags opencinema
```

## Configuration Details

### CamillaDSP Build

The deployment builds CamillaDSP from source with PulseAudio support. This takes **30-45 minutes** on Raspberry Pi 4.

**Why build from source?**
- No pre-built ARM64 binaries with PulseAudio support available
- Ensures compatibility with your specific Raspberry Pi

**Alternative:** Use the GitHub workflow (`.github/workflows/build-camilladsp-arm64.yml`) to build on CI/CD and download the binary.

### Services

After deployment, the following systemd services will be running:

```bash
# Check service status
sudo systemctl status pulseaudio
sudo systemctl status camilladsp
sudo systemctl status open-cinema

# View logs
sudo journalctl -u open-cinema -f
sudo journalctl -u camilladsp -f
```

### Network Access

After deployment, Open Cinema will be available at:
- **User Interface**: `http://<raspberry-pi-ip>/ui`
- **Admin Interface**: `http://<raspberry-pi-ip>/admin`
- **API**: `http://<raspberry-pi-ip>/api/`
- **Health Check**: `http://<raspberry-pi-ip>/health`

API endpoints (examples):
- `http://<raspberry-pi-ip>/api/version`
- `http://<raspberry-pi-ip>/api/devices`
- `http://<raspberry-pi-ip>/api/camilladsp/status`
- `http://<raspberry-pi-ip>/api/camilladsp/pipelines`
- `http://<raspberry-pi-ip>/api/camilladsp/mixers`

CamillaDSP websocket:
- `ws://<raspberry-pi-ip>:1234`

**Note**: All web traffic goes through nginx on port 80. The Django API runs on port 8000 internally but is only accessible via `/api/` path.

## Directory Structure

```
/opt/home-cinema/
├── open-cinema/           # Django API application root
│   ├── venv/             # Python virtual environment
│   ├── manage.py
│   ├── opencinema/
│   ├── api/
│   ├── core/
│   ├── plugin/
│   ├── db.sqlite3        # SQLite database
│   ├── staticfiles/      # Django static files
│   └── .env              # Environment configuration
└── pcm-auto-decoder.yaml  # Optional decoder config

/var/www/
├── open-cinema-admin/     # React admin build
│   ├── index.html
│   ├── assets/
│   └── ...
└── open-cinema-ui/        # React user UI build
    ├── index.html
    ├── assets/
    └── ...

/etc/nginx/
└── sites-available/
    └── open-cinema        # nginx site configuration

/etc/camilladsp/
└── default.yml            # CamillaDSP configuration

/usr/local/bin/
├── camilladsp
└── pcm-auto-decoder
```

## Updating

To update to a new version:

1. Update `open_cinema.version` in `group_vars/all.yml`
2. Run the playbook again:

```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags opencinema
```

The application will be redeployed and services restarted automatically.

## Troubleshooting

### CamillaDSP Build Fails

If CamillaDSP build fails due to memory constraints:

```bash
# On the Raspberry Pi, increase swap
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile  # Set CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

Then re-run the playbook.

### Audio Devices Not Detected

```bash
# On the Raspberry Pi
pactl list sources short
pactl list sinks short

# If empty, check PulseAudio
sudo systemctl status pulseaudio
sudo journalctl -u pulseaudio
```

### Django Application Won't Start

```bash
# Check logs
sudo journalctl -u open-cinema -n 100

# Check database permissions
sudo chown -R opencinema:opencinema /opt/home-cinema/open-cinema

# Retry migrations manually
sudo -u opencinema /opt/home-cinema/open-cinema/venv/bin/python \
  /opt/home-cinema/open-cinema/manage.py migrate
```

## Development vs Production

The current configuration is suitable for development/testing. For production:

1. **Generate a secure SECRET_KEY**:
   ```python
   python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   ```

2. **Set DEBUG=false** in `group_vars/all.yml`

3. **Configure ALLOWED_HOSTS** properly

4. **Use PostgreSQL** instead of SQLite (add postgres role)

5. **Enable HTTPS** with Let's Encrypt (configure nginx with SSL)

## Roles

### common
- Updates system packages
- Creates project directories
- Installs base dependencies

### pulseaudio
- Installs PulseAudio server
- Configures system-wide daemon
- Sets up systemd service

### camilladsp
- Installs Rust compiler
- Builds CamillaDSP from source with PulseAudio support
- Installs binary and configuration
- Sets up systemd service with websocket

### python-app
- Creates application user
- Clones application from GitHub
- Creates Python virtual environment
- Installs dependencies
- Runs migrations
- Collects static files
- Sets up Gunicorn systemd service

### nginx
- Installs and configures nginx web server
- Sets up reverse proxy for Django API
- Serves React static files
- Configures path-based routing (`/ui`, `/admin`, `/api`)
- Enables gzip compression and security headers

### react-apps
- Downloads React builds from GitHub releases
- Extracts admin and UI builds to web root
- Configures proper permissions
- Verifies deployment (checks index.html)

### pcm-auto-decoder (optional)
- Downloads and installs decoder from GitHub releases
- Configures and starts service

## Tags

Use tags to run specific parts:

- `common` - Base system setup
- `pulseaudio` - Audio server
- `audio` - Both PulseAudio and CamillaDSP
- `camilladsp` - Audio processor
- `opencinema` - Django API application
- `python` - Python app (alias for opencinema)
- `app` - Application layer (alias for opencinema)
- `nginx` - Web server and reverse proxy
- `react` - React frontend applications
- `frontend` - Both nginx and react-apps
- `web` - Web layer (nginx + react-apps)
- `ui` - React applications (alias for react)
- `decoder` - PCM decoder

### Examples

Deploy only the frontend:
```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags frontend
```

Update only React apps:
```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags react
```

Deploy API and frontend without audio components:
```bash
ansible-playbook -i inventories/local.yml playbooks/site.yml --tags opencinema,frontend
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/yourusername/open-cinema/issues
- Documentation: Project README.md
