from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .signal_contracts import ChannelLayout

SIGNAL_DESCRIPTOR_SCHEMA_VERSION = 1
_CODEC = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")


class SignalTransportKind(StrEnum):
    UNKNOWN = "unknown"
    PCM = "pcm"
    IEC61937 = "iec61937"


class SignalContentKind(StrEnum):
    UNKNOWN = "unknown"
    PCM = "pcm"
    ENCODED = "encoded"
    SILENCE = "silence"


class SignalObservationSourceKind(StrEnum):
    WIREPLUMBER = "wireplumber"
    DECODER = "decoder"
    PROCESSOR = "processor"
    REPLAY = "replay"


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_nonempty(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, name)


def _timestamp(value: object) -> str:
    raw = _nonempty(value, "observed_at")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unknown_fields(document: Mapping[str, object], known: set[str], name: str) -> None:
    unknown = set(document) - known
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(sorted(unknown))}")


@dataclass(frozen=True, slots=True)
class AudioFormatDescriptor:
    """One observed PCM carrier or processor-output format."""

    sample_format: str | None = None
    rate: int | None = None
    layout: ChannelLayout | None = None

    def __post_init__(self) -> None:
        sample_format = _optional_nonempty(self.sample_format, "sample_format")
        if sample_format is not None:
            sample_format = sample_format.upper()
        object.__setattr__(self, "sample_format", sample_format)
        if self.rate is not None and (
            isinstance(self.rate, bool) or not isinstance(self.rate, int) or self.rate < 1
        ):
            raise ValueError("rate must be a positive integer or null")
        if self.layout is not None and not isinstance(self.layout, ChannelLayout):
            raise TypeError("layout must be a ChannelLayout or null")

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {}
        if self.sample_format is not None:
            document["sampleFormat"] = self.sample_format
        if self.rate is not None:
            document["rate"] = self.rate
        if self.layout is not None:
            document["layout"] = self.layout.to_document()
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> AudioFormatDescriptor:
        if not isinstance(document, Mapping):
            raise ValueError("audio format must be an object")
        _unknown_fields(document, {"sampleFormat", "rate", "layout"}, "audio-format")
        layout = document.get("layout")
        return cls(
            sample_format=document.get("sampleFormat"),
            rate=document.get("rate"),
            layout=(ChannelLayout.from_document(layout) if layout is not None else None),
        )


@dataclass(frozen=True, slots=True)
class SignalTransportDescriptor:
    kind: SignalTransportKind
    format: AudioFormatDescriptor

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SignalTransportKind(self.kind))
        if not isinstance(self.format, AudioFormatDescriptor):
            raise TypeError("transport format must be an AudioFormatDescriptor")

    def to_document(self) -> dict[str, object]:
        return {"kind": self.kind.value, "format": self.format.to_document()}

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> SignalTransportDescriptor:
        if not isinstance(document, Mapping):
            raise ValueError("transport must be an object")
        _unknown_fields(document, {"kind", "format"}, "transport")
        return cls(
            kind=document.get("kind"),
            format=AudioFormatDescriptor.from_document(document.get("format")),
        )


@dataclass(frozen=True, slots=True)
class SignalContentDescriptor:
    kind: SignalContentKind
    codec: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SignalContentKind(self.kind))
        codec = _optional_nonempty(self.codec, "codec")
        if codec is not None:
            codec = codec.lower()
            if _CODEC.fullmatch(codec) is None:
                raise ValueError("codec must be a stable lowercase token")
        if self.kind is SignalContentKind.ENCODED and codec is None:
            raise ValueError("encoded content requires a codec")
        if self.kind is not SignalContentKind.ENCODED and codec is not None:
            raise ValueError("only encoded content may declare a codec")
        object.__setattr__(self, "codec", codec)

    def to_document(self) -> dict[str, object]:
        document = {"kind": self.kind.value}
        if self.codec is not None:
            document["codec"] = self.codec
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> SignalContentDescriptor:
        if not isinstance(document, Mapping):
            raise ValueError("content must be an object")
        _unknown_fields(document, {"kind", "codec"}, "content")
        return cls(kind=document.get("kind"), codec=document.get("codec"))


