from dataclasses import replace

import pytest
from wyreplumber.runtime import (
    ConnectionHealthValue,
    ConnectionState,
    FrozenDict,
    LinkValue,
    NodeValue,
    PortDirection,
    PortValue,
    RuntimeSnapshot,
)

from core.orchestration.driver_actions import (
    ActionFailureClassification,
    DriverActionError,
    DriverCommand,
)
from core.orchestration.wireplumber_driver import (
    OPEN_CINEMA_LINK_OWNER,
    ManagedLinkShape,
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_managed_link_action,
    build_remove_managed_link_action,
    observe_managed_link,
    register_managed_link_controls,
)
from tests.test_wireplumber_driver import _confirmed_outcome


def _link(*, link_id=30, owner=OPEN_CINEMA_LINK_OWNER, desired_id="fanout:left"):
    properties = FrozenDict()
    if owner is not None and desired_id is not None:
        properties = FrozenDict(
            {
                "open-cinema.owner": owner,
                "open-cinema.desired-id": desired_id,
                "link.group": "front",
                "link.passive": "true",
            }
        )
    return LinkValue(
        id=link_id,
        output_node_id=1,
        output_port_id=11,
        input_node_id=2,
        input_port_id=21,
        owner=owner,
        desired_id=desired_id,
        properties=properties,
    )


def _runtime(*, links=()):
    return RuntimeSnapshot(
        generation=9,
        sequence=4,
        captured_at="2026-08-22T12:00:00Z",
        health=ConnectionHealthValue(ConnectionState.CONNECTED, 9),
        nodes=(
            NodeValue(id=1, name="managed-output", output_port_ids=(11,)),
            NodeValue(id=2, name="managed-input", input_port_ids=(21,)),
        ),
        ports=(
            PortValue(id=11, node_id=1, direction=PortDirection.OUTPUT),
            PortValue(id=21, node_id=2, direction=PortDirection.INPUT),
        ),
        links=tuple(links),
    )


def _adapter(runtime, calls):
    def control(kind):
        def invoke(connection, **kwargs):
            calls.append((kind, connection, kwargs))
            return _confirmed_outcome()

        return invoke

    registry = WirePlumberControlRegistry()
    register_managed_link_controls(
        registry,
        create_link=control("create"),
        remove_link=control("remove"),
    )
    return WirePlumberDriverAdapter(
        lambda: "connection",
        registry=registry,
        snapshot_capture=lambda _connection: runtime,
        contract_checker=lambda _minimum, _maximum: None,
    )


def _create_action(**changes):
    arguments = {
        "desired_link_id": "fanout:left",
        "shape": ManagedLinkShape.FAN_OUT,
        "runtime_generation": 9,
        "output_node_runtime_key": "runtime:9:node:1",
        "output_port_runtime_key": "runtime:9:port:11",
        "input_node_runtime_key": "runtime:9:node:2",
        "input_port_runtime_key": "runtime:9:port:21",
        "passive": True,
        "properties": {"link.group": "front"},
        "intent_scope": "plan:fanout",
        "timeout_seconds": 1.5,
    }
    arguments.update(changes)
    return build_managed_link_action(**arguments)


def test_advanced_link_creation_uses_fixed_ownership_and_current_endpoints() -> None:
    calls = []
    action = _create_action()

    result = _adapter(_runtime(), calls).perform(action)

    assert calls == [
        (
            "create",
            "connection",
            {
                "owner": OPEN_CINEMA_LINK_OWNER,
                "desired_id": "fanout:left",
                "output_node_id": 1,
                "output_port_id": 11,
                "input_node_id": 2,
                "input_port_id": 21,
                "expected_generation": 9,
                "expected_sequence": 4,
                "passive": True,
                "properties": {"link.group": "front"},
                "timeout": 1.5,
                "request_id": action.idempotency_key,
            },
        )
    ]
    assert action.metadata["advancedShape"] == "fan-out"
    assert action.metadata["owner"] == OPEN_CINEMA_LINK_OWNER
    assert action.recovery.inverse.command.operation == "remove-managed-link"
    assert result["status"] == "confirmed"


def test_owned_link_observation_verifies_tags_and_detached_topology() -> None:
    facts = observe_managed_link(_adapter(_runtime(links=(_link(),)), []), "fanout:left")

    prefix = f"managedLink.{OPEN_CINEMA_LINK_OWNER}.fanout:left"
    assert facts[f"{prefix}.present"] is True
    assert facts[f"{prefix}.conflict"] is False
    assert facts[f"{prefix}.tagged"] is True
    assert facts[f"{prefix}.outputNodeRuntimeKey"] == "runtime:9:node:1"
    assert facts[f"{prefix}.inputPortRuntimeKey"] == "runtime:9:port:21"


