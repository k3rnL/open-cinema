from dataclasses import replace

from wyreplumber.runtime import FrozenDict, NodeState, NodeValue

from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from core.orchestration.decoder_driver import DecoderInstanceConfiguration
from core.orchestration.processor_runtime import (
    ProcessorNodeMatchStatus,
    match_managed_processor_node,
)
from core.plugin_system.contracts import ProcessingDriverRequest
from tests.test_endpoint_inventory_mapping import _snapshot


def _decoder_configuration() -> DecoderInstanceConfiguration:
    return DecoderInstanceConfiguration.from_request(
        ProcessingDriverRequest(
            node_instance_id="living-room",
            idempotency_key="test-correlation",
            configuration={},
            plan={},
        )
    )


def _node(identity, node_id: int) -> NodeValue:
    return NodeValue(
        id=node_id,
        name=identity.node_name,
        media_class="Audio/Sink",
        state=NodeState.IDLE,
        properties=FrozenDict(
            {
                "node.name": identity.node_name,
                "node.group": identity.node_group_name,
                **identity.required_properties.to_dict(),
            }
        ),
    )


def test_decoder_nodes_rematch_after_runtime_ids_change() -> None:
    identity = _decoder_configuration().runtime_identities[1]
    first = replace(_snapshot(generation=1), nodes=(_node(identity, 100),))
    restarted = replace(_snapshot(generation=2), nodes=(_node(identity, 900),))

    before = match_managed_processor_node(first, identity)
    after = match_managed_processor_node(restarted, identity)

    assert before.status is ProcessorNodeMatchStatus.MATCHED
    assert after.status is ProcessorNodeMatchStatus.MATCHED
    assert before.selected.identity.stable_key == after.selected.identity.stable_key
    assert before.selected.runtime_key != after.selected.runtime_key


def test_decoder_match_requires_instance_and_port_properties() -> None:
    identity = _decoder_configuration().runtime_identities[1]
    wrong = _node(identity, 100)
    wrong = replace(
        wrong,
        properties=FrozenDict(
            {**wrong.properties.to_dict(), "open-cinema.processor.instance": "other"}
        ),
    )

    result = match_managed_processor_node(
        replace(_snapshot(), nodes=(wrong,)),
        identity,
    )

    assert result.status is ProcessorNodeMatchStatus.NO_MATCH


def test_camilladsp_matches_native_name_and_group_without_custom_properties() -> None:
    identity = CamillaDSPDeploymentPolicy().runtime_identities(0)[1]
    result = match_managed_processor_node(
        replace(_snapshot(), nodes=(_node(identity, 40),)),
        identity,
    )

    assert result.status is ProcessorNodeMatchStatus.MATCHED
    assert result.selected.projection_document()["identity"]["port"] == "playback"


def test_duplicate_native_nodes_are_reported_as_ambiguous() -> None:
    identity = CamillaDSPDeploymentPolicy().runtime_identities(0)[0]
    result = match_managed_processor_node(
        replace(_snapshot(), nodes=(_node(identity, 40), _node(identity, 41))),
        identity,
    )

    assert result.status is ProcessorNodeMatchStatus.AMBIGUOUS
    assert result.selected is None
