import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
DEPLOYMENT = ROOT / "deployment"
PIPEWIRE_ROLE = DEPLOYMENT / "roles/pipewire-wireplumber"
APP_ROLE = DEPLOYMENT / "roles/open-cinema"
READINESS_ROLE = DEPLOYMENT / "roles/readiness"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deployment_uses_one_headless_native_pipewire_session() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    common = read(DEPLOYMENT / "roles/common/tasks/main.yml")
    audio_tasks = read(PIPEWIRE_ROLE / "tasks/main.yml")

    assert "role: pipewire-wireplumber" in site
    assert "enable-linger" in common
    assert "user@{{ open_cinema_uid }}.service" in common
    assert "scope: user" in audio_tasks
    assert "Disable competing per-user audio sessions" in audio_tasks
    assert "Require competing login sessions to have no audio runtime" in read(
        READINESS_ROLE / "tasks/main.yml"
    )
    assert "Install the selected PipeWire and WirePlumber stack" in audio_tasks


def test_active_runtime_surface_is_native_pipewire_only() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    manifest = yaml.safe_load(read(DEPLOYMENT / "release-manifest.yml"))

    assert set(inventory["audio_service"]) == {
        "user",
        "group",
        "exclusive",
        "competing_session_users",
        "supplementary_groups",
        "runtime_dir",
        "pipewire_socket",
        "dbus_address",
    }
    assert manifest["processor_requirements"] == {
        "camilladsp_instances": 1,
        "decoder_instances": 1,
    }
    assert manifest["components"]["camilladsp"]["backend"] == "pipewire"
    assert manifest["components"]["pcm_auto_decoder"]["backend"] == "pipewire"

    active_paths = [
        *DEPLOYMENT.rglob("*"),
        *(ROOT / ".devcontainer").rglob("*"),
        *(ROOT / ".github/workflows").rglob("*"),
        ROOT / "pyproject.toml",
        ROOT / "README.md",
        ROOT / "docs/audio-orchestration/CAMILLADSP_DRIVER.md",
        ROOT / "docs/audio-orchestration/DECODER_DRIVER.md",
    ]
    excluded_parts = {"acceptance", "audits", "results"}
    text_suffixes = {".j2", ".md", ".py", ".sh", ".txt", ".yaml", ".yml"}
    active_text = "\n".join(
        read(path).lower()
        for path in active_paths
        if path.is_file()
        and not excluded_parts.intersection(path.parts)
        and (path.suffix in text_suffixes or path.name == "Dockerfile")
    )
    retired_terms = (
        "pulse" + "audio",
        "pipewire" + "-pulse",
        "lib" + "pulse",
        "pact" + "l",
        "pulse" + "_server",
        "pulse" + "_runtime_path",
    )
    assert all(term not in active_text for term in retired_terms)
    assert not (ROOT / ".github/workflows/build-" "camilladsp-arm64.yml").exists()


def test_release_manifest_is_installed_and_correlated_with_recovery_records() -> None:
    common = read(DEPLOYMENT / "roles/common/tasks/main.yml")
    readiness = read(DEPLOYMENT / "roles/readiness/tasks/main.yml")
    rollback = read(DEPLOYMENT / "roles/open-cinema/templates/rollback-manifest.yml.j2")

    assert "Install the coordinated release manifest" in common
    assert "checksum_algorithm: sha256" in common
    assert "release_manifest_sha256" in readiness
    assert "installed_identity_path" in readiness
    assert "release_manifest_sha256" in rollback


def test_manifest_input_validation_precedes_every_appliance_role() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    validator = read(DEPLOYMENT / "scripts/validate_release_manifest.py")
    rollback_preflight = read(DEPLOYMENT / "tasks/private-rollback-preflight.yml")

    validation_at = site.index(
        "Validate and resolve every deployment input before appliance mutation"
    )
    assert validation_at < site.index("role: common")
    assert validation_at < site.index("role: pipewire-wireplumber")
    rollback_at = site.index("Verify retained rollback input before any appliance mutation")
    assert validation_at < rollback_at < site.index("role: common")
    assert "--mode" in site
    assert "install_from_local" in site
    assert "verify_private_rollback_capsule.py" in rollback_preflight
    assert "--receipt-sha256" in rollback_preflight
    assert "no_log: true" in rollback_preflight
    assert "Publish the protected appliance baseline path" in rollback_preflight
    assert "Verify recursive immutable protection" in rollback_preflight
    assert "target-verified" in rollback_preflight
    assert "when: not install_from_local" in rollback_preflight
    assert (
        "- name: Verify and protect the private first-release replacement baseline\n"
        "  become: true"
    ) in rollback_preflight
    assert "MUTABLE_SOURCE_MARKERS" not in validator
    for rejected_input in (
        "editable",
        "floating",
        "latest",
        "local-directory",
        "local-source",
    ):
        assert rejected_input in validator


