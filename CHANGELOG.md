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
