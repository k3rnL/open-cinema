from core.orchestration.manual_override_resolution import resolve_manual_overrides
from core.orchestration.resolver_inputs import ResolverOverrideInput

NOW = "2026-08-22T16:00:00+00:00"


def _override(
    override_id,
    scope_type,
    scope_id,
    value,
    *,
    priority=100,
    starts_at="2026-08-22T15:00:00+00:00",
    expires_at="2026-08-22T17:00:00+00:00",
    cancelled_at=None,
    active=True,
):
    return ResolverOverrideInput(
        override_id=override_id,
        scope_type=scope_type,
        scope_id=scope_id,
        value=value,
        priority=priority,
        starts_at=starts_at,
        expires_at=expires_at,
        cancelled_at=cancelled_at,
        active=active,
        reason=f"Reason for {override_id}",
    )


def _resolve(overrides):
    return resolve_manual_overrides(
        overrides,
        evaluated_at=NOW,
        endpoint_ids={"endpoint:headset", "endpoint:speakers"},
        base_parameter_values={"gain": 0.7, "profile": "cinema"},
        base_modes={"scene": "automatic"},
    )


def test_highest_priority_wins_with_latest_start_as_explicit_tie_break() -> None:
    resolution = _resolve(
        (
            _override("low", "endpoint", "primary-output", "endpoint:speakers", priority=10),
            _override(
                "older",
                "endpoint",
                "primary-output",
                "endpoint:speakers",
                priority=100,
                starts_at="2026-08-22T14:00:00+00:00",
            ),
            _override(
                "newer",
                "endpoint",
                "primary-output",
                "endpoint:headset",
                priority=100,
                starts_at="2026-08-22T15:30:00+00:00",
            ),
        )
    )

    assert [winner.override_id for winner in resolution.winners] == ["newer"]
    assert resolution.endpoint_selections == {"primary-output": "endpoint:headset"}
    assert {item.override_id: item.reason for item in resolution.rejected} == {
        "low": "lower_priority",
        "older": "newer_start_tie_break",
    }


def test_not_started_expired_cancelled_and_marked_inactive_are_rejected() -> None:
    resolution = _resolve(
        (
            _override(
                "future",
                "mute",
                "endpoint:speakers",
                True,
                starts_at="2026-08-22T16:01:00+00:00",
            ),
            _override(
                "expired",
                "mute",
                "endpoint:speakers",
                True,
                expires_at=NOW,
            ),
            _override(
                "cancelled",
                "mute",
                "endpoint:speakers",
                True,
                cancelled_at="2026-08-22T15:30:00+00:00",
            ),
            _override("inactive", "mute", "endpoint:speakers", True, active=False),
        )
    )

    assert resolution.winners == ()
    assert {item.override_id: item.reason for item in resolution.rejected} == {
        "future": "not_started",
        "expired": "expired",
        "cancelled": "cancelled",
        "inactive": "inactive",
    }


def test_invalid_endpoint_and_parameter_targets_are_explicit() -> None:
    resolution = _resolve(
        (
            _override("endpoint", "endpoint", "primary-output", "endpoint:missing"),
            _override("parameter", "graph_parameter", "unknown", {"value": 1}),
        )
    )

    assert {item.override_id: item.reason for item in resolution.rejected} == {
        "endpoint": "invalid_endpoint_target",
        "parameter": "invalid_parameter_target",
    }


def test_temporary_values_overlay_but_do_not_mutate_persistent_inputs() -> None:
    base_parameters = {"gain": 0.7, "profile": "cinema"}
    base_modes = {"scene": "automatic"}
    resolution = resolve_manual_overrides(
        (
            _override("gain", "graph_parameter", "gain", {"value": 0.2}),
            _override("scene", "scene", "scene", "night"),
            _override("volume", "volume", "endpoint:speakers", 0.4),
        ),
        evaluated_at=NOW,
        endpoint_ids={"endpoint:speakers"},
        base_parameter_values=base_parameters,
        base_modes=base_modes,
    )

    assert resolution.parameter_values == {"gain": 0.2, "profile": "cinema"}
    assert resolution.modes == {"scene": "night"}
    assert resolution.controls == {"volume.endpoint:speakers": 0.4}
    assert resolution.provenance["parameter.gain"]["source"] == "temporary_override"
    assert resolution.provenance["parameter.profile"] == {"source": "persistent_activation"}
    assert base_parameters == {"gain": 0.7, "profile": "cinema"}
    assert base_modes == {"scene": "automatic"}