def test_release_installers_consume_only_selected_manifest_artifacts() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    app = read(APP_ROLE / "tasks/main.yml")
    ui = read(DEPLOYMENT / "roles/react-apps/tasks/main.yml")
    decoder = read(DEPLOYMENT / "roles/pcm-auto-decoder/tasks/main.yml")
    camilladsp = read(DEPLOYMENT / "roles/camilladsp/tasks/main.yml")

    assert set(inventory["wyreplumber"]) == {
        "app_path",
        "local_source_path",
        "required_contract",
    }
    assert "ansible.builtin.git:" not in app
    for selected in (
        "open_cinema_source",
        "open_cinema_wheel",
        "wyreplumber_wheel",
        "pycamilladsp_wheel",
    ):
        assert f"open_cinema_release_artifacts.{selected}" in app
    for source in (app, ui, decoder, camilladsp):
        assert "open_cinema_release_artifacts" in source
        assert 'checksum: "sha256:' in source
    assert "--no-deps" in app
    assert "--force-reinstall" in app
    assert "Install only manifest-selected Python wheels in appliance mode" in app


def test_mutable_development_identity_and_exact_runtime_probes_are_diagnostic() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    preflight = read(DEPLOYMENT / "roles/preflight/tasks/main.yml")
    readiness = read(READINESS_ROLE / "tasks/main.yml")
    rollback = read(APP_ROLE / "templates/rollback-manifest.yml.j2")

    assert "Record mutable development source identities explicitly" in site
    assert "sourceType': 'local-directory'" in site
    assert "open_cinema_development_source_identities" in site
    assert "open_cinema_deployment_input_identity" in site
    assert "metadata.version('open-cinema')" in preflight
    assert "WIREPLUMBER_BUILD_API_FAMILY" in preflight
    assert "decoder_output" in readiness
    assert "inputIdentity" in readiness
    assert "installed_probes" in readiness
    assert "input_identity" in rollback


def test_candidate_contracts_are_probed_before_live_activation() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    gate = read(DEPLOYMENT / "roles/contract-gate/tasks/main.yml")
    safety = read(DEPLOYMENT / "roles/deployment-safety/tasks/main.yml")
    preflight = read(DEPLOYMENT / "roles/preflight/tasks/main.yml")
    environment = read(APP_ROLE / "templates/env.j2")
    ui_tasks = read(DEPLOYMENT / "roles/react-apps/tasks/main.yml")

    assert site.index("name: deployment-safety") < site.index("name: open-cinema")
    assert site.index("name: pcm-auto-decoder") < site.index("name: contract-gate")
    assert site.index("name: contract-gate") < site.index("name: readiness")
    assert "Stop the previous live controller" in safety
    assert "open_cinema_contract_gate_complete" in site
    assert "open_cinema_contract_gate_previously_passed" in site
    assert "open_cinema_contract_gate_complete | default(false)" in environment
    assert "Enter a diagnosable non-live runtime" in gate
    assert "open_cinema_preflight_require_full_runtime: true" in gate
    assert "Activate the accepted full runtime only after every contract probe passes" in gate
    for contract in (
        "ORCHESTRATION_CONTRACT_VERSION",
        "RUNTIME_VALUE_SCHEMA_VERSION",
        "DECODER_PROTOCOL_VERSION",
        "PLUGIN_CONTRACT_VERSION",
        "driver_contract_version",
        "management UI DTO contract",
    ):
        assert contract in preflight
    assert "Reject a local management UI with incompatible DTO contracts" in ui_tasks
    assert "open-cinema.audio-client-contract/v1" in preflight
    assert "desiredGraphSchemaVersion" in preflight
    assert not (DEPLOYMENT / "roles/react-apps/templates/open-cinema-contract.json.j2").exists()


def test_unchanged_candidate_reuses_the_passed_contract_gate() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    safety = read(DEPLOYMENT / "roles/deployment-safety/tasks/main.yml")
    gate = read(DEPLOYMENT / "roles/contract-gate/tasks/main.yml")
    preflight = read(DEPLOYMENT / "roles/preflight/tasks/main.yml")
    digest_script = read(DEPLOYMENT / "scripts/source-tree-digest.py")

    assert "Fingerprint locally synchronized candidate source trees" in site
    assert "open_cinema_deployment_candidate_digest" in site
    assert "Check whether this exact candidate already passed the contract gate" in site
    assert "open_cinema_contract_gate_previously_passed" in safety
    assert "open_cinema_contract_gate_previously_passed" in gate
    assert "candidateDigest" in preflight
    assert "IGNORED_DIRECTORY_PATTERNS" in digest_script
    assert "hashlib.sha256" in digest_script
    app_tasks = read(APP_ROLE / "tasks/main.yml")
    for excluded in ("deployment", "docs", "openspec", "tests", "README.md"):
        assert f"--exclude={excluded}" in app_tasks
    assert "Remove previously synchronized controller-only source trees" in app_tasks