@dataclass(frozen=True, slots=True)
class SignalObservationSource:
    kind: SignalObservationSourceKind
    source_id: str
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SignalObservationSourceKind(self.kind))
        _nonempty(self.source_id, "source_id")
        if self.sequence is not None and (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("source sequence must be non-negative or null")

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "kind": self.kind.value,
            "id": self.source_id,
        }
        if self.sequence is not None:
            document["sequence"] = self.sequence
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> SignalObservationSource:
        if not isinstance(document, Mapping):
            raise ValueError("source must be an object")
        _unknown_fields(document, {"kind", "id", "sequence"}, "source")
        return cls(
            kind=document.get("kind"),
            source_id=document.get("id"),
            sequence=document.get("sequence"),
        )


@dataclass(frozen=True, slots=True)
class SignalDescriptor:
    version: int
    transport: SignalTransportDescriptor
    content: SignalContentDescriptor
    decoded_output: AudioFormatDescriptor | None
    confidence: float
    source: SignalObservationSource
    observed_at: str

    def __post_init__(self) -> None:
        if self.version != SIGNAL_DESCRIPTOR_SCHEMA_VERSION:
            raise ValueError(
                f"signal descriptor version must be {SIGNAL_DESCRIPTOR_SCHEMA_VERSION}"
            )
        if not isinstance(self.transport, SignalTransportDescriptor):
            raise TypeError("transport must be a SignalTransportDescriptor")
        if not isinstance(self.content, SignalContentDescriptor):
            raise TypeError("content must be a SignalContentDescriptor")
        if self.decoded_output is not None and not isinstance(
            self.decoded_output, AudioFormatDescriptor
        ):
            raise TypeError("decoded_output must be an AudioFormatDescriptor or null")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be a number")
        confidence = float(self.confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        if not isinstance(self.source, SignalObservationSource):
            raise TypeError("source must be a SignalObservationSource")
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at))

    def to_document(self) -> dict[str, object]:
        return {
            "version": self.version,
            "transport": self.transport.to_document(),
            "content": self.content.to_document(),
            "decodedOutput": (
                self.decoded_output.to_document() if self.decoded_output is not None else None
            ),
            "confidence": self.confidence,
            "source": self.source.to_document(),
            "observedAt": self.observed_at,
        }

    def to_facts(self, signal_id: str) -> dict[str, object]:
        """Project stable descriptor facts without flattening transport into content."""

        prefix = f"signal.{_nonempty(signal_id, 'signal_id')}"
        facts: dict[str, object] = {
            f"{prefix}.transport": self.transport.kind.value,
            f"{prefix}.content.kind": self.content.kind.value,
            f"{prefix}.content.codec": self.content.codec,
            f"{prefix}.confidence": self.confidence,
            f"{prefix}.observedAt": self.observed_at,
            f"{prefix}.source.kind": self.source.kind.value,
            f"{prefix}.source.id": self.source.source_id,
        }
        transport_format = self.transport.format
        facts.update(
            {
                f"{prefix}.transport.sampleFormat": transport_format.sample_format,
                f"{prefix}.transport.rate": transport_format.rate,
                f"{prefix}.transport.channels": (
                    transport_format.layout.channels
                    if transport_format.layout is not None
                    else None
                ),
            }
        )
        if self.decoded_output is not None:
            facts.update(
                {
                    f"{prefix}.decoded.sampleFormat": self.decoded_output.sample_format,
                    f"{prefix}.decoded.rate": self.decoded_output.rate,
                    f"{prefix}.decoded.channels": (
                        self.decoded_output.layout.channels
                        if self.decoded_output.layout is not None
                        else None
                    ),
                    f"{prefix}.decoded.layout": (
                        self.decoded_output.layout.to_document()
                        if self.decoded_output.layout is not None
                        else None
                    ),
                }
            )
        return facts

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> SignalDescriptor:
        if not isinstance(document, Mapping):
            raise ValueError("signal descriptor must be an object")
        known = {
            "version",
            "transport",
            "content",
            "decodedOutput",
            "confidence",
            "source",
            "observedAt",
        }
        _unknown_fields(document, known, "signal-descriptor")
        decoded_output = document.get("decodedOutput")
        return cls(
            version=document.get("version"),
            transport=SignalTransportDescriptor.from_document(document.get("transport")),
            content=SignalContentDescriptor.from_document(document.get("content")),
            decoded_output=(
                AudioFormatDescriptor.from_document(decoded_output)
                if decoded_output is not None
                else None
            ),
            confidence=document.get("confidence"),
            source=SignalObservationSource.from_document(document.get("source")),
            observed_at=document.get("observedAt"),
        )
