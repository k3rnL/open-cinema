# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [Unreleased]

### Planned
- Periodic device discovery task (Celery/Django-Q)
- Filter management UI
- Pipeline templates
- Audio device statistics/monitoring
- User authentication
- Production deployment configuration