def test_changed_candidate_creates_a_full_coordinated_transition_bundle() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    tasks = read(DEPLOYMENT / "roles/transition-backup/tasks/main.yml")
    manifest = read(DEPLOYMENT / "roles/transition-backup/templates/manifest.yml.j2")
    state_probe = read(DEPLOYMENT / "scripts/dynamic-state-digest.py")

    assert site.index("role: preflight") < site.index("role: transition-backup")
    assert site.index("role: transition-backup") < site.index("name: deployment-safety")
    assert "Stop every previous application database writer" in tasks
    assert ".backup" in tasks
    for artifact in (
        "application.tar.gz",
        "wyreplumber.tar.gz",
        "web.tar.gz",
        "managed-static.tar.gz",
        "processor-binaries.tar.gz",
        "processor-runtime.tar.gz",
        "release-manifest.yml",
        "dynamic-state.json",
    ):
        assert artifact in tasks
    assert "Retain the controller inventory inputs" in tasks
    assert "Mark the coordinated transition bundle restorable" in tasks
    assert "open_cinema_transition_mutable_bundle_paths" in tasks
    assert "open_cinema_protected_rollback_bundle_ids" in tasks
    assert "Require protected transition bundles to remain outside the mutable set" in tasks
    assert "previous_candidate_digest" in manifest
    assert "artifacts:" in manifest
    for model in (
        "GraphDefinition",
        "GraphRevision",
        "GraphActivation",
        "LogicalEndpoint",
        "CamillaDSPProfile",
        "ManagedAudioAdapter",
        "ManualOverride",
    ):
        assert model in state_probe


def test_rollback_restores_one_explicit_verified_generation() -> None:
    playbook = read(DEPLOYMENT / "playbooks/rollback.yml")
    tasks = read(DEPLOYMENT / "roles/rollback/tasks/main.yml")

    assert "open_cinema_rollback_bundle_id" in tasks
    assert "Rollback never selects or deletes a bundle implicitly" in tasks
    assert "Verify every coordinated rollback artifact checksum" in tasks
    assert "Back up the candidate database before rollback" in tasks
    assert "Keep the pre-rollback candidate checkpoint private" in tasks
    assert 'mode: "0600"' in tasks
    assert "Remove only coordinated application generation directories" in tasks
    assert "Extract coordinated application binding and web archives" in tasks
    assert "Restore the coordinated pre-transition database" in tasks
    assert "Restore the previous installed release identity" in tasks
    assert "Invalidate candidate gate and readiness evidence before replacement" in tasks
    assert "Reconstruct the passed contract gate from the verified rollback manifest" in tasks
    restored_identity_at = tasks.index("Restore the previous installed release identity")
    restored_identity_end = tasks.index("Load the restored installed release manifest")
    restored_identity = tasks[restored_identity_at:restored_identity_end]
    assert "src: contract-gate-result.json" not in restored_identity
    assert "src: readiness-result.json" not in restored_identity
    restored_manifest_at = tasks.index("Load the restored installed release manifest")
    publish_manifest_at = tasks.index("Publish the restored manifest for post-rollback readiness")
    assert restored_manifest_at < publish_manifest_at
    assert "open_cinema_release_manifest:" in tasks[publish_manifest_at:]
    assert "Verify retained rollback input before rollback mutation" in playbook
    assert "Require rollback to restore exact user-owned audio intent" in tasks
    assert "Record the successful coordinated rollback result" in tasks
    assert "role: rollback" in playbook
    assert "role: readiness" in playbook


def test_every_candidate_stage_failure_is_correlated_with_rollback() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    tasks = read(DEPLOYMENT / "roles/deployment-failure/tasks/main.yml")

    assert "Install, gate, and verify one coordinated candidate generation" in site
    assert "rescue:" in site
    assert "Preserve the original candidate-stage failure identity" in site
    assert "name: deployment-failure" in site
    assert "Find retained coordinated transition bundles after failure" in tasks
    assert "Probe every coordinated service after candidate-stage failure" in tasks
    assert "Retain the private correlated candidate-stage failure result" in tasks
    assert "Stop without deleting the coordinated rollback boundary" in tasks
    assert 'mode: "0600"' in tasks


