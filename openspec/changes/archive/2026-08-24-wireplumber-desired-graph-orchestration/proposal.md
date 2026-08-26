## Why

Open Cinema currently duplicates part of WirePlumber's session-policy responsibility through a static `AudioPipelineGraph` and pluggable audio backends, which creates competing sources of truth for discovery, routing, defaults, and runtime graph state. The project needs a single declarative orchestration model that preserves reusable desired graphs while making WirePlumber the authoritative runtime session manager and allowing CamillaDSP, adaptive decoding, and future processors to remain extensible.

## What Changes

- Reinterpret saved audio pipelines as parameterized desired graphs that may reference unavailable logical endpoints and reusable, versioned subgraphs.
- Add a deterministic resolver that combines a desired graph, endpoint availability, signal formats, rules, priorities, and manual overrides into an explainable resolved plan.
- Add continuous reconciliation so device, format, processing, and user changes update the live system without modifying the saved desired graph.
- Make WirePlumber, accessed through WyrePlumber, the required runtime authority for PipeWire discovery, nodes, ports, defaults, metadata, volume, mute, and link/session state.
- **BREAKING**: Remove the audio-backend plugin abstraction, backend preferences, and PulseAudio/ALSA backend implementations from Open Cinema.
- Preserve and formalize extensibility through audio-processing plugins and other application plugins; processing plugins contribute graph node types, schemas, validation, planning, and lifecycle integration rather than alternative device backends.
- Model processors as first-class insertable graph stages, distinct from input/output endpoint references even when their managed processes expose PipeWire nodes and ports.
- Integrate CamillaDSP as a built-in processor whose profile, configuration, lifecycle, health, and PipeWire-facing ports are selected from the resolved route and signal requirements.
- Integrate `pcm-auto-decoder` as a built-in signal-aware processor that reports transport, codec, decoded format, rate, channels, and layout to Open Cinema.
- Add runtime and planning APIs that clearly separate desired graphs, resolved plans, and the observed PipeWire graph.
- Preserve and evolve the existing end-user management console in `apps/admin`, including its dashboard, device discovery, React Flow graph editor, processor editing, validation/error feedback, explicit Save and Apply workflow, and established look and feel without introducing custom CSS.
- Keep `apps/ui` as the placeholder for the future on-box external-display experience; it does not replace the management console in this change.
- Add reusable subgraphs, parameters, conditions, fallbacks, processor nodes, resolved-state explanations, and an optional rule-oriented view to the existing management experience.

## Capabilities

### New Capabilities

- `desired-audio-graphs`: Persistent parameterized desired graphs, logical ports, reusable subgraphs, endpoint references, and graph validation.
- `audio-endpoint-inventory`: Logical endpoint identity and matching against transient PipeWire/WirePlumber nodes, routes, capabilities, and availability.
- `audio-route-resolution`: Deterministic condition, priority, fallback, format, and manual-override resolution into an explainable active plan.
- `audio-reconciliation`: Continuous observation, diffing, safe transition execution, failure recovery, and resolved/degraded/waiting status management.
- `wireplumber-runtime-control`: Required WyrePlumber integration for live PipeWire observation and runtime control, replacing audio backend plugins.
- `audio-processing-plugins`: Extensible processing-node contracts for schemas, validation, plan contribution, runtime lifecycle, and status.
- `adaptive-signal-processing`: Signal descriptors and decoder events that allow processing and routing decisions to react to PCM and encoded formats.
- `camilladsp-graph-processing`: CamillaDSP profiles and configurations selected and applied as part of resolved processing chains.
- `audio-orchestration-api-ui`: APIs and web experiences for desired graphs, subgraphs, rules, live state, resolved explanations, and manual control.

### Modified Capabilities

None. This repository does not yet contain main OpenSpec capability specifications.

## Impact

- Backend models, migrations, REST APIs, Celery jobs, plugin discovery, pipeline validation, and process management will change substantially.
- `core.audio.audio_backend`, `AudioBackends`, `PreferencesAudioBackend`, and PulseAudio/ALSA backend plugins and APIs will be removed directly; the alpha data has no users and requires no compatibility migration.
- WyrePlumber becomes a required dependency and will need event subscriptions plus additional runtime graph/control coverage.
- `pcm-auto-decoder` will need a structured local status/control protocol and richer decoded-signal reporting.
- CamillaDSP management will move from a parallel pipeline concept into processing profiles consumed by desired graphs.
- `open-cinema-ui/apps/admin` will retain its end-user management role and existing interaction design while receiving repaired API contracts, first-class processor nodes, endpoint inventory, reusable subgraph editing, rule controls, and runtime visualization.
- `open-cinema-ui/apps/ui` remains a placeholder for the future external-display interface during this change.
- Existing pipeline data is considered alpha and will be removed or reset directly; no compatibility migration or preservation path is required.
- Raspberry Pi, Ansible, coordinated release, hardware profiling, and appliance rollout work is intentionally tracked by the separate `deploy-raspberry-audio-appliance` change after local product acceptance.
