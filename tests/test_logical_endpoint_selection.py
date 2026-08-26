from core.orchestration.logical_endpoint_selection import (
    LogicalEndpointSelector,
    LogicalEndpointSummary,
    parse_logical_endpoint_selector,
    select_logical_endpoints,
)


def _endpoint(
    endpoint_id: str,
    name: str,
    *,
    direction: str = "output",
    tags: tuple[str, ...] = ("preferred-output",),
    groups: tuple[str, ...],
) -> LogicalEndpointSummary:
    return LogicalEndpointSummary(
        endpoint_id=endpoint_id,
        name=name,
        direction=direction,
        tags=tags,
        groups=groups,
        update_version=1,
    )


def test_tag_and_group_selector_is_parsed_as_safe_versioned_data() -> None:
    validation = parse_logical_endpoint_selector(
        {
            "version": 1,
            "direction": "output",
            "requiredTags": ["preferred-output"],
            "orderedGroups": ["headsets", "room-speakers"],
        }
    )

    assert validation.valid
    assert validation.selector == LogicalEndpointSelector(
        direction="output",
        required_tags=("preferred-output",),
        ordered_groups=("headsets", "room-speakers"),
    )


def test_selector_rejects_empty_duplicate_and_unknown_taxonomy() -> None:
    empty = parse_logical_endpoint_selector({"version": 1})
    duplicate = parse_logical_endpoint_selector(
        {"version": 1, "orderedGroups": ["headsets", "headsets"]}
    )
    unknown = parse_logical_endpoint_selector(
        {"version": 1, "requiredTags": ["output"], "runtimeId": 42}
    )

    assert {issue.code for issue in empty.issues} == {"empty_selector"}
    assert "duplicate_value" in {issue.code for issue in duplicate.issues}
    assert "unknown_fields" in {issue.code for issue in unknown.issues}


def test_ordered_groups_drive_selection_before_stable_tie_breaks() -> None:
    selector = LogicalEndpointSelector(
        direction="output",
        required_tags=("preferred-output",),
        ordered_groups=("headsets", "room-speakers"),
    )
    endpoints = (
        _endpoint("speakers", "Main speakers", groups=("room-speakers",)),
        _endpoint("headset-b", "Bluetooth headset", groups=("preferred", "headsets")),
        _endpoint("headset-a", "USB headset", groups=("headsets", "preferred")),
    )

    result = select_logical_endpoints(selector, reversed(endpoints))

    assert [endpoint.endpoint_id for endpoint in result.selected] == [
        "headset-a",
        "headset-b",
        "speakers",
    ]
    assert result.diagnostics[0].accepted_evidence == (
        "direction:output",
        "tag:preferred-output",
        "group:headsets",
    )


def test_selection_filters_runtime_ineligible_and_tag_mismatches_with_reasons() -> None:
    selector = LogicalEndpointSelector(
        direction="output",
        required_tags=("preferred-output",),
        ordered_groups=("headsets", "room-speakers"),
    )
    endpoints = (
        _endpoint("headset", "Headset", groups=("headsets",)),
        _endpoint("speakers", "Speakers", groups=("room-speakers",)),
        _endpoint(
            "monitor",
            "Monitor",
            tags=("secondary-output",),
            groups=("room-speakers",),
        ),
    )

    result = select_logical_endpoints(
        selector,
        endpoints,
        eligible_endpoint_ids={"speakers", "monitor"},
    )

    assert [endpoint.endpoint_id for endpoint in result.selected] == ["speakers"]
    by_id = {item.endpoint_id: item for item in result.diagnostics}
    assert "runtime:not-eligible" in by_id["headset"].rejected_evidence
    assert "tag:preferred-output" in by_id["monitor"].rejected_evidence


def test_equivalent_input_order_produces_identical_selection() -> None:
    selector = LogicalEndpointSelector(
        direction=None,
        required_tags=("programme",),
        ordered_groups=("bluetooth-sources", "tv-inputs"),
    )
    endpoints = (
        _endpoint(
            "tv",
            "TV",
            direction="input",
            tags=("programme",),
            groups=("tv-inputs",),
        ),
        _endpoint(
            "phone",
            "Phone",
            direction="input",
            tags=("programme",),
            groups=("bluetooth-sources",),
        ),
    )

    forward = select_logical_endpoints(selector, endpoints)
    backward = select_logical_endpoints(selector, reversed(endpoints))

    assert forward == backward