def test_readiness_loads_release_identity_for_independently_tagged_runs() -> None:
    readiness = read(DEPLOYMENT / "roles/readiness/tasks/main.yml")

    assert "Load the coordinated release manifest for independently tagged runs" in readiness
    assert "open_cinema_readiness_release_manifest_stat.stat.checksum" in readiness
    assert "open_cinema_release_manifest_digest" in readiness
    assert "Find the retained rollback identity for independently tagged runs" in readiness
    assert "open_cinema_rollback_id is not defined" in readiness


def test_deployment_uses_one_contract_gated_full_runtime() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    rollback_playbook = read(DEPLOYMENT / "playbooks/rollback.yml")
    group_inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    example_inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/example.yml"))
    environment = read(DEPLOYMENT / "roles/open-cinema/templates/env.j2")
    readiness = read(READINESS_ROLE / "tasks/main.yml")
    backup = read(DEPLOYMENT / "roles/transition-backup/tasks/main.yml")
    rollback_manifest = read(APP_ROLE / "templates/rollback-manifest.yml.j2")

    assert not (DEPLOYMENT / "rollout-stages.yml").exists()
    retired_inventory_keys = {
        "open_cinema_rollout_stage",
        "open_cinema_live_graph_allowlist",
        "open_cinema_local_product_gate_complete",
        "open_cinema_allow_experimental_deployment",
        "rollout_policy",
    }
    assert retired_inventory_keys.isdisjoint(group_inventory)
    assert retired_inventory_keys.isdisjoint(example_inventory["all"]["hosts"]["cinema_pi"])
    assert all(group_inventory["open_cinema"]["orchestration_features"].values())
    assert "open_cinema_release_status" not in group_inventory
    assert group_inventory["open_cinema_close_rollback_window"] is False
    assert "open_cinema_release_manifest.status in ['experimental', 'supported']" in site
    assert "open_cinema_release_manifest.runtime_profile == 'full'" in site

    assert "open_cinema_rollout" not in site
    assert "open_cinema_rollout" not in rollback_playbook
    assert "open_cinema_feature_" not in environment
    assert "OPEN_CINEMA_AUDIO_LIVE_GRAPH_ALLOWLIST=*" in environment
    assert environment.count("open_cinema_contract_gate_complete | default(false)") == 2
    assert 'runtimeProfile: "{{ open_cinema_release_manifest.runtime_profile }}"' in readiness
    assert 'runtime_profile: "{{ open_cinema_release_manifest.runtime_profile }}"' in readiness
    assert "rolloutStage" not in readiness
    assert "rollout_stage" not in readiness
    assert "rollout-stages.yml" not in backup
    assert (
        'runtime_profile: "{{ open_cinema_release_manifest.runtime_profile }}"' in rollback_manifest
    )
    assert "local_product_gate_complete" not in rollback_manifest


def test_processor_lifecycle_authorization_is_narrowly_scoped() -> None:
    common = read(DEPLOYMENT / "roles/common/tasks/main.yml")
    policy = read(DEPLOYMENT / "roles/common/templates/49-open-cinema-processors.rules.j2")

    assert "Install least-privilege managed processor lifecycle authorization" in common
    assert "org.freedesktop.systemd1.manage-units" in policy
    assert "camilladsp|pcm-auto-decoder" in policy
    assert '["start", "stop", "restart"]' in policy
    assert "enable" not in policy


def test_wireplumber_fragments_are_upgrade_safe_and_cover_bluetooth_roles() -> None:
    tasks = read(PIPEWIRE_ROLE / "tasks/main.yml")
    bluetooth = read(PIPEWIRE_ROLE / "templates/90-open-cinema-bluetooth.conf.j2")
    policy = read(PIPEWIRE_ROLE / "templates/91-open-cinema-policy.conf.j2")

    assert "/etc/wireplumber/wireplumber.conf.d" in tasks
    assert "/etc/systemd/user/{{ item }}.service.d" in tasks
    assert "a2dp_sink" in bluetooth
    assert "a2dp_source" in bluetooth
    assert "hfp_hf" in bluetooth
    assert "monitor.bluez.seat-monitoring = disabled" in bluetooth
    assert 'bluez5.media-source-role = "input"' in bluetooth
    assert "linking.allow-moving-streams = false" in policy
    assert "node.restore-default-targets = false" in policy
    assert 'device.name = "alsa_card.platform-soc_107c000000_sound"' in policy
    assert 'device.profile = "pro-audio"' in policy
    assert 'object.path = "alsa:acp:I2Sout:1:capture"' in policy
    assert 'node.description = "TV SPDIF input"' in policy
    assert "audio.channels = 2" in policy
    assert "audio.position = [ FL FR ]" in policy


