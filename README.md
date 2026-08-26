# Open Cinema

Open Cinema is the control plane for a configurable home-cinema and audio
appliance. It stores versioned desired audio graphs, resolves them against the
devices and signal formats that are present, and continuously reconciles the
result with a native PipeWire session through WirePlumber.

The project is intended to make common policies simple—TV audio on the main
speakers, Bluetooth sources taking over those speakers, and a connected
headset taking priority—without preventing advanced users from composing
reusable graphs, conditional routes, and processing stages.

## System boundaries

Open Cinema owns desired state, policy, validation, reconciliation, and the
management API. It does not replace PipeWire's media graph or WirePlumber's
session model.

- **PipeWire and WirePlumber 0.5** expose devices, ports, routes, profiles, and
  links. The native
  [WyrePlumber](https://github.com/k3rnL/wyreplumber) binding is Open Cinema's
  single audio-runtime integration.
- **PCM Auto Decoder** observes an encoded/PCM input and exposes one stable,
  adaptive native PipeWire PCM output. Format changes are reported to Open
  Cinema without replacing the logical processor node.
- **CamillaDSP 4** is an independently versioned native PipeWire process. Open
  Cinema manages typed profiles and instance lifecycle while CamillaDSP owns
  the real-time DSP engine.
- **Open Cinema UI** is maintained in the separate
  [open-cinema-ui](https://github.com/k3rnL/open-cinema-ui) repository. Its
  `apps/admin` application is the end-user administration console; `apps/ui`
  is the on-box display application and is currently a placeholder.

CamillaDSP and the decoder are processors, not endpoints. They can be inserted
between logical inputs and outputs in a desired graph. Application and
processing plugins may extend Open Cinema, but plugins cannot introduce a
second audio backend or take ownership of the PipeWire session.

## Audio model

The orchestration API keeps four states deliberately separate:

1. A **draft graph** is editable and may refer to devices that are currently
   absent.
2. A **published revision** is immutable desired state that can be activated or
   disabled.
3. A **resolved plan** explains which endpoints, routes, processors, and
   fallbacks match the current runtime facts.
4. The **applied/runtime state** records the actions and live PipeWire objects
   produced by reconciliation.

Saving a draft never changes active audio. Applying performs save, validation,
publication, activation, and reconciliation as one observable operation; a
failure preserves the previous active graph. Reusable parameterized subgraphs
allow a complex installation to expose a smaller end-user graph.

The versioned API starts at `/api/audio/v1`. Useful discovery endpoints include:

```bash
curl -u admin:admin http://localhost:8000/api/audio/v1/schema
curl -u admin:admin http://localhost:8000/api/audio/v1/endpoints
curl -u admin:admin http://localhost:8000/api/audio/v1/runtime/readiness
curl -u admin:admin http://localhost:8000/api/audio/v1/graphs
curl -u admin:admin http://localhost:8000/api/audio/v1/plans/current
```

Browser clients should use the session/CSRF authentication flow implemented by
the administration UI rather than HTTP basic authentication.

## Supported appliance

The currently exercised fixture is a Raspberry Pi 5 with 8 GB RAM running
Debian 13 (Trixie), using a dedicated headless PipeWire/WirePlumber service
identity. Hardware acceptance has covered the GAB8 output, an SPDIF-to-I2S TV
input, Bluetooth programme sources and headsets, one adaptive decoder, and one
CamillaDSP instance. See [deployment/README.md](deployment/README.md) and
[deployment/SUPPORTED_PLATFORMS.md](deployment/SUPPORTED_PLATFORMS.md) for the
precise boundary and deferred campaigns.

Other Raspberry Pi memory tiers and clean-image/upgrade qualification are not
currently claimed. Performance characterization is tracked separately from
functional deployment acceptance.

## Development

Python 3.12 or 3.13 and `uv` are supported. Native runtime development also
requires WirePlumber 0.5. The repository's development source override expects
the related projects beside it:

```text
PyCharmProjects/
├── open-cinema/
└── wyreplumber/
RustroverProjects/
└── pcm-auto-decoder/
```

Clone those repositories, then create the environment from the lock file:

```bash
uv sync --frozen --extra dev
uv run python manage.py migrate
uv run python manage.py ensure_default_admin
```

The temporary development administrator is `admin` / `admin`. Override it with
`--username`, `--password`, or `OPEN_CINEMA_DEFAULT_ADMIN_PASSWORD`; do not use
the default credential on an exposed system.

### Isolated native-audio container

The recommended integration environment is the devcontainer. It runs Debian
Trixie with private D-Bus, PipeWire, WirePlumber 0.5, Redis, and deterministic
TV/main-speaker/headset fixtures. It does not attach to the host audio session.

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash

uv sync --frozen --extra dev
uv run python manage.py migrate
uv run python manage.py ensure_default_admin
uv run pytest
wpctl status
```

See [.devcontainer/README.md](.devcontainer/README.md) for the private runtime
paths and decoder/CamillaDSP test helpers.

### Running the control plane

Redis must be reachable through `OPEN_CINEMA_RUNTIME_REDIS_URL`,
`CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND`. In separate shells run:

```bash
uv run python manage.py runserver 0.0.0.0:8000
uv run celery -A opencinema worker --loglevel=info
uv run celery -A opencinema beat --loglevel=info
uv run open-cinema-orchestrator
```

Use `uv run open-cinema-orchestrator --check` for a bounded startup/contract
probe. Live reconciliation should only be enabled inside an audio session the
developer intends Open Cinema to control.

## Validation and distributions

The complete local backend gate is:

```bash
uv sync --frozen --extra dev
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
uv build
uv run python scripts/verify_release_dist.py \
  --dist-dir dist \
  --expected-version "$(uv run python -c 'from opencinema.version import __version__; print(__version__)')"
```

Deployment syntax checks are run from `deployment/`:

```bash
ansible-playbook -i inventories/example.yml playbooks/preflight.yml --syntax-check
ansible-playbook -i inventories/example.yml playbooks/site.yml --syntax-check
ansible-playbook -i inventories/example.yml playbooks/rollback.yml --syntax-check
ansible-playbook -i inventories/example.yml playbooks/benchmark.yml --syntax-check
```

CI repeats the backend, archive, isolated-install, and deployment syntax gates
on branches and pull requests. A wheel is not accepted merely because it
builds: the distribution verifier requires the license, runtime version module,
and versioned orchestration contracts in both wheel and source archive.

## Deployment modes

Ansible supports two intentionally distinct inputs:

- **Development mode** synchronizes explicitly configured local source
  directories. Diagnostics identify this input as mutable and non-release.
- **Appliance/release mode** consumes a coordinated manifest whose components
  are pinned by version, commit, platform/ABI selector, artifact URL, SHA-256,
  and provenance. Mutable branches, editable installs, and adjacent worktrees
  are not valid release inputs.

The repository manifest currently records the experimental development
fixture; it must not be presented as an immutable product release. Follow the
[deployment guide](deployment/README.md) for inventory, authentication,
preflight, readiness, diagnostics, backup, and coordinated rollback.

## Versioning and releases

`opencinema.version.__version__` is the authoritative backend version. Python
package metadata and `/api/version` read that same value. Release tags use
`v<major>.<minor>.<patch>` and must exactly match it.

The tag workflow first runs the same required CI gates, then publishes a wheel,
source archive, SHA-256 records, and portable provenance. A project tag alone
does not make an appliance release: WyrePlumber, the decoder, both UI builds,
and Open Cinema are published in dependency order and admitted only after their
downloaded artifacts pass verification and are recorded in one immutable
coordinated manifest.

## Repository guide

- [Audio API v1](docs/audio-orchestration/API_V1.md)
- [Application and processing plugins](docs/audio-orchestration/PLUGINS.md)
- [Deployment and operations](deployment/README.md)
- [Version history](CHANGELOG.md)
- [`contracts/`](contracts/) — packaged cross-project schemas and protocol data
- [`core/orchestration/`](core/orchestration/) — desired-state resolver and
  reconciler
- [`api/audio_v1/`](api/audio_v1/) — public orchestration API
- [`plugin/`](plugin/) — plugin contracts and bundled example

## License

Open Cinema is distributed under the [MIT License](LICENSE).
