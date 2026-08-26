from dataclasses import replace

import pytest

from core.orchestration.adaptive_decoder import (
    AdaptiveDecoderChoice,
    AdaptiveDecoderDecisionStatus,
    AdaptiveDecoderPolicy,
    adaptive_decoder_node_type_definition,
    resolve_adaptive_decoder_choice,
)
from core.orchestration.signal_contracts import AudioContent, ChannelLayout
from core.orchestration.signal_descriptors import (
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalDescriptor,
    SignalObservationSource,
    SignalTransportDescriptor,
)


def _descriptor(content="encoded", codec="ac3", confidence=0.99, decoded=True):
    return SignalDescriptor(
        version=1,
        transport=SignalTransportDescriptor(
            "iec61937" if content == "encoded" else "pcm",
            AudioFormatDescriptor("S16LE", 48_000, ChannelLayout(2)),
        ),
        content=SignalContentDescriptor(content, codec if content == "encoded" else None),
        decoded_output=(
            AudioFormatDescriptor("FLOAT32LE", 48_000, ChannelLayout(6)) if decoded else None
        ),
        confidence=confidence,
        source=SignalObservationSource("decoder", "decoder:tv", 1),
        observed_at="2026-08-22T16:00:00Z",
    )


def _policy(**changes):
    values = {
        "pcm_behavior": "bypass",
        "encoded_behavior": "decode",
        "unsupported_behavior": "error",
        "supported_codecs": ("ac3", "eac3", "dts"),
        "minimum_confidence": 0.9,
        **changes,
    }
    return AdaptiveDecoderPolicy(**values)


def test_node_schema_requires_every_explicit_safety_behavior() -> None:
    definition = adaptive_decoder_node_type_definition()
    canonical = {
        "pcmBehavior": "bypass",
        "encodedBehavior": "decode",
        "unsupportedBehavior": "error",
        "minimumConfidence": 0.9,
        "detectionWindowMs": 250,
        "confidenceHysteresis": 0.05,
        "debounceMs": 50,
        "stableDurationMs": 300,
        "cooldownMs": 1_000,
    }

    assert definition.validate_configuration(canonical) == ()
    parsed = AdaptiveDecoderPolicy.from_document(canonical)
    assert parsed.stability_policy.to_document() == {
        key: value
        for key, value in canonical.items()
        if key
        in {
            "minimumConfidence",
            "detectionWindowMs",
            "confidenceHysteresis",
            "debounceMs",
            "stableDurationMs",
            "cooldownMs",
        }
    }
    assert definition.validate_configuration({"pcmBehavior": "bypass"})


@pytest.mark.parametrize(
    ("behavior", "choice", "status"),
    (
        ("bypass", AdaptiveDecoderChoice.PCM_BYPASS, "resolved"),
        ("silence", AdaptiveDecoderChoice.SILENCE, "resolved"),
        ("error", AdaptiveDecoderChoice.ERROR, "error"),
    ),
)
def test_plain_pcm_uses_only_the_explicit_pcm_behavior(behavior, choice, status) -> None:
    decision = resolve_adaptive_decoder_choice(
        _descriptor(content="pcm", codec=None, decoded=False),
        _policy(pcm_behavior=behavior),
    )

    assert decision.choice is choice
    assert decision.status.value == status
    if choice is AdaptiveDecoderChoice.PCM_BYPASS:
        assert decision.output_contract.content is AudioContent.PCM


@pytest.mark.parametrize(
    ("behavior", "choice", "status"),
    (
        ("decode", AdaptiveDecoderChoice.DECODE, "resolved"),
        ("passthrough", AdaptiveDecoderChoice.PASSTHROUGH, "resolved"),
        ("silence", AdaptiveDecoderChoice.SILENCE, "resolved"),
        ("error", AdaptiveDecoderChoice.ERROR, "error"),
    ),
)
def test_supported_encoded_content_uses_only_encoded_behavior(
    behavior,
    choice,
    status,
) -> None:
    decision = resolve_adaptive_decoder_choice(
        _descriptor(),
        _policy(encoded_behavior=behavior),
    )

    assert decision.choice is choice
    assert decision.status.value == status
    if choice is AdaptiveDecoderChoice.DECODE:
        assert decision.output_contract.content is AudioContent.PCM
        assert decision.output_contract.layouts == (ChannelLayout(6),)
    if choice is AdaptiveDecoderChoice.PASSTHROUGH:
        assert decision.output_contract.content is AudioContent.ENCODED
        assert decision.output_contract.codecs == ("ac3",)


@pytest.mark.parametrize(
    ("behavior", "choice"),
    (
        ("passthrough", AdaptiveDecoderChoice.PASSTHROUGH),
        ("silence", AdaptiveDecoderChoice.SILENCE),
        ("error", AdaptiveDecoderChoice.ERROR),
    ),
)
def test_unsupported_codec_never_falls_into_decode(behavior, choice) -> None:
    decision = resolve_adaptive_decoder_choice(
        _descriptor(codec="truehd"),
        _policy(unsupported_behavior=behavior),
    )

    assert decision.choice is choice
    assert decision.choice is not AdaptiveDecoderChoice.DECODE
    assert decision.reason.startswith("unsupported_codec")


def test_decode_waits_for_decoder_and_actual_output_without_guessing_format() -> None:
    descriptor = _descriptor(decoded=False)

    unavailable = resolve_adaptive_decoder_choice(
        descriptor,
        _policy(),
        decoder_available=False,
    )
    detecting_output = resolve_adaptive_decoder_choice(descriptor, _policy())

    assert unavailable.choice is AdaptiveDecoderChoice.DECODE
    assert unavailable.status is AdaptiveDecoderDecisionStatus.WAITING
    assert unavailable.output_contract is None
    assert detecting_output.choice is AdaptiveDecoderChoice.DECODE
    assert detecting_output.status is AdaptiveDecoderDecisionStatus.WAITING
    assert detecting_output.output_contract.content is AudioContent.PCM
    assert detecting_output.output_contract.layouts == ()


def test_pcm_and_decoded_content_resolve_to_the_same_emitted_working_bus() -> None:
    emitted = AudioFormatDescriptor(
        "FLOAT32LE",
        48_000,
        ChannelLayout(8, ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")),
    )

    pcm = resolve_adaptive_decoder_choice(
        _descriptor(content="pcm", codec=None, decoded=False),
        _policy(),
        emitted_output=emitted,
    )
    encoded = resolve_adaptive_decoder_choice(
        _descriptor(),
        _policy(),
        emitted_output=emitted,
    )

    assert pcm.output_contract == encoded.output_contract
    assert pcm.output_contract.layouts == (emitted.layout,)
    assert pcm.output_contract.sample_formats == ("FLOAT32LE",)
    assert pcm.output_contract.rates == (48_000,)


def test_unknown_or_low_confidence_input_waits_without_selecting_audible_output() -> None:
    unknown = replace(
        _descriptor(decoded=False),
        content=SignalContentDescriptor("unknown"),
    )
    low_confidence = _descriptor(confidence=0.89)

    for descriptor in (unknown, low_confidence):
        decision = resolve_adaptive_decoder_choice(descriptor, _policy())
        assert decision.choice is AdaptiveDecoderChoice.WAITING
        assert decision.status is AdaptiveDecoderDecisionStatus.WAITING
        assert decision.output_contract is None
