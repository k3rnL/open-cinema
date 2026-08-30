from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model

from wyreplumber.runtime import FrozenDict

from api.audio_v1.representations import plan_document
from api.models import (
    AppliedPlanState,
    GraphDefinition,
    GraphRevision,
    ResolvedPlan,
)
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.resolved_plan import build_resolved_plan
from core.orchestration.resolver_inputs import (
    ResolverGraphRevisionInput,
    ResolverLogicalEndpointInput,
    ResolverSignalFactsInput,
)
from core.orchestration.resolver_pipeline import run_resolution_pipeline
from tests.test_resolver_pipeline import (
    _registry,
    _resolver_inputs,
    _root_document,
    _selector,
)


def _resolved(inputs=None):
    inputs = inputs or _resolver_inputs()
    return build_resolved_plan(inputs, run_resolution_pipeline(inputs, registry=_registry()))


def _output_selector_inputs(*, headset_available: bool):
    inputs = _resolver_inputs()
    document = _root_document()
    sink = next(node for node in document["nodes"] if node["id"] == "sink")
    sink.update(
        {
            "type": "core.ordered-selector",
            "configuration": {
                "mode": "first-available",
                "candidates": [
                    {"endpoint": "endpoint:headset", "priority": 300},
                    {"endpoint": "endpoint:speakers", "priority": 100},
                ],
            },
        }
    )
    graph = ResolverGraphRevisionInput(
        definition_id=inputs.graph.definition_id,
        revision_id=inputs.graph.revision_id,
        revision_number=inputs.graph.revision_number,
        schema_version=inputs.graph.schema_version,
        content_digest=graph_content_digest(document),
        document=document,
    )
    headset = ResolverLogicalEndpointInput(
        endpoint_id="endpoint:headset",
        name="Headset",
        direction="output",
        selector=(
            _selector("device.properties.device.serial", "ROOM-123")
            if headset_available
            else _selector("device.properties.device.serial", "DISCONNECTED")
        ),
    )
    return replace(inputs, graph=graph, logical_endpoints=(*inputs.logical_endpoints, headset))


def test_normal_route_uses_human_endpoint_names_and_ordered_segments() -> None:
    presentation = _resolved().explanation["presentation"]

    assert presentation["headline"] == {
        "status": "active",
        "title": "Phone is playing on Speakers",
        "summary": "The selected route is ready.",
    }
    assert [segment["role"] for segment in presentation["route"]] == [
        "source",
        "process",
        "output",
    ]
    assert presentation["selection"]["winner"] == "Speakers"
    assert presentation["signals"]["input"]["content.codec"] == "pcm"


def test_encoded_decoder_and_channel_facts_are_explained() -> None:
    inputs = _resolver_inputs()
    encoded_inputs = replace(
        inputs,
        signal_facts=ResolverSignalFactsInput(
            version=1,
            facts={
                "signal.source.content.codec": "ac3",
                "signal.source.channels": 6,
            },
        ),
    )
    pipeline = run_resolution_pipeline(encoded_inputs, registry=_registry())
    expanded = pipeline.expanded_document.to_dict()
    processor = next(node for node in expanded["nodes"] if node["id"] == "processing/process")
    processor["type"] = "processor.pcm-auto-decoder"
    pipeline = replace(pipeline, expanded_document=FrozenDict(expanded))

    presentation = build_resolved_plan(encoded_inputs, pipeline).explanation["presentation"]

    decoder = presentation["processors"][0]
    assert decoder["role"] == "decode"
    assert decoder["name"] == "Adaptive PCM decoder"
    assert decoder["detail"] == "Decode AC3 to PCM · 6 channels"


def test_headset_preference_wins_when_available() -> None:
    presentation = _resolved(_output_selector_inputs(headset_available=True)).explanation[
        "presentation"
    ]

    assert presentation["headline"]["title"] == "Phone is playing on Headset"
    assert presentation["selection"]["winner"] == "Headset"
    assert presentation["selection"]["reasonCode"] == "first-available"
    speakers = next(item for item in presentation["alternatives"] if item["name"] == "Speakers")
    assert speakers["reasonCode"] == "lower_priority"


def test_unavailable_headset_explains_speaker_fallback() -> None:
    presentation = _resolved(_output_selector_inputs(headset_available=False)).explanation[
        "presentation"
    ]

    assert presentation["selection"]["winner"] == "Speakers"
    assert presentation["headline"]["summary"] == (
        "Headset is unavailable, so Speakers was selected."
    )
    headset = next(item for item in presentation["alternatives"] if item["name"] == "Headset")
    assert headset["status"] == "unavailable"
    assert headset["technicalEvidence"] == ("endpoint:unavailable",)


def test_inactive_graph_and_waiting_processor_have_actionable_wording() -> None:
    inactive_inputs = _resolver_inputs(cinema=False)
    inactive = _resolved(inactive_inputs).explanation["presentation"]
    waiting = _resolved(_resolver_inputs(resources=False)).explanation["presentation"]

    assert inactive["headline"]["status"] == "inactive"
    assert "Activate" in inactive["headline"]["summary"]
    assert waiting["headline"]["status"] == "waiting"
    assert waiting["errors"][0]["nextStep"].startswith("Wait for the processor")


@pytest.mark.django_db
def test_plan_api_presentation_tracks_converged_and_failed_reconciliation() -> None:
    api_user = get_user_model().objects.create_user(username="explanation-owner")
    graph = GraphDefinition.objects.create(owner=api_user, name="Runtime presentation")
    revision = GraphRevision.objects.create(
        definition=graph,
        author=api_user,
        revision_number=1,
        state="published",
        content={
            "schemaVersion": 1,
            "id": str(graph.pk),
            "kind": "graph",
            "metadata": {"name": "Runtime presentation"},
            "parameters": [],
            "publicPorts": [],
            "conditions": [],
            "nodes": [],
            "edges": [],
            "layout": {},
        },
    )
    explanation = _resolved().explanation.to_dict()
    plan = ResolvedPlan.objects.create(
        graph_definition=graph,
        graph_revision=revision,
        desired_state_version=1,
        world_generation=1,
        world_sequence=1,
        resolution_mode="live",
        status="resolved",
        document={"world": {"version": "1:1:1:1:1:1:1"}},
        explanation=explanation,
    )
    state = AppliedPlanState.objects.create(
        graph_definition=graph,
        current_plan=plan,
        transition_generation=1,
        status="converged",
    )

    assert (
        plan_document(plan, applied_state=state)["explanation"]["presentation"]["transition"][
            "status"
        ]
        == "converged"
    )

    state.status = "failed"
    state.last_error = {"message": "CamillaDSP did not become ready."}
    state.save(update_fields=("status", "last_error"))
    failed = plan_document(plan, applied_state=state)["explanation"]["presentation"]

    assert failed["headline"]["status"] == "failed"
    assert failed["transition"]["message"] == "CamillaDSP did not become ready."
    assert failed["errors"][-1]["code"] == "reconciliation_failed"
