import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from core.orchestration.adaptive_decoder import (
    AdaptiveDecoderPolicy,
    resolve_adaptive_decoder_choice,
)
from core.orchestration.signal_descriptors import SignalDescriptor
from core.orchestration.world_state_scheduler import (
    WorldStateScheduleState,
    schedule_world_state_observation,
    signal_world_state_observation,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "orchestration" / "adaptive_signal_traces.json"
SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "audio-signal-descriptor-v1.schema.json"


@pytest.fixture(scope="module")
def adaptive_signal_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_covers_every_required_adaptive_signal_case(
    adaptive_signal_fixture,
) -> None:
    assert {case["id"] for case in adaptive_signal_fixture["cases"]} == {
        "plain-pcm",
        "detecting-unknown",
        "ac3",
        "eac3",
        "dts",
        "codec-change",
        "stereo-in-codec",
        "unsupported-codec",
        "false-preamble",
        "status-failure",
    }


def test_every_fixture_descriptor_matches_schema_and_executable_behavior(
    adaptive_signal_fixture,
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    policy = AdaptiveDecoderPolicy.from_document(adaptive_signal_fixture["policy"])

    for case in adaptive_signal_fixture["cases"]:
        state = WorldStateScheduleState()
        material_content = {}
        for observation in case["observations"]:
            descriptor_document = observation["descriptor"]
            assert list(validator.iter_errors(descriptor_document)) == [], case["id"]
            descriptor = SignalDescriptor.from_document(descriptor_document)
            material_key = signal_world_state_observation(
                descriptor,
                observation_window_ms=observation["observationWindowMs"],
                observed_at_ms=observation["observedAtMs"],
            )
            material_content[material_key.material_key] = descriptor.content.kind.value
            scheduling = schedule_world_state_observation(
                policy.stability_policy,
                state,
                material_key,
            )
            state = scheduling.state
            decision = resolve_adaptive_decoder_choice(
                descriptor,
                policy,
                decoder_available=observation["decoderAvailable"],
            )
            expected = observation["expected"]

            assert decision.choice.value == expected["choice"], case["id"]
            assert decision.status.value == expected["decisionStatus"], case["id"]
            assert decision.reason == expected["reason"], case["id"]
            assert scheduling.status.value == expected["schedulerStatus"], case["id"]
            assert scheduling.schedule_resolution is expected["scheduleResolution"]
            if "schedulerReason" in expected:
                assert scheduling.reason == expected["schedulerReason"], case["id"]
            if "activeContent" in expected:
                assert material_content[state.active_key] == expected["activeContent"]
            layouts = decision.output_contract.layouts if decision.output_contract else ()
            output_channels = layouts[0].channels if layouts else None
            assert output_channels == expected["outputChannels"], case["id"]


def test_status_failure_is_distinct_from_detection_and_unknown_signal(
    adaptive_signal_fixture,
) -> None:
    by_id = {case["id"]: case for case in adaptive_signal_fixture["cases"]}
    detecting = by_id["detecting-unknown"]["observations"][0]
    failure = by_id["status-failure"]["observations"][0]

    assert detecting["processorHealth"] == "detecting"
    assert detecting["decoderAvailable"] is True
    assert failure["processorHealth"] == "status-channel-failed"
    assert failure["decoderAvailable"] is False
