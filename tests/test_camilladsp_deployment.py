from dataclasses import replace
from pathlib import Path

import yaml

from wyreplumber.runtime import FrozenDict

from core.orchestration.endpoint_inventory import RuntimeEndpointReference
from core.orchestration.endpoint_matching import EndpointMatchStatus, match_endpoint_candidates
from core.orchestration.endpoint_selectors import parse_endpoint_selector
from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from tests.test_endpoint_matching import _sink

ROLE = Path("deployment/roles/camilladsp")


def test_camilladsp_role_installs_owned_template_without_starting_instances() -> None:
    tasks = (ROLE / "tasks/main.yml").read_text()
    unit = (ROLE / "templates/camilladsp@.service.j2").read_text()
    tmpfiles = (ROLE / "templates/open-cinema-camilladsp.tmpfiles.j2").read_text()

    assert "/etc/systemd/system/camilladsp@.service" in tasks
    assert "systemd-analyze verify" in tasks
    assert "enabled: true" not in tasks
    assert "state: started" not in tasks
    assert "ConditionPathExists=/run/open-cinema/camilladsp/%i.env" in unit
    assert "EnvironmentFile=/run/open-cinema/camilladsp/%i.env" in unit
    assert "--wait" in unit
    assert "--address ${CAMILLADSP_ADDRESS}" in unit
    assert "ExecStartPre=/usr/bin/test -S {{ audio_service.pipewire_socket }}" in unit
    assert "After=user@{{ open_cinema_uid }}.service" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/run/open-cinema/camilladsp" in unit
    assert "/run/open-cinema/camilladsp" in tmpfiles
    assert not (ROLE / "templates/camilladsp.service.j2").exists()


def test_native_processor_nodes_are_instance_scoped_and_restart_matchable() -> None:
    capture, playback = CamillaDSPDeploymentPolicy().endpoints(0)

    assert capture.node_name == "opencinema.camilladsp.0.capture"
    assert playback.node_name == "opencinema.camilladsp.0.playback"
    assert capture.node_group_name == playback.node_group_name
    assert capture.autoconnect_to is None
    assert playback.autoconnect_to is None
    assert not (ROLE / "templates/80-open-cinema-camilladsp.conf.j2").exists()

    selector = parse_endpoint_selector(
        {
            "version": 1,
            "match": "all",
            "predicates": [
                {
                    "path": "node.name",
                    "operator": "exact",
                    "value": playback.node_name,
                },
                {
                    "path": "node.properties.open-cinema.endpoint-id",
                    "operator": "exact",
                    "value": "processor:camilladsp:0:output",
                },
            ],
        }
    ).selector
    base = _sink()
    before_restart = replace(
        base,
        runtime=RuntimeEndpointReference(1, 100, None),
        name=playback.node_name,
        node_properties=FrozenDict(
            {
                **base.node_properties.to_dict(),
                "open-cinema.endpoint-id": "processor:camilladsp:0:output",
            }
        ),
    )
    after_restart = replace(
        before_restart,
        runtime=RuntimeEndpointReference(2, 900, None),
    )

    first = match_endpoint_candidates(selector, [before_restart])
    second = match_endpoint_candidates(selector, [after_restart])

    assert first.status is EndpointMatchStatus.MATCHED
    assert second.status is EndpointMatchStatus.MATCHED
    assert first.selected.runtime_key != second.selected.runtime_key
    assert first.selected.name == second.selected.name


def test_inventory_declares_runtime_policy_and_manifest_pins_release_asset() -> None:
    inventory = Path("deployment/inventories/group_vars/all.yml").read_text()
    manifest = yaml.safe_load(Path("deployment/release-manifest.yml").read_text())

    assert 'websocket_address: "127.0.0.1"' in inventory
    assert "instance_count: 1" in inventory
    assert 'bus_prefix: "opencinema.camilladsp"' in inventory
    assert 'sharing_policy: "exclusive"' in inventory
    assert 'reconfiguration_policy: "reconfigure-idle"' in inventory
    component = manifest["components"]["camilladsp"]
    assert component["version"] == "4.1.3"
    assert component["artifacts"][0]["name"] == "camilladsp-linux-pipewire-aarch64.tar.gz"
    assert "build_from_source" not in inventory
