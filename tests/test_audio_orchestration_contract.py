from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "contracts" / "audio-orchestration-v1.yml"


def load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_covers_every_coordinated_component() -> None:
    assert set(load_contract()["components"]) == {
        "open-cinema",
        "wyreplumber",
        "open-cinema-ui",
        "pcm-auto-decoder",
        "deployment",
    }


def test_every_interface_has_version_detection_and_failure_behavior() -> None:
    for contract in load_contract()["contracts"].values():
        assert contract["supported_major"] >= 1
        assert contract["producer"]
        assert contract["consumers"]
        assert contract["detection"]
        assert contract["failure"]


def test_incompatible_or_missing_major_versions_are_rejected() -> None:
    policy = load_contract()["version_policy"]

    assert policy["missing_version"] == "reject"
    assert policy["major_mismatch"] == "reject"
    assert policy["unknown_required_capability"] == "reject"


def test_all_compatibility_gates_precede_graph_activation() -> None:
    gates = load_contract()["activation_gates"]
    orders = [gate["order"] for gate in gates]

    assert orders == sorted(orders)
    assert len(orders) == len(set(orders))
    assert gates[-1]["id"] == "graph-activation"
    assert {gate["id"] for gate in gates[:-1]} == {
        "deployment-preflight",
        "persistent-schema-startup",
        "runtime-handshake",
        "processor-handshake",
        "client-handshake",
    }