def test_orchestrator_has_explicit_audio_identity_ordering_and_shutdown() -> None:
    unit = read(APP_ROLE / "templates/orchestrator.service.j2")
    tasks = read(APP_ROLE / "tasks/main.yml")

    assert "User={{ open_cinema.user }}" in unit
    assert (
        "After=network-online.target redis-server.service user@{{ open_cinema_uid }}.service"
        in unit
    )
    assert "XDG_RUNTIME_DIR={{ audio_service.runtime_dir }}" in unit
    assert "DBUS_SESSION_BUS_ADDRESS={{ audio_service.dbus_address }}" in unit
    assert "ExecStartPre=/usr/bin/test -S {{ audio_service.pipewire_socket }}" in unit
    assert "ExecStartPre=/usr/bin/redis-cli" in unit
    assert "open-cinema-orchestrator --check" in unit
    assert "RuntimeDirectoryPreserve=yes" in unit
    assert "TimeoutStopSec=20s" in unit
    assert "KillSignal=SIGTERM" in unit
    assert "KillMode=control-group" in unit
    assert "Verify application unit syntax and dependency graph before restart" in tasks
    assert "systemd-analyze" in tasks


def test_gunicorn_can_run_bounded_speaker_diagnostics_in_owned_audio_session() -> None:
    unit = read(APP_ROLE / "templates/gunicorn.service.j2")

    assert (
        "After=network.target redis-server.service user@{{ open_cinema_service_uid }}.service"
        in unit
    )
    assert "XDG_RUNTIME_DIR={{ audio_service.runtime_dir }}" in unit
    assert "DBUS_SESSION_BUS_ADDRESS={{ audio_service.dbus_address }}" in unit
    assert "PIPEWIRE_REMOTE=pipewire-0" in unit
    assert "RuntimeDirectory=open-cinema" in unit
    assert "RuntimeDirectoryPreserve=yes" in unit
    assert "ProtectHome=false" in unit
    assert "InaccessiblePaths=/home /root" in unit
    assert "ReadWritePaths={{ open_cinema.app_path }} /run/open-cinema /var/log/open-cinema" in unit


def test_audio_session_units_are_verified_before_restart() -> None:
    tasks = read(PIPEWIRE_ROLE / "tasks/main.yml")

    verify_at = tasks.index("Verify audio-session unit syntax and dependency graph before restart")
    start_at = tasks.index("Enable and start the PipeWire socket")
    assert verify_at < start_at
    assert "- systemd-analyze" in tasks
    assert "- --user" in tasks
    assert "- verify" in tasks


def test_local_wyreplumber_sync_never_copies_workstation_native_extensions() -> None:
    tasks = read(APP_ROLE / "tasks/main.yml")

    assert '"--exclude=*.so"' in tasks
    assert "Probe the Pi-native WyrePlumber extension" in tasks
    assert "Remove stale WyrePlumber native extensions" in tasks
    assert "--reinstall-package wyreplumber" in tasks


def test_celery_is_retained_only_for_bounded_orchestration_retention() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    tasks = read(APP_ROLE / "tasks/main.yml")
    beat = read(APP_ROLE / "templates/celery-beat.service.j2")

    assert inventory["open_cinema"]["celery_enabled"] is True
    assert "/etc/systemd/system/celery-beat.service" in tasks
    assert "when: open_cinema.celery_enabled | bool" in tasks
    assert "celery -A opencinema beat" in beat
    assert "TimeoutStopSec=30s" in beat


def test_redis_and_nginx_have_upgrade_safe_bounded_lifecycle_overrides() -> None:
    app_tasks = read(APP_ROLE / "tasks/main.yml")
    nginx_tasks = read(DEPLOYMENT / "roles/nginx/tasks/main.yml")
    redis_policy = read(APP_ROLE / "templates/redis.service.conf.j2")
    nginx_policy = read(DEPLOYMENT / "roles/nginx/templates/dependency.service.conf.j2")

    assert "/etc/systemd/system/redis-server.service.d/90-open-cinema.conf" in app_tasks
    assert "/etc/systemd/system/nginx.service.d/90-open-cinema.conf" in nginx_tasks
    for policy in (redis_policy, nginx_policy):
        assert "Restart=on-failure" in policy
        assert "TimeoutStartSec=30s" in policy
        assert "TimeoutStopSec=30s" in policy
    assert "--maxmemory {{ redis_policy.maxmemory_mb }}mb" in redis_policy
    assert '--save "" --appendonly no' in redis_policy
    assert "MemoryMax={{ redis_policy.systemd_memory_max_mb }}M" in redis_policy


