from dataclasses import replace

from wyreplumber.runtime import (
    AudioFormatValue,
    AudioPropertiesValue,
    FrozenDict,
    ParameterValue,
    SpaIdValue,
)

from core.orchestration.endpoint_inventory import map_runtime_endpoints
from tests.test_endpoint_inventory_mapping import _snapshot


def _sink_with(parameters, *, latency="256/48000"):
    snapshot = _snapshot()
    nodes = tuple(
        (
            replace(
                node,
                properties=FrozenDict({**node.properties.to_dict(), "node.latency": latency}),
            )
            if node.name == "alsa_output.usb-room"
            else node
        )
        for node in snapshot.nodes
    )
    snapshot = replace(snapshot, nodes=nodes, parameters=tuple(parameters))
    return next(
        candidate
        for candidate in map_runtime_endpoints(snapshot).candidates
        if candidate.name == "alsa_output.usb-room"
    )


def test_formats_volume_mute_layout_and_latency_are_projected() -> None:
    format_value = AudioFormatValue(
        media_type=SpaIdValue("media_type", 1, "audio"),
        media_subtype=SpaIdValue("media_subtype", 1, "raw"),
        sample_format=SpaIdValue("audio_format", 3, "S16LE"),
        rate=48000,
        channels=2,
        positions=(
            SpaIdValue("audio_channel", 1, "FL"),
            SpaIdValue("audio_channel", 2, "FR"),
        ),
    )
    sink = _sink_with(
        (
            ParameterValue("node", 10, "EnumFormat", "r", (format_value,)),
            ParameterValue(
                "node",
                10,
                "Props",
                "rw",
                (
                    AudioPropertiesValue(volume=0.42, mute=True),
                    AudioPropertiesValue(),
                ),
            ),
        )
    )

    projection = sink.projection_document()["audioCapabilities"]

    assert projection["formats"][0]["content"] == "pcm"
    assert projection["formats"][0]["sampleFormat"] == {
        "value": "S16LE",
        "known": True,
        "choices": [],
    }
    assert projection["formats"][0]["rate"]["value"] == 48000
    assert projection["formats"][0]["channels"]["value"] == 2
    assert projection["formats"][0]["positions"]["value"] == ("FL", "FR")
    assert projection["volume"] == {
        "value": 0.42,
        "known": True,
        "readable": True,
        "writable": True,
    }
    assert projection["mute"] == {
        "value": True,
        "known": True,
        "readable": True,
        "writable": True,
    }
    assert round(projection["latency"]["milliseconds"], 3) == 5.333
    assert sink.routes[0].name == "analog-output-speaker"
    assert sink.profiles[0].name == "output:analog-stereo"


def test_unknown_format_and_latency_values_are_preserved_explicitly() -> None:
    unknown = AudioFormatValue(
        media_type=SpaIdValue("media_type", 999),
        media_subtype=SpaIdValue("media_subtype", 888),
        sample_format=SpaIdValue("audio_format", 777),
        rate=12345,
        channels=7,
        positions=(SpaIdValue("audio_channel", 999),) * 7,
    )
    sink = _sink_with(
        (ParameterValue("node", 10, "EnumFormat", "r", (unknown,)),),
        latency="future-latency-value",
    )

    projection = sink.projection_document()["audioCapabilities"]
    observed = projection["formats"][0]
    assert observed["sampleFormat"] == {
        "value": "audio_format:777",
        "known": False,
        "choices": [],
    }
    assert observed["mediaType"]["known"] is False
    assert observed["positions"]["known"] is False
    assert projection["latency"] == {
        "milliseconds": None,
        "raw": "future-latency-value",
        "known": False,
    }


def test_active_route_supplies_volume_and_mute_when_node_props_are_absent() -> None:
    sink = _sink_with(())

    assert sink.volume == 0.6
    assert sink.mute is False
    assert sink.volume_writable is False
    assert sink.mute_writable is False
    assert sink.projection_document()["audioCapabilities"]["volume"] == {
        "value": 0.6,
        "known": True,
        "readable": True,
        "writable": False,
    }


def test_device_props_do_not_hide_readable_writable_node_controls() -> None:
    sink = _sink_with(
        (
            ParameterValue(
                "node",
                10,
                "Props",
                "rw",
                (AudioPropertiesValue(volume=0.42, mute=True),),
            ),
            ParameterValue(
                "device",
                1,
                "Props",
                "rw",
                (AudioPropertiesValue(),),
            ),
        )
    )

    assert sink.volume == 0.42
    assert sink.mute is True
    assert sink.volume_writable is True
    assert sink.mute_writable is True