def test_remove_action_only_accepts_fully_tagged_owned_links_and_keeps_inverse() -> None:
    link = _link()
    calls = []
    action = build_remove_managed_link_action(
        link=link,
        shape="fan-out",
        runtime_generation=9,
        intent_scope="plan:cleanup",
        timeout_seconds=1,
    )

    _adapter(_runtime(links=(link,)), calls).perform(action)

    assert calls[0][0] == "remove"
    assert calls[0][2]["owner"] == OPEN_CINEMA_LINK_OWNER
    assert calls[0][2]["desired_id"] == "fanout:left"
    assert action.recovery.inverse.command.operation == "create-managed-link"
    assert action.recovery.inverse.command.arguments["properties"] == {"link.group": "front"}
    assert action.recovery.inverse.command.arguments["passive"] is True


@pytest.mark.parametrize(
    "link",
    (
        _link(owner=None, desired_id=None),
        replace(
            _link(),
            properties=FrozenDict(
                {
                    "open-cinema.owner": "external.owner",
                    "open-cinema.desired-id": "fanout:left",
                }
            ),
        ),
    ),
)
def test_remove_builder_refuses_unmanaged_or_inconsistently_tagged_link(link) -> None:
    with pytest.raises(PermissionError, match="not owned"):
        build_remove_managed_link_action(
            link=link,
            shape="fan-out",
            runtime_generation=9,
            intent_scope="plan:unsafe-cleanup",
            timeout_seconds=1,
        )


def test_remove_handler_refuses_unmanaged_identity_collision() -> None:
    action = build_remove_managed_link_action(
        link=_link(),
        shape="fan-out",
        runtime_generation=9,
        intent_scope="plan:collision",
        timeout_seconds=1,
    )
    unmanaged = _link(owner="external.owner")

    with pytest.raises(DriverActionError) as caught:
        _adapter(_runtime(links=(unmanaged,)), []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.SAFETY
    assert caught.value.failure.code == "wireplumber:unmanaged-link-removal-refused"


def test_remove_handler_refuses_forged_owner_even_when_operation_is_registered() -> None:
    action = build_remove_managed_link_action(
        link=_link(),
        shape="fan-out",
        runtime_generation=9,
        intent_scope="plan:forged-owner",
        timeout_seconds=1,
    )
    forged = replace(
        action,
        command=DriverCommand(
            "remove-managed-link",
            {
                **action.command.arguments.to_dict(),
                "owner": "external.owner",
            },
        ),
    )

    with pytest.raises(DriverActionError) as caught:
        _adapter(_runtime(links=(_link(),)), []).perform(forged)

    assert caught.value.failure.classification is ActionFailureClassification.SAFETY
    assert caught.value.failure.code == "wireplumber:managed-link-owner-refused"


def test_remove_handler_refuses_inconsistent_native_ownership_tags() -> None:
    action = build_remove_managed_link_action(
        link=_link(),
        shape="fan-out",
        runtime_generation=9,
        intent_scope="plan:invalid-tags",
        timeout_seconds=1,
    )
    invalid = replace(
        _link(),
        properties=FrozenDict(
            {
                "open-cinema.owner": OPEN_CINEMA_LINK_OWNER,
                "open-cinema.desired-id": "another-link",
            }
        ),
    )

    with pytest.raises(DriverActionError) as caught:
        _adapter(_runtime(links=(invalid,)), []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.SAFETY
    assert caught.value.failure.code == "wireplumber:managed-link-tags-invalid"


def test_unclassified_route_cannot_build_an_explicit_link() -> None:
    with pytest.raises(ValueError, match="advanced"):
        _create_action(shape="ordinary")


def test_reserved_link_properties_are_assigned_only_by_adapter() -> None:
    with pytest.raises(ValueError, match="assigned by the adapter"):
        _create_action(properties={"open-cinema.owner": "forged"})


def test_generation_mismatched_runtime_keys_are_rejected_during_planning() -> None:
    with pytest.raises(ValueError, match="generation 9"):
        _create_action(input_port_runtime_key="runtime:8:port:21")


def test_disappeared_port_is_a_stale_precondition() -> None:
    action = _create_action(input_port_runtime_key="runtime:9:port:22")

    with pytest.raises(DriverActionError) as caught:
        _adapter(_runtime(), []).perform(action)

    assert caught.value.failure.classification is ActionFailureClassification.STALE_PRECONDITION
    assert caught.value.failure.code == "wireplumber:managed-link-port-stale"