def test_control_plane_state_has_bounded_database_worker_and_retention_policy() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    environment = read(APP_ROLE / "templates/env.j2")
    worker = read(APP_ROLE / "templates/celery.service.j2")
    readiness = read(READINESS_ROLE / "tasks/control-plane-limits.yml")

    assert inventory["redis_policy"]["maxmemory_mb"] == 128
    assert inventory["open_cinema"]["sqlite"]["wal_autocheckpoint_pages"] == 1000
    assert inventory["open_cinema"]["celery"]["worker_concurrency"] == 1
    assert "OPEN_CINEMA_AUDIO_PLAN_RETENTION_DAYS" in environment
    assert "CELERY_TASK_IGNORE_RESULT=true" in environment
    assert "--max-tasks-per-child={{ open_cinema.celery.max_tasks_per_child }}" in worker
    assert "Verify bounded Redis memory persistence and client policy" in readiness
    assert "PRAGMA wal_autocheckpoint" in readiness
    assert "Inspect bounded Celery unit execution and memory policy" in readiness


def test_destructive_migration_is_backed_up_and_failure_is_diagnostic() -> None:
    tasks = read(APP_ROLE / "tasks/main.yml")
    manifest = read(APP_ROLE / "templates/rollback-manifest.yml.j2")

    assert "Record the pending Django migration plan" in tasks
    assert "- migrate\n          - --plan" in tasks
    assert "Back up the pre-migration SQLite database" in tasks
    assert "Back up processor runtime configurations" in tasks
    assert "Apply Django migrations without preserving removed legacy audio data" in tasks
    assert "rescue:" in tasks
    assert "Retain failed migration service logs" in tasks
    assert "ansible.builtin.fail" in tasks
    assert "migration_policy: destructive-removal-of-legacy-audio-models" in manifest
    assert "migration_plan:" in manifest
    assert "Print the exact coordinated rollback boundary" in tasks
    assert "Determine whether a schema transition is pending" in tasks
    assert "No planned migration operations." in tasks
    assert "Stop the current application generation before a schema transition" in tasks
    assert "Reuse the latest retained rollback identity" in tasks
    assert "Enforce private ownership of the live SQLite database" in tasks
    assert 'mode: "0600"' in tasks
    assert "PRAGMA quick_check" in tasks
    assert "check_consistent_history" in tasks
    assert tasks.count("/usr/bin/timeout") >= 5
    assert ".backup" in tasks
    assert "Build the correlated migration failure result" in tasks
    assert "Retain the correlated migration failure result" in tasks
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    assert inventory["open_cinema"]["migrations"]["apply_timeout_seconds"] == 120


def test_end_of_play_readiness_covers_every_coordinated_component() -> None:
    tasks = read(READINESS_ROLE / "tasks/main.yml")

    for expected in (
        "PipeWire runtime socket",
        "WirePlumber-owned graph",
        "WyrePlumber orchestration contract",
        "Redis wake-up",
        "Django application and orchestrator",
        "exactly one active orchestrator controller process",
        "controller lock to identify the singleton process",
        "database schema and desired-to-applied orchestration progress",
        "orchestrator's bounded runtime snapshot",
        "versioned orchestration API route",
        "pinned CamillaDSP binary",
        "CamillaDSP control client contract",
        "generated CamillaDSP configuration",
        "pinned decoder binary",
        "decoder exposes the managed status protocol",
        "both web interfaces through the appliance network address",
        "referenced management and on-box static assets",
        "Reject anonymous access to administrative diagnostics",
        "Require versioned API schema metadata through nginx",
        "Require authorized administrative diagnostics through nginx",
        "authenticated SSE connection and cursor-gap recovery",
        "Retain readiness diagnostics",
    ):
        assert expected in tasks
    assert "connection.sync()" in tasks
    assert "capture_runtime_snapshot(connection)" in tasks
    assert "snapshot.health.state.value == 'connected'" in tasks
    assert "Stop deployment without deleting the previous rollback release" in tasks


def test_readiness_publishes_one_correlated_success_or_failure_result() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    tasks = read(READINESS_ROLE / "tasks/main.yml")

    assert inventory["open_cinema"]["readiness_result_path"].endswith("/readiness-result.json")
    assert "Probe every coordinated service after a readiness failure" in tasks
    assert "Correlate every failed follow-up readiness probe" in tasks
    assert "Build the correlated failed readiness result" in tasks
    assert "Retain the timestamped failed readiness result" in tasks
    assert "Build the aggregate successful end-of-play readiness result" in tasks
    assert "Publish the aggregate end-of-play readiness result" in tasks
    for field in (
        "releaseManifestSha256",
        "components:",
        "failedChecks:",
        "serviceLogs:",
        "runtimeFacts:",
    ):
        assert field in tasks