def test_expiry_restores_persistent_value_without_editing_it() -> None:
    override = _override(
        "gain",
        "graph_parameter",
        "gain",
        {"value": 0.2},
        expires_at="2026-08-22T16:30:00+00:00",
    )
    active = resolve_manual_overrides(
        (override,),
        evaluated_at="2026-08-22T16:29:59+00:00",
        endpoint_ids=(),
        base_parameter_values={"gain": 0.7},
        base_modes={},
    )
    expired = resolve_manual_overrides(
        (override,),
        evaluated_at="2026-08-22T16:30:00+00:00",
        endpoint_ids=(),
        base_parameter_values={"gain": 0.7},
        base_modes={},
    )

    assert active.parameter_values["gain"] == 0.2
    assert expired.parameter_values["gain"] == 0.7
    assert expired.rejected[0].reason == "expired"


def test_endpoint_scene_volume_and_mute_overrides_win_then_revert_as_a_set() -> None:
    overrides = (
        _override(
            "speaker-fallback",
            "endpoint",
            "primary-output",
            "endpoint:speakers",
            priority=10,
        ),
        _override(
            "headset",
            "endpoint",
            "primary-output",
            "endpoint:headset",
            priority=200,
        ),
        _override("night", "scene", "scene", "night", priority=200),
        _override("quiet", "volume", "endpoint:headset", 0.25, priority=200),
        _override("mute-room", "mute", "endpoint:speakers", True, priority=200),
    )
    active = _resolve(overrides)
    document = active.to_document()

    assert active.endpoint_selections == {"primary-output": "endpoint:headset"}
    assert active.modes == {"scene": "night"}
    assert active.controls == {
        "mute.endpoint:speakers": True,
        "volume.endpoint:headset": 0.25,
    }
    assert {winner["scopeType"] for winner in document["winners"]} == {
        "endpoint",
        "scene",
        "volume",
        "mute",
    }
    assert all(winner["expiresAt"] == "2026-08-22T17:00:00+00:00" for winner in document["winners"])
    assert active.provenance["endpoint.primary-output"]["overrideId"] == "headset"
    assert {item.override_id: item.reason for item in active.rejected} == {
        "speaker-fallback": "lower_priority"
    }

    cancelled_or_expired = tuple(
        ResolverOverrideInput(
            override_id=item.override_id,
            scope_type=item.scope_type,
            scope_id=item.scope_id,
            value=item.value,
            priority=item.priority,
            starts_at=item.starts_at,
            expires_at="2026-08-22T16:30:00+00:00",
            cancelled_at=("2026-08-22T16:15:00+00:00" if item.override_id == "headset" else None),
            active=item.active,
            reason=item.reason,
        )
        for item in overrides
    )
    reverted = resolve_manual_overrides(
        cancelled_or_expired,
        evaluated_at="2026-08-22T16:30:00+00:00",
        endpoint_ids={"endpoint:headset", "endpoint:speakers"},
        base_parameter_values={"gain": 0.7},
        base_modes={"scene": "automatic"},
    )

    assert reverted.winners == ()
    assert reverted.endpoint_selections == {}
    assert reverted.modes == {"scene": "automatic"}
    assert reverted.controls == {}
    assert {item.override_id: item.reason for item in reverted.rejected} == {
        "headset": "cancelled",
        "mute-room": "expired",
        "night": "expired",
        "quiet": "expired",
        "speaker-fallback": "expired",
    }
