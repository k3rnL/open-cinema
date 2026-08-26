from pathlib import Path

ROLE = Path("deployment/roles/pcm-auto-decoder")


def test_decoder_role_installs_managed_template_and_runtime_directory() -> None:
    tasks = (ROLE / "tasks/main.yml").read_text()
    tmpfiles = (ROLE / "templates/open-cinema-decoder.tmpfiles.j2").read_text()
    unit_path = ROLE / "templates/pcm-auto-decoder@.service.j2"

    assert "systemd-tmpfiles --create" in tasks
    assert "/etc/systemd/system/pcm-auto-decoder@.service" in tasks
    assert "systemd-analyze verify" in tasks
    assert "/run/open-cinema/decoder" in tmpfiles
    assert "{{ open_cinema.user }} {{ open_cinema.group }}" in tmpfiles
    assert unit_path.is_file()
    assert not (ROLE / "templates/pcm-auto-decoder.service.j2").exists()


def test_decoder_unit_uses_owned_runtime_contract_and_hardening() -> None:
    unit = (ROLE / "templates/pcm-auto-decoder@.service.j2").read_text()

    assert "User={{ open_cinema.user }}" in unit
    assert "Group={{ open_cinema.group }}" in unit
    assert "ConditionPathExists=/run/open-cinema/decoder/%i.env" in unit
    assert "EnvironmentFile=/run/open-cinema/decoder/%i.env" in unit
    assert "--instance-id %i" in unit
    assert "--status-socket /run/open-cinema/decoder/%i.sock" in unit
    assert "After=user@{{ open_cinema_uid }}.service" in unit
    assert "ExecStartPre=/usr/bin/test -S {{ audio_service.pipewire_socket }}" in unit
    assert "Restart=on-failure" in unit
    assert "TimeoutStopSec=10s" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=false" in unit
    assert "InaccessiblePaths=/home /root" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "ReadWritePaths=/run/open-cinema/decoder" in unit


def test_ansible_does_not_enable_an_unconfigured_decoder_instance() -> None:
    tasks = (ROLE / "tasks/main.yml").read_text()

    assert "enabled: true" not in tasks
    assert "state: started" not in tasks
