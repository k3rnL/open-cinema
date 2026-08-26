# Provisional deployment audit — 2026-08-24

## Entry-gate status

This audit re-evaluates the current `deployment/` tree against
`deploy-raspberry-audio-appliance`; it does not import completion claims from
earlier work.

- `wireplumber-desired-graph-orchestration` is 186/188. Its remaining tasks are
  explicit end-user UI/scenario acceptance and final completion after that
  acceptance.
- `managed-audio-endpoint-adapters` is 38/39. Its remaining task is explicit
  acceptance of the adapter menu and ROC/debug-file workflows.
- Raspberry Pi validation is therefore an experimental continuation of local
  acceptance, not a supported release promotion.
- `playbooks/site.yml` requires
  `open_cinema_allow_experimental_deployment=true` while the gate is open. It
  also rejects a supported label, default live reconciliation, or rollback
  window closure during that period.

## File and behavior mapping

| File | Requirement/task ownership | Current assessment |
| --- | --- | --- |
| `README.md` | 2.1–2.6, 3.1–3.9, 4.1–4.9, 6.1–6.7, 10.6 | Useful operator overview; release commands and rollback prose exist, but promoted artifact and recovery commands are incomplete. |
| `SUPPORTED_PLATFORMS.md` | 2.1–2.3, 8.8–8.10 | Pi 4/5, Trixie/aarch64, and WirePlumber 0.5 boundary are selected. Power, cooling, storage, and measured capacity are not yet promotable. |
| `compatibility.yml` | 2.1–2.4, 2.7–2.9, 5.6–5.8 | Machine-readable version ranges and provisional processor policy exist. It is not yet a coordinated artifact manifest and duplicates inventory values. |
| `ansible.cfg` | 7.1–7.2, 7.8 | Correct role/filter paths; controller version is documented but not locked by this file. Host-key checking is disabled and must not be a production default. |
| `collections/requirements.yml` | 2.3, 7.1 | `ansible.posix` is pinned. Ansible Core itself still needs a controller lock/bootstrap. |
| `filter_plugins/open_cinema_compatibility.py` | 2.7–2.9 | Bounded semantic version helpers are dependency-free and used by preflight. |
| `inventories/example.yml` | 10.6 | Minimal public example; secrets, network boundary, hardware fixtures, stable UID/GID, and rollout stage examples are missing. |
| `inventories/single-env.yml` | 7.8, 10.6 | Environment-driven target helper only; it does not define release inputs. |
| `inventories/local.yml` | 1.7, 2.6, 9.1–9.2 | Pi-specific experimental inventory using current local backend, binding, UI, and decoder sources. API and observation are enabled; mutation flags remain off. |
| `inventories/group_vars/all.yml` | 1.7, 2.1–2.4, 3.1–3.4, 4.1–4.6, 5.1–5.7, 8.8–8.9, 9.1 | Central provisional policy. Component versions are duplicated with `compatibility.yml`; release revisions/hashes are incomplete. |
| `playbooks/preflight.yml` | 2.7–2.9, 7.7 | Read-only platform/runtime preflight. It currently stops at the first failure instead of returning one aggregate incompatibility report. |
| `playbooks/site.yml` | 1.7, 6.1, 7.1–7.2, 9.1–9.10 | Ordered role entry point with explicit experimental gate. Full rollout stages still need dedicated playbooks/tags and evidence capture. |
| `roles/preflight/defaults/main.yml` | 1.7, 2.7–2.9 | Safe production defaults and explicit experimental-platform opt-in. |
| `roles/preflight/tasks/main.yml` | 2.2, 2.7–2.9, 3.8 | Validates OS/architecture and PipeWire/WirePlumber/runtime contract. Model, memory, disk, repositories, power, manifest digest, and aggregate reporting are missing. |
| `roles/common/tasks/main.yml` | 3.1–3.3, 7.5 | Creates the service identity, linger session, project and diagnostic roots. Stable configurable UID/GID and stricter modes still need work. |
| `roles/pipewire-wireplumber/tasks/main.yml` | 3.2–3.10, 6.3, 7.4 | Installs one headless PipeWire/WirePlumber session, cleans legacy PulseAudio, installs owned fragments, and verifies the socket. Pi rerun is idempotent. Bluetooth source/headset behavior and least-privilege probes remain untested. |
| `roles/pipewire-wireplumber/handlers/main.yml` | 3.2, 3.5, 6.1–6.2 | User-session and Bluetooth restart handlers with explicit session environment. |
| `roles/pipewire-wireplumber/templates/49-open-cinema-bluez.rules.j2` | 3.6–3.7, 3.10 | Dedicated-user BlueZ authorization; action scope needs security review on hardware. |
| `roles/pipewire-wireplumber/templates/90-open-cinema-bluetooth.conf.j2` | 3.6–3.7 | Declares programme-source and headset roles; phone/headset acceptance is pending. |
| `roles/pipewire-wireplumber/templates/90-open-cinema-service.conf.j2` | 3.5, 6.1–6.2 | Upgrade-safe bounded restart policy. |
| `roles/pipewire-wireplumber/templates/91-open-cinema-policy.conf.j2` | 3.5, 4.8–4.9 | Prevents default-target policy from competing with Open Cinema. |
| `roles/open-cinema/tasks/main.yml` | 2.5–2.6, 4.1–4.9, 6.4, 7.1–7.3, 10.1–10.3 | Local sync, locked Python dependencies, destructive legacy migration, rollback bundle, and service install work on Pi. Every run currently stops services, runs commands marked changed, and creates a new rollback bundle, so full-play idempotency is not yet met. |
| `roles/open-cinema/handlers/main.yml` | 6.1–6.2, 6.9 | Coordinated service restarts; failure correlation remains limited. |
| `roles/open-cinema/templates/env.j2` | 1.7, 4.5–4.7, 9.1–9.10 | Feature flags and shared runtime addresses. Secrets are templated but vault/redaction workflow is pending. |
| `roles/open-cinema/templates/gunicorn.service.j2` | 4.5, 6.1–6.2, 7.5 | Hardened bounded API service; network binding remains intentionally broad behind nginx and needs boundary verification. |
| `roles/open-cinema/templates/celery.service.j2` | 4.3, 6.1–6.2 | Retention worker only; resource/memory limits are pending. |
| `roles/open-cinema/templates/celery-beat.service.j2` | 4.3, 6.1–6.2 | Retention scheduler; schedule-file recovery and limits are pending. |
| `roles/open-cinema/templates/orchestrator.service.j2` | 3.3, 4.6–4.7, 6.1–6.4 | Pi-validated singleton service and shared audio session. Sandbox was corrected so `/run/user/<uid>` remains reachable while `/home` and `/root` stay inaccessible. |
| `roles/open-cinema/templates/dependency.service.conf.j2` | 6.1–6.2 | Generic Redis lifecycle override. |
| `roles/open-cinema/templates/rollback-manifest.yml.j2` | 1.7, 2.10, 10.1–10.3 | Records experimental status and component labels, but lacks artifact digests and a runnable coordinated restore action. |
| `roles/nginx/tasks/main.yml` | 4.2, 4.5, 6.6, 7.6 | Installs proxy/static routes and validates nginx. Authentication/network exposure checks are pending. |
| `roles/nginx/handlers/main.yml` | 6.1–6.2 | Bounded reload/restart operations. |
| `roles/nginx/templates/dependency.service.conf.j2` | 6.1–6.2 | Vendor-safe lifecycle drop-in. |
| `roles/nginx/templates/open-cinema.conf.j2` | 4.2, 4.5, 6.6, 7.6 | Correctly separates `/admin/` and `/ui/`; security, cache policy for HTML, SSE-specific proxy behavior, and configured network boundary need follow-up. |
| `roles/react-apps/tasks/main.yml` | 2.5–2.6, 4.2, 6.6 | Supports immutable release downloads and experimental local build synchronization. Release asset checksums/manifest identity are missing. |
| `roles/react-apps/handlers/main.yml` | 6.1–6.2 | nginx reload only. |
| `roles/camilladsp/tasks/main.yml` | 5.3–5.10, 6.5 | Pi-validated 3.0.1 binary, stable buses, tmpfiles, and non-started instance template. Source build uses an unpinned rustup bootstrap and must be replaced for production. |
| `roles/camilladsp/handlers/main.yml` | 5.4, 6.1–6.2 | Reloads unit and PipeWire Pulse bus configuration. |
| `roles/camilladsp/templates/80-open-cinema-camilladsp.conf.j2` | 5.5–5.7 | Creates stable owned processor buses. Pi validation found and fixed their accidental projection as physical endpoints. |
| `roles/camilladsp/templates/camilladsp@.service.j2` | 5.4–5.5, 6.1–6.2 | Hardened orchestrator-managed template; no instance is enabled by Ansible. Live instance restart/recovery remains untested. |
| `roles/camilladsp/templates/open-cinema-camilladsp.tmpfiles.j2` | 5.4, 7.5 | Owned ephemeral runtime directory. |
| `roles/pcm-auto-decoder/tasks/main.yml` | 2.5–2.6, 5.1–5.2, 5.8, 8.3, 8.7 | Release download path and experimental local 0.1.4 build path exist. Local build was stopped after power/thermal failure; release 0.1.4 checksum is not yet accepted. |
| `roles/pcm-auto-decoder/handlers/main.yml` | 5.2, 6.1–6.2 | Unit reload only. |
| `roles/pcm-auto-decoder/templates/open-cinema-decoder.tmpfiles.j2` | 5.2, 7.5 | Owned ephemeral runtime directory. |
| `roles/pcm-auto-decoder/templates/pcm-auto-decoder@.service.j2` | 5.2, 5.5, 6.1–6.2 | Hardened managed status-socket template; binary contract and live start are blocked by the incomplete 0.1.4 build. |
| `roles/readiness/tasks/main.yml` | 1.7, 2.9–2.10, 3.8–3.9, 5.8–5.9, 6.3–6.7, 10.1–10.2 | Broad coordinated readiness and diagnostics. Experimental success retains rollback bundles. It currently fails fast and assumes every processor is installed. |
| `benchmarks/fixtures.yml` | 8.1, 8.5–8.9 | Machine-readable fixture and budget contract added by this audit. |
| `benchmarks/README.md` | 8.1–8.10 | Repeatable preparation, execution, and evidence rules. |

## Obsolete, duplicate, unowned, and missing work

Obsolete behavior found on the Pi was a custom system-level
`pulseaudio.service`, its `/run/pulse` socket, and per-user daemon configuration.
The audio role now removes those artifacts and masks the daemon while preserving
only PipeWire Pulse. The old singleton `camilladsp.service` is also removed.

Version data is duplicated between `compatibility.yml` and group variables.
Open Cinema's inventory label (`0.2.0`) also differs from the package-reported
version (`0.0.1`), and current dirty local source trees cannot be called immutable
artifacts. These identities must move into one coordinated release manifest.

The largest missing owned capabilities are aggregate preflight/readiness reports,
artifact publication and hashes, a runnable coordinated rollback, stable UID/GID,
production secrets/network policy, Bluetooth fixtures, decoder 0.1.4 artifact,
processor live recovery, full-play idempotency, clean-boot power/cooling evidence,
and the canonical user/UI/audio acceptance report.