def test_service_ordering_uses_dependencies_and_readiness_not_timing_delays() -> None:
    orchestrator = read(APP_ROLE / "templates/orchestrator.service.j2")
    gunicorn = read(APP_ROLE / "templates/gunicorn.service.j2")
    celery = read(APP_ROLE / "templates/celery.service.j2")
    celery_beat = read(APP_ROLE / "templates/celery-beat.service.j2")
    camilladsp = read(DEPLOYMENT / "roles/camilladsp/templates/camilladsp@.service.j2")
    decoder = read(DEPLOYMENT / "roles/pcm-auto-decoder/templates/pcm-auto-decoder@.service.j2")

    assert "After=network-online.target redis-server.service user@" in orchestrator
    assert "ExecStartPre=/usr/bin/test -S {{ audio_service.pipewire_socket }}" in orchestrator
    assert "ExecStartPre=/usr/bin/redis-cli" in orchestrator
    assert "open-cinema-orchestrator --check" in orchestrator
    for service in (gunicorn, celery, celery_beat):
        assert "After=network.target redis-server.service" in service
        assert "Wants=redis-server.service" in service
    for processor in (camilladsp, decoder):
        assert (
            "After=user@{{ open_cinema_uid }}.service open-cinema-orchestrator.service" in processor
        )
        assert "ConditionPathExists=/run/open-cinema/" in processor
        assert "ExecStartPre=/usr/bin/test -S {{ audio_service.pipewire_socket }}" in processor

    deployment_sources = "\n".join(
        read(path)
        for role in DEPLOYMENT.glob("roles/*")
        for path in role.rglob("*")
        if path.is_file() and "benchmark-tools" not in path.parts
    )
    assert "ansible.builtin.pause:" not in deployment_sources
    assert "sleep " not in deployment_sources


def test_successful_readiness_keeps_one_active_and_verified_protected_rollback() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    tasks = read(READINESS_ROLE / "tasks/main.yml")

    assert inventory["open_cinema"]["rollback_releases_to_keep"] == 1
    assert inventory["private_rollback_capsule_path"] == ""
    assert "Require one active rollback release and any verified protected exception" in tasks
    assert "Record the successful one-release rollback boundary" in tasks
    assert "rollback-window.yml" in tasks
    assert "Remove rollback bundles older than the accepted previous release" in tasks
    assert "open_cinema_protected_rollback_bundle_paths" in tasks
    assert "open_cinema_expected_retained_rollback_paths" in tasks
    assert "Verify the active and protected rollback releases remain" in tasks
    assert "['verified', 'target-verified']" in tasks


def test_private_inventory_is_ignored_and_public_example_has_safe_placeholders() -> None:
    gitignore = read(ROOT / ".gitignore")
    example = yaml.safe_load(read(DEPLOYMENT / "inventories/example.yml"))
    host = example["all"]["hosts"]["cinema_pi"]

    assert "/deployment/inventories/local.yml" in gitignore
    assert "/deployment/inventories/*.local.yml" in gitignore
    assert host["open_cinema_release_manifest_source_path"].startswith("/absolute/")
    assert host["private_rollback_capsule_path"].startswith("/absolute/private/")


def test_readiness_preserves_a_manifest_published_by_rollback() -> None:
    tasks = read(READINESS_ROLE / "tasks/main.yml")

    load_at = tasks.index("Load the coordinated release manifest for independently tagged runs")
    assert "when: open_cinema_release_manifest is not defined" in tasks[load_at : load_at + 300]


def test_readiness_verifies_vendor_integrity_and_permission_boundaries() -> None:
    audio_tasks = read(PIPEWIRE_ROLE / "tasks/main.yml")
    readiness = read(READINESS_ROLE / "tasks/main.yml")
    permission_checks = read(READINESS_ROLE / "tasks/permissions.yml")

    assert "Find previously managed WirePlumber configuration fragments" in audio_tasks
    assert "Remove obsolete Open Cinema WirePlumber fragments" in audio_tasks
    assert "*-open-cinema-*.conf" in audio_tasks
    assert "distribution PipeWire and WirePlumber files to remain unmodified" in readiness
    assert "dpkg" in readiness and "--verify" in readiness
    assert "Verify deployment ownership and permission boundaries" in readiness
    assert "Inspect fixed deployment ownership and permission boundaries" in permission_checks
    assert "Require private retained rollback files" in permission_checks
    assert "Require private diagnostic files" in permission_checks
    assert "Require private processor runtime files and sockets" in permission_checks


