import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from core.orchestration.signal_contracts import ChannelLayout
from core.orchestration.signal_descriptors import (
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalContentKind,
    SignalDescriptor,
    SignalObservationSource,
    SignalTransportDescriptor,
    SignalTransportKind,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "audio-signal-descriptor-v1.schema.json"
)


def _ac3_descriptor() -> SignalDescriptor:
    return SignalDescriptor(
        version=1,
        transport=SignalTransportDescriptor(
            kind=SignalTransportKind.IEC61937,
            format=AudioFormatDescriptor(
                sample_format="S16LE",
                rate=48_000,
                layout=ChannelLayout(2, ("FL", "FR")),
            ),
        ),
        content=SignalContentDescriptor(
            kind=SignalContentKind.ENCODED,
            codec="ac3",
        ),
        decoded_output=AudioFormatDescriptor(
            sample_format="FLOAT32LE",
            rate=48_000,
            layout=ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR")),
        ),
        confidence=0.98,
        source=SignalObservationSource(
            kind="decoder",
            source_id="decoder:tv",
            sequence=42,
        ),
        observed_at="2026-08-22T18:00:00+02:00",
    )


def test_ac3_transport_content_and_actual_decoded_output_are_separate() -> None:
    descriptor = _ac3_descriptor()
    document = descriptor.to_document()

    assert document["transport"] == {
        "kind": "iec61937",
        "format": {
            "sampleFormat": "S16LE",
            "rate": 48_000,
            "layout": {"channels": 2, "positions": ["FL", "FR"]},
        },
    }
    assert document["content"] == {"kind": "encoded", "codec": "ac3"}
    assert document["decodedOutput"]["layout"]["channels"] == 6
    assert document["observedAt"] == "2026-08-22T16:00:00Z"
    assert SignalDescriptor.from_document(document) == descriptor


def test_plain_pcm_does_not_invent_an_encoded_codec_or_decoded_output() -> None:
    descriptor = SignalDescriptor(
        version=1,
        transport=SignalTransportDescriptor(
            kind="pcm",
            format=AudioFormatDescriptor(
                sample_format="s16le",
                rate=48_000,
                layout=ChannelLayout(2),
            ),
        ),
        content=SignalContentDescriptor(kind="pcm"),
        decoded_output=None,
        confidence=1,
        source=SignalObservationSource(
            kind="wireplumber",
            source_id="runtime:3:node:130",
        ),
        observed_at="2026-08-22T16:00:00Z",
    )

    document = descriptor.to_document()

    assert document["content"] == {"kind": "pcm"}
    assert document["decodedOutput"] is None
    assert document["confidence"] == 1.0


def test_descriptor_projects_distinct_typed_facts() -> None:
    facts = _ac3_descriptor().to_facts("tv")

    assert facts["signal.tv.transport"] == "iec61937"
    assert facts["signal.tv.transport.channels"] == 2
    assert facts["signal.tv.content.kind"] == "encoded"
    assert facts["signal.tv.content.codec"] == "ac3"
    assert facts["signal.tv.decoded.channels"] == 6
    assert facts["signal.tv.source.id"] == "decoder:tv"


def test_canonical_document_matches_the_published_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert list(validator.iter_errors(_ac3_descriptor().to_document())) == []


@pytest.mark.parametrize(
    "factory",
    (
        lambda: SignalContentDescriptor(kind="encoded"),
        lambda: SignalContentDescriptor(kind="pcm", codec="ac3"),
        lambda: SignalContentDescriptor(kind="encoded", codec="AC 3"),
        lambda: SignalDescriptor(
            version=2,
            transport=SignalTransportDescriptor("unknown", AudioFormatDescriptor()),
            content=SignalContentDescriptor("unknown"),
            decoded_output=None,
            confidence=0.5,
            source=SignalObservationSource("replay", "fixture"),
            observed_at="2026-08-22T16:00:00Z",
        ),
        lambda: SignalDescriptor(
            version=1,
            transport=SignalTransportDescriptor("unknown", AudioFormatDescriptor()),
            content=SignalContentDescriptor("unknown"),
            decoded_output=None,
            confidence=1.01,
            source=SignalObservationSource("replay", "fixture"),
            observed_at="2026-08-22T16:00:00Z",
        ),
        lambda: SignalDescriptor(
            version=1,
            transport=SignalTransportDescriptor("unknown", AudioFormatDescriptor()),
            content=SignalContentDescriptor("unknown"),
            decoded_output=None,
            confidence=0,
            source=SignalObservationSource("replay", "fixture"),
            observed_at="2026-08-22 16:00:00",
        ),
    ),
)
def test_invalid_or_conflated_signal_descriptors_are_rejected(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_unknown_fields_are_rejected_on_deserialization() -> None:
    document = _ac3_descriptor().to_document()
    document["transport"]["codec"] = "ac3"

    with pytest.raises(ValueError, match="unknown transport fields"):
        SignalDescriptor.from_document(document)
