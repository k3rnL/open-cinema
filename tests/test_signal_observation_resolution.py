from core.orchestration.signal_contracts import ChannelLayout
from core.orchestration.signal_descriptors import (
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalDescriptor,
    SignalObservationSource,
    SignalTransportDescriptor,
)
from core.orchestration.signal_observation_resolution import (
    DecodedOutputSource,
    SignalObservationHealth,
    resolve_decoded_output_observation,
)


def _descriptor(decoded_output):
    return SignalDescriptor(
        version=1,
        transport=SignalTransportDescriptor(
            "iec61937",
            AudioFormatDescriptor("S16LE", 48_000, ChannelLayout(2)),
        ),
        content=SignalContentDescriptor("encoded", "ac3"),
        decoded_output=decoded_output,
        confidence=0.99,
        source=SignalObservationSource("decoder", "decoder:tv", 4),
        observed_at="2026-08-22T16:00:00Z",
    )


def test_observed_stereo_frames_override_six_channel_codec_assumption() -> None:
    stereo = AudioFormatDescriptor(
        "FLOAT32LE",
        48_000,
        ChannelLayout(2, ("FL", "FR")),
    )
    codec_maximum = AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(6))

    resolution = resolve_decoded_output_observation(
        _descriptor(stereo),
        codec_maximum_assumption=codec_maximum,
    )

    assert resolution.format == stereo
    assert resolution.source is DecodedOutputSource.DECODER_OBSERVED
    assert resolution.health is SignalObservationHealth.HEALTHY
    assert resolution.reason == "decoded_frame_output_is_authoritative"


def test_decoder_pipewire_disagreement_is_degraded_but_decoder_stays_authoritative() -> None:
    decoder = AudioFormatDescriptor(
        "FLOAT32LE",
        48_000,
        ChannelLayout(2, ("FL", "FR")),
    )
    pipewire = AudioFormatDescriptor(
        "S16LE",
        96_000,
        ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR")),
    )

    resolution = resolve_decoded_output_observation(
        _descriptor(decoder),
        pipewire_output=pipewire,
    )

    assert resolution.format == decoder
    assert resolution.source is DecodedOutputSource.DECODER_OBSERVED
    assert resolution.health is SignalObservationHealth.DEGRADED
    assert resolution.disagreements == ("sample_format", "rate", "channels")
    assert resolution.to_processor_facts("decoder:tv").to_dict() == {
        "processor.decoder:tv.health": "degraded",
        "processor.decoder:tv.ready": True,
        "processor.decoder:tv.outputSource": "decoder-observed",
        "processor.decoder:tv.observationDisagreements": [
            "sample_format",
            "rate",
            "channels",
        ],
    }


def test_partial_pipewire_observation_only_compares_known_fields() -> None:
    decoder = AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(2))
    pipewire = AudioFormatDescriptor(rate=48_000)

    resolution = resolve_decoded_output_observation(
        _descriptor(decoder),
        pipewire_output=pipewire,
    )

    assert resolution.health is SignalObservationHealth.HEALTHY
    assert resolution.disagreements == ()


def test_pipewire_or_codec_fallbacks_are_never_reported_as_healthy_actual_output() -> None:
    pipewire = AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(2))
    assumption = AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(6))

    observed = resolve_decoded_output_observation(
        _descriptor(None),
        pipewire_output=pipewire,
        codec_maximum_assumption=assumption,
    )
    assumed = resolve_decoded_output_observation(
        _descriptor(None),
        codec_maximum_assumption=assumption,
    )
    unavailable = resolve_decoded_output_observation(_descriptor(None))

    assert observed.source is DecodedOutputSource.PIPEWIRE_OBSERVED
    assert observed.health is SignalObservationHealth.DEGRADED
    assert assumed.source is DecodedOutputSource.CODEC_ASSUMPTION
    assert assumed.health is SignalObservationHealth.UNKNOWN
    assert unavailable.format is None
    assert unavailable.source is DecodedOutputSource.UNAVAILABLE