def test_nginx_restricts_the_management_api_to_configured_networks() -> None:
    inventory = yaml.safe_load(read(DEPLOYMENT / "inventories/group_vars/all.yml"))
    nginx_tasks = read(DEPLOYMENT / "roles/nginx/tasks/main.yml")
    nginx_site = read(DEPLOYMENT / "roles/nginx/templates/open-cinema.conf.j2")
    readiness = read(READINESS_ROLE / "tasks/main.yml")

    assert inventory["open_cinema_management_api_networks"] == ["127.0.0.1"]
    assert "Require an explicit bounded management API network policy" in nginx_tasks
    assert "0.0.0.0/0" in nginx_tasks and "::/0" in nginx_tasks
    assert "{% for network in open_cinema_management_api_networks %}" in nginx_site
    assert "allow {{ network }};" in nginx_site
    assert "deny all;" in nginx_site
    assert "Inspect the effective nginx management API boundary" in readiness
    assert "Require every configured API source and the default deny rule" in readiness


def test_ansible_does_not_mutate_dynamic_audio_intent() -> None:
    deployment_sources = [
        path
        for path in DEPLOYMENT.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml", ".j2", ".py"}
    ]
    source = "\n".join(read(path) for path in deployment_sources)
    dynamic_models = (
        "GraphDefinition",
        "GraphRevision",
        "GraphActivation",
        "LogicalEndpoint",
        "CamillaDSPProfile",
        "ManualOverride",
    )
    mutators = "create|update|delete|bulk_create|bulk_update|get_or_create|update_or_create"

    for model in dynamic_models:
        assert re.search(rf"{model}\.objects\.({mutators})\s*\(", source) is None

    audio_api_urls = re.finditer(r"url:\s*>?-?\s*\n?\s*.*?/api/audio/v1[^\n]*", source)
    for match in audio_api_urls:
        following_task = source[match.start() : match.start() + 500]
        assert re.search(r"\n\s*method:\s*(POST|PUT|PATCH|DELETE)\b", following_task) is None

    assert (
        re.search(
            r"\b(INSERT\s+INTO|UPDATE\s+(api_|orchestration_)|DELETE\s+FROM\s+(api_|orchestration_))",
            source,
            flags=re.IGNORECASE,
        )
        is None
    )


def test_preflight_aggregates_compatibility_before_destructive_or_live_roles() -> None:
    site = read(DEPLOYMENT / "playbooks/site.yml")
    preflight = read(DEPLOYMENT / "roles/preflight/tasks/main.yml")
    defaults = yaml.safe_load(read(DEPLOYMENT / "roles/preflight/defaults/main.yml"))

    assert site.index("role: preflight") < site.index("name: camilladsp")
    assert site.index("role: preflight") < site.index("name: open-cinema")
    assert site.index("role: preflight") < site.index("name: pcm-auto-decoder")
    assert preflight.count("ansible.builtin.assert:") == 1
    assert "Build one actionable preflight compatibility result" in preflight
    assert "open_cinema_preflight_platform_failures" in preflight
    assert "open_cinema_preflight_repository_failures" in preflight
    assert "open_cinema_preflight_identity_failures" in preflight
    assert "open_cinema_preflight_audio_failures" in preflight
    assert "open_cinema_preflight_runtime_failures" in preflight
    assert "open_cinema_preflight_manifest_failures" in preflight
    assert "Probe installed Python packages and orchestration contracts" in preflight
    assert "Verify retained rollback input for standalone preflight runs" in preflight
    assert "private-rollback-preflight.yml" in preflight
    normalize_at = preflight.index(
        "Normalize independent host and component probe results"
    )
    match_at = preflight.index(
        "Match the normalized host against supported Raspberry Pi models"
    )
    classify_at = preflight.index("Classify the target platform")
    assert normalize_at < match_at < classify_at
    assert defaults["open_cinema_preflight_result_path"] == "/tmp/open-cinema-preflight-result.json"


def test_development_environment_is_isolated_pinned_and_uses_cross_repo_fixtures() -> None:
    dockerfile = read(ROOT / ".devcontainer/Dockerfile")
    compose = yaml.safe_load(read(ROOT / ".devcontainer/docker-compose.yml"))
    start = read(ROOT / ".devcontainer/start-pipewire.sh")

    assert "FROM debian:trixie-slim" in dockerfile
    assert "libwireplumber-0.5-dev" in dockerfile
    assert "camilladsp-linux-pipewire" not in dockerfile
    assert compose["services"]["redis"]["image"] == "redis:7.4.2-alpine"
    volumes = compose["services"]["app"]["volumes"]
    assert any("wyreplumber" in item for item in volumes)
    assert any("pcm-auto-decoder" in item for item in volumes)
    assert "/tmp/open-cinema-runtime" in dockerfile
    assert "dbus-daemon" in start
    assert "PIPEWIRE_REMOTE=pipewire-0" in start
    assert "wpctl status" in start
    assert (ROOT / ".devcontainer/fakes/replay_decoder_status.py").is_file()


def test_all_deployment_yaml_is_well_formed_before_jinja_rendering() -> None:
    for path in DEPLOYMENT.rglob("*.yml"):
        yaml.safe_load(read(path))
