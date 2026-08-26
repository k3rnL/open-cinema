from core.orchestration.node_catalogue import core_node_type_registry
from core.orchestration.signal_contracts import (
    AudioContent,
    ChannelLayout,
    LatencyRange,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from core.orchestration.signal_descriptors import (
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalDescriptor,
    SignalObservationSource,
    SignalTransportDescriptor,
)
from core.orchestration.signal_negotiation import (
    negotiate_port_contracts,
    negotiate_signal_contracts,
    propagate_graph_signal_contracts,
    signal_contract_from_descriptor,
)


def _signal(**kwargs):
    return SignalContract(media_kind=MediaKind.AUDIO, **kwargs)


def test_negotiation_narrows_every_audio_dimension_and_latency() -> None:
    source = _signal(
        content="pcm",
        sample_formats=("S16LE", "S32LE"),
        rates=(48_000, 96_000),
        layouts=(ChannelLayout(2), ChannelLayout(6)),
        latency=LatencyRange(2, 50),
        capabilities=("clock-sync", "mute"),
    )
    target = _signal(
        content="any",
        sample_formats=("S16LE",),
        rates=(48_000,),
        layouts=(ChannelLayout(2),),
        latency=LatencyRange(5, 20),
        capabilities=("clock-sync",),
        required_capabilities=("mute",),
    )

    result = negotiate_signal_contracts(source, target)

    assert result.compatible
    assert result.contract == _signal(
        content="pcm",
        sample_formats=("S16LE",),
        rates=(48_000,),
        layouts=(ChannelLayout(2),),
        latency=LatencyRange(5, 20),
        capabilities=("clock-sync",),
        required_capabilities=("mute",),
    )


def test_incompatible_negotiation_preserves_every_reason() -> None:
    result = negotiate_port_contracts(
        PortContract(
            "source",
            PortDirection.INPUT,
            _signal(
                content="encoded",
                codecs=("ac3",),
                sample_formats=("S16LE",),
                rates=(48_000,),
                layouts=(ChannelLayout(2),),
                latency=LatencyRange(100, 200),
                required_capabilities=("passthrough",),
            ),
        ),
        PortContract(
            "target",
            PortDirection.OUTPUT,
            SignalContract(
                media_kind="control",
                capabilities=("volume",),
                required_capabilities=("mute",),
            ),
        ),
    )

    assert result.contract is None
    assert set(result.reasons) == {
        "source_direction",
        "target_direction",
        "media_kind",
        "source_capability",
        "target_capability",
    }


def test_observed_descriptor_can_negotiate_content_or_actual_decoded_output() -> None:
    descriptor = SignalDescriptor(
        version=1,
        transport=SignalTransportDescriptor(
            "iec61937",
            AudioFormatDescriptor("S16LE", 48_000, ChannelLayout(2)),
        ),
        content=SignalContentDescriptor("encoded", "ac3"),
        decoded_output=AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(6)),
        confidence=0.99,
        source=SignalObservationSource("decoder", "decoder:tv", 7),
        observed_at="2026-08-22T16:00:00Z",
    )

    encoded = signal_contract_from_descriptor(descriptor)
    decoded = signal_contract_from_descriptor(descriptor, decoded_output=True)

    assert encoded.content is AudioContent.ENCODED
    assert encoded.codecs == ("ac3",)
    assert encoded.sample_formats == ("S16LE",)
    assert decoded.content is AudioContent.PCM
    assert decoded.codecs == ()
    assert decoded.layouts == (ChannelLayout(6),)


def test_graph_propagation_carries_exact_format_through_wildcard_processor() -> None:
    document = {
        "nodes": [
            {"id": "source", "type": "core.endpoint-reference", "version": 1},
            {"id": "fan", "type": "core.fan-out", "version": 1},
            {"id": "sink", "type": "core.endpoint-reference", "version": 1},
        ],
        "edges": [
            {
                "id": "first",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "fan", "port": "input"},
            },
            {
                "id": "second",
                "from": {"node": "fan", "port": "outputs"},
                "to": {"node": "sink", "port": "input"},
            },
        ],
    }
    exact = _signal(
        content="pcm",
        sample_formats=("S16LE",),
        rates=(48_000,),
        layouts=(ChannelLayout(2),),
    )

    result = propagate_graph_signal_contracts(
        document,
        registry=core_node_type_registry(),
        observed_outputs={("source", "output"): exact},
    )

    assert result.compatible
    assert result.port_contracts.to_dict()["fan.outputs"] == exact.to_document()
    assert result.edge_contracts.to_dict()["second"]["negotiated"] == (exact.to_document())


def test_graph_propagation_reports_selected_edge_processor_constraint_failure() -> None:
    document = {
        "nodes": [
            {"id": "source", "type": "core.endpoint-reference", "version": 1},
            {"id": "mixer", "type": "core.mixer-intent", "version": 1},
        ],
        "edges": [
            {
                "id": "encoded-to-pcm",
                "from": {"node": "source", "port": "output"},
                "to": {"node": "mixer", "port": "inputs"},
            }
        ],
    }
    encoded = _signal(content="encoded", codecs=("ac3",))

    result = propagate_graph_signal_contracts(
        document,
        registry=core_node_type_registry(),
        observed_outputs={("source", "output"): encoded},
    )

    assert not result.compatible
    assert result.issues[0].edge_id == "encoded-to-pcm"
    assert result.issues[0].reasons == ("content",)
