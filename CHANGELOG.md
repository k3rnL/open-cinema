# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Periodic device discovery task (Celery/Django-Q)
- Filter management UI
- Pipeline templates
- Audio device statistics/monitoring
- User authentication
- Production deployment configuration

## [0.3.14] - 2026-08-31

### Fixed
- Observe and mutate effective endpoint volume and mute state through
  WirePlumber's mixer API, including device-route controls whose raw node Props
  do not represent the actual hardware level.
- Preserve desired endpoint levels during appliance restart reconciliation
  instead of timing out and rolling back an otherwise valid audio graph.

## [0.3.13] - 2026-08-31

### Fixed
- Select the librespot plugin release that keeps activity-based audio routes
  active while the next Spotify track is preloading.

## [0.3.12] - 2026-08-30

### Fixed
- Select the librespot plugin release that preserves its immutable overlay
  import path for playback events.
- Ship the administration UI that presents plugin-managed audio sources and
  suppresses obsolete plugin-operation failures after a successful update.

## [0.3.10] - 2026-08-30

### Fixed
- Permit the orchestrator's managed Librespot child to enumerate multicast
  interfaces through netlink while retaining the systemd address-family sandbox.
- Finalize a stale reconnecting system-control operation before deciding whether
  a new restart request is a duplicate.

## [0.3.9] - 2026-08-30

### Fixed
- Validate an update candidate in a clean plugin-discovery context so a module
  from the active generation cannot shadow the new overlay.

## [0.3.8] - 2026-08-30

### Changed
- Select the immutable Librespot plugin 0.1.9 release whose event relay works
  from isolated plugin overlay generations.

## [0.3.7] - 2026-08-30

### Fixed
- Reconcile persisted hot plugin enable/disable state independently in web,
  worker, and orchestrator processes before using plugin capabilities.

## [0.3.6] - 2026-08-30

### Fixed
- Activate the installed plugin overlay before Django starts in both the Celery
  worker and dedicated audio-orchestrator entry points.

## [0.3.5] - 2026-08-30

### Fixed
- Install plugin overlay dependencies without a user-home package cache so
  lifecycle operations work inside the hardened systemd service sandbox.
- Include bounded installer output in failed plugin-operation diagnostics.

## [0.3.4] - 2026-08-30

### Fixed
- Keep the standalone plugin generation-control helper independent from Django
  application initialization during appliance deployment and rollback checks.

## [0.3.3] - 2026-08-30

### Added
- Versioned installable-plugin contract, SDK, catalogue, lifecycle operations, and declarative administration UI support.
- Managed multi-instance audio-source integration for external plugins, including durable endpoint and desired-graph contributions.
- Appliance observability, system controls, managed-resource actions, and endpoint volume/mute controls.

### Changed
- Runtime explanations and administration workflows now expose user-facing route, health, and recovery information.
- Audio-level reconciliation can clear controls on configured fallback sources even while another source is selected.

## [0.0.1] - 2025-12-20

### Added
- Initial release
- Plugin-based audio backend discovery system
- PulseAudio backend implementation
- CamillaDSP integration with websocket control
- Django REST API for audio device management
- Pipeline CRUD operations (create, read, update, delete, activate)
- Known audio device tracking with active/inactive status
- Device discovery task for database population
- CamillaDSP configuration builder (YAML generation)
- CamillaDSP client with websocket support and SIGHUP fallback
- Devcontainer setup with PulseAudio and CamillaDSP
- Database models: KnownAudioDevice, Pipeline, Filter
- API endpoints for:
  - Device discovery and listing
  - Pipeline management
  - CamillaDSP status and configuration
- HTTP test file for API testing
- Version endpoint

### Infrastructure
- Docker devcontainer with Ubuntu
- PulseAudio with pipe source/sink support
- CamillaDSP built from source with PulseAudio support
- Django 6.0 application framework
- SQLite database
