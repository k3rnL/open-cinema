import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "admin_ux_scenarios.json"


def test_admin_ux_fixture_covers_required_platform_and_audio_states() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert document["fixtureVersion"] == "open-cinema.admin-ux/v1"
    assert document["system"]["raspberry"]["temperatureCelsius"] > 0
    assert document["system"]["partial"]["throttling"]["supported"] is False
    assert {item["id"] for item in document["components"]} >= {
        "open-cinema",
        "open-cinema-orchestrator",
        "wyreplumber",
        "camilladsp",
        "pcm-auto-decoder",
    }

    endpoints = {item["id"]: item for item in document["endpoints"]}
    assert endpoints["endpoint-speakers"]["volume"]["writable"] is True
    assert endpoints["endpoint-hdmi"]["volume"]["writable"] is False

    resources = {item["kind"]: item for item in document["managedResources"]}
    assert resources["roc-receiver"]["actions"] == [{"id": "restart", "available": True}]
    assert resources["camilladsp"]["actions"] == []
    assert resources["pcm-auto-decoder"]["actions"] == []

    explanation = document["explanation"]
    assert [segment["role"] for segment in explanation["route"]] == [
        "source",
        "decode",
        "process",
        "output",
    ]
    assert explanation["alternatives"][0]["status"] == "unavailable"
