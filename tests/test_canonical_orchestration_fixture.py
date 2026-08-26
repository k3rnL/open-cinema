import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "orchestration" / "canonical"


def load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_desired_graph_contains_only_stable_endpoint_references() -> None:
    document = load("desired_graph.json")
    graph = document["graph"]
    serialized = json.dumps(graph)

    assert document["fixtureVersion"] == "open-cinema.canonical-acceptance/v1"
    assert graph["schemaVersion"] == 1
    assert {endpoint["id"] for endpoint in document["logicalEndpoints"]} == {
        "endpoint:tv",
        "endpoint:bluetooth-programme",
        "endpoint:main-speakers",
        "endpoint:headset",
    }
    assert "runtimeId" not in serialized


def test_case_world_versions_and_references_are_consistent() -> None:
    cases = load("cases.json")
    graph = load("desired_graph.json")["graph"]
    endpoint_ids = {endpoint["id"] for endpoint in load("desired_graph.json")["logicalEndpoints"]}
    world_versions = []

    assert cases["desiredGraph"] == graph["id"]
    for case in cases["cases"]:
        world_versions.append(case["world"]["version"])
        assert set(case["world"]["endpoints"]) == endpoint_ids
        assert case["expectedPlan"]["selectedInput"] in endpoint_ids
        assert case["expectedPlan"]["selectedOutput"] in endpoint_ids
        assert case["expectedPlan"]["status"] == "resolved"
        assert case["explanation"]
        assert case["runtimeAssertions"]

    assert world_versions == sorted(world_versions)
    assert len(world_versions) == len(set(world_versions))


def test_cases_cover_source_output_and_format_switches() -> None:
    cases = {case["id"]: case for case in load("cases.json")["cases"]}

    assert cases["case:tv-pcm-main-speakers"]["expectedPlan"] == {
        "status": "resolved",
        "selectedInput": "endpoint:tv",
        "selectedOutput": "endpoint:main-speakers",
        "decoderMode": "pcm-bypass",
        "decodedSignal": {"format": "S16LE", "rate": 48000, "channels": 2},
        "camillaProfile": "camilladsp:living-room",
        "actionIntent": ["prepare-camilladsp", "set-stream-target", "verify-route"],
    }
    assert (
        cases["case:bluetooth-main-speakers"]["expectedPlan"]["selectedInput"]
        == "endpoint:bluetooth-programme"
    )
    assert (
        cases["case:headset-overrides-output"]["expectedPlan"]["selectedOutput"]
        == "endpoint:headset"
    )
    restored = cases["case:headset-removed-restores-speakers"]["expectedPlan"]
    assert restored["selectedInput"] == "endpoint:bluetooth-programme"
    assert restored["selectedOutput"] == "endpoint:main-speakers"
    assert restored["camillaProfile"] == "camilladsp:living-room"
    ac3_plan = cases["case:tv-ac3-decoded-to-room"]["expectedPlan"]
    assert ac3_plan["decoderMode"] == "decode"
    assert ac3_plan["decodedSignal"]["channels"] == 6
    assert ac3_plan["camillaProfile"] == "camilladsp:living-room"


def test_each_expected_plan_has_assertions_for_selected_route() -> None:
    for case in load("cases.json")["cases"]:
        assertions = {
            assertion["path"]: assertion["equals"] for assertion in case["runtimeAssertions"]
        }
        plan = case["expectedPlan"]
        assert assertions["route.source.logicalEndpoint"] == plan["selectedInput"]
        assert assertions["route.sink.logicalEndpoint"] == plan["selectedOutput"]


def test_routing_mechanism_evaluation_covers_canonical_and_advanced_shapes() -> None:
    evaluation = load("routing_mechanisms.json")
    canonical_case_ids = {case["id"] for case in load("cases.json")["cases"]}
    evaluated_case_ids = {case["id"] for case in evaluation["canonicalCases"]}

    assert evaluation["desiredGraph"] == "graph:canonical-home-cinema"
    assert evaluation["canonicalRequiresRawLinks"] is False
    assert evaluated_case_ids == canonical_case_ids
    assert all(case["rawManagedLinks"] is False for case in evaluation["canonicalCases"])
    assert {stage["mechanism"] for stage in evaluation["canonicalStages"]} == {
        "stream-target-metadata",
        "configured-default-metadata",
    }
    assert all(stage["rawManagedLinks"] is False for stage in evaluation["canonicalStages"])

    advanced = {shape["id"]: shape for shape in evaluation["advancedShapes"]}
    assert advanced["controlled-fan-out"]["rawManagedLinks"] is True
    assert advanced["multi-source-mixer"]["rawManagedLinks"] is True
    assert advanced["stable-processor-internal-topology"]["rawManagedLinks"] == ("conditional")
    assert all(
        shape["requiredOwnership"] == "open-cinema.orchestrator" for shape in advanced.values()
    )
