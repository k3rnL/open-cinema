from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping


class PortDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class MediaKind(StrEnum):
    AUDIO = "audio"
    CONTROL = "control"


class AudioContent(StrEnum):
    ANY = "any"
    PCM = "pcm"
    ENCODED = "encoded"


class KnownSampleFormat(StrEnum):
    U8 = "U8"
    S16LE = "S16LE"
    S24LE = "S24LE"
    S24_32LE = "S24_32LE"
    S32LE = "S32LE"
    FLOAT32LE = "FLOAT32LE"
    FLOAT64LE = "FLOAT64LE"


def _stable_strings(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    received = tuple(values)
    if any(not isinstance(value, str) or not value for value in received):
        raise ValueError(f"{field} must contain unique non-empty strings")
    return tuple(sorted({str(value) for value in received}))


@dataclass(frozen=True, slots=True, order=True)
class ChannelLayout:
    channels: int
    positions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.channels, bool) or not isinstance(self.channels, int):
            raise ValueError("channel count must be an integer")
        if self.channels < 1 or self.channels > 64:
            raise ValueError("channel count must be between 1 and 64")
        normalized = tuple(self.positions)
        if normalized and len(normalized) != self.channels:
            raise ValueError("channel positions must match channel count")
        if any(not isinstance(position, str) or not position for position in normalized):
            raise ValueError("channel positions must be non-empty strings")
        object.__setattr__(self, "positions", normalized)

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {"channels": self.channels}
        if self.positions:
            document["positions"] = list(self.positions)
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> "ChannelLayout":
        if not isinstance(document, Mapping):
            raise ValueError("channel layout must be an object")
        unknown = set(document) - {"channels", "positions"}
        if unknown:
            raise ValueError(f"unknown channel-layout fields: {', '.join(sorted(unknown))}")
        positions = document.get("positions", ())
        if not isinstance(positions, (list, tuple)):
            raise ValueError("channel positions must be an array")
        return cls(channels=document.get("channels"), positions=tuple(positions))


@dataclass(frozen=True, slots=True)
class LatencyRange:
    minimum_ms: float | None = None
    maximum_ms: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum", self.minimum_ms),
            ("maximum", self.maximum_ms),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
            ):
                raise ValueError(f"latency {name} must be a non-negative number")
        if (
            self.minimum_ms is not None
            and self.maximum_ms is not None
            and self.minimum_ms > self.maximum_ms
        ):
            raise ValueError("latency minimum cannot exceed maximum")

    def overlaps(self, other: "LatencyRange") -> bool:
        minimum = max(
            value for value in (self.minimum_ms, other.minimum_ms, 0) if value is not None
        )
        maxima = [value for value in (self.maximum_ms, other.maximum_ms) if value is not None]
        return not maxima or minimum <= min(maxima)

    def to_document(self) -> dict[str, float]:
        document = {}
        if self.minimum_ms is not None:
            document["minimum"] = self.minimum_ms
        if self.maximum_ms is not None:
            document["maximum"] = self.maximum_ms
        return document


@dataclass(frozen=True, slots=True)
class SignalContract:
    media_kind: MediaKind
    content: AudioContent = AudioContent.ANY
    codecs: tuple[str, ...] = ()
    sample_formats: tuple[str, ...] = ()
    rates: tuple[int, ...] = ()
    layouts: tuple[ChannelLayout, ...] = ()
    latency: LatencyRange | None = None
    capabilities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "media_kind", MediaKind(self.media_kind))
        object.__setattr__(self, "content", AudioContent(self.content))
        object.__setattr__(self, "codecs", _stable_strings(self.codecs, field="codecs"))
        object.__setattr__(
            self,
            "sample_formats",
            _stable_strings(self.sample_formats, field="sample_formats"),
        )
        rates = tuple(sorted(set(self.rates)))
        if any(isinstance(rate, bool) or not isinstance(rate, int) or rate < 1 for rate in rates):
            raise ValueError("rates must contain unique positive integers")
        object.__setattr__(self, "rates", rates)
        layouts = tuple(sorted(set(self.layouts)))
        if any(not isinstance(layout, ChannelLayout) for layout in layouts):
            raise ValueError("layouts must contain ChannelLayout values")
        object.__setattr__(self, "layouts", layouts)
        if self.latency is not None and not isinstance(self.latency, LatencyRange):
            raise ValueError("latency must be a LatencyRange or null")
        object.__setattr__(
            self,
            "capabilities",
            _stable_strings(self.capabilities, field="capabilities"),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _stable_strings(
                self.required_capabilities,
                field="required_capabilities",
            ),
        )
        if self.media_kind == MediaKind.CONTROL and (
            self.content != AudioContent.ANY
            or self.codecs
            or self.sample_formats
            or self.rates
            or self.layouts
        ):
            raise ValueError("control contracts cannot declare audio format fields")

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "mediaKind": self.media_kind.value,
            "content": self.content.value,
        }
        for key, values in (
            ("codecs", self.codecs),
            ("sampleFormats", self.sample_formats),
            ("rates", self.rates),
            ("capabilities", self.capabilities),
            ("requiredCapabilities", self.required_capabilities),
        ):
            if values:
                document[key] = list(values)
        if self.layouts:
            document["layouts"] = [layout.to_document() for layout in self.layouts]
        if self.latency is not None:
            document["latencyMs"] = self.latency.to_document()
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> "SignalContract":
        if not isinstance(document, Mapping):
            raise ValueError("signal contract must be an object")
        known = {
            "mediaKind",
            "content",
            "codecs",
            "sampleFormats",
            "rates",
            "layouts",
            "latencyMs",
            "capabilities",
            "requiredCapabilities",
        }
        unknown = set(document) - known
        if unknown:
            raise ValueError(f"unknown signal-contract fields: {', '.join(sorted(unknown))}")

        def array(name):
            value = document.get(name, ())
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{name} must be an array")
            return tuple(value)

        latency_document = document.get("latencyMs")
        latency = None
        if latency_document is not None:
            if not isinstance(latency_document, Mapping):
                raise ValueError("latencyMs must be an object")
            unknown_latency = set(latency_document) - {"minimum", "maximum"}
            if unknown_latency:
                raise ValueError(f"unknown latency fields: {', '.join(sorted(unknown_latency))}")
            latency = LatencyRange(
                minimum_ms=latency_document.get("minimum"),
                maximum_ms=latency_document.get("maximum"),
            )
        return cls(
            media_kind=document.get("mediaKind"),
            content=document.get("content", AudioContent.ANY),
            codecs=array("codecs"),
            sample_formats=array("sampleFormats"),
            rates=array("rates"),
            layouts=tuple(ChannelLayout.from_document(item) for item in array("layouts")),
            latency=latency,
            capabilities=array("capabilities"),
            required_capabilities=array("requiredCapabilities"),
        )


@dataclass(frozen=True, slots=True)
class PortCompatibility:
    compatible: bool
    reasons: tuple[str, ...] = ()


def _sets_overlap(first: tuple[object, ...], second: tuple[object, ...]) -> bool:
    return not first or not second or not set(first).isdisjoint(second)


@dataclass(frozen=True, slots=True)
class PortContract:
    name: str
    direction: PortDirection
    signal: SignalContract
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("port name must be a non-empty string")
        object.__setattr__(self, "direction", PortDirection(self.direction))
        if not isinstance(self.signal, SignalContract):
            raise ValueError("port signal must be a SignalContract")

    def compatibility_with(self, target: "PortContract") -> PortCompatibility:
        reasons: list[str] = []
        if self.direction != PortDirection.OUTPUT:
            reasons.append("source_direction")
        if target.direction != PortDirection.INPUT:
            reasons.append("target_direction")
        source = self.signal
        sink = target.signal
        if source.media_kind != sink.media_kind:
            reasons.append("media_kind")
        if (
            source.content != AudioContent.ANY
            and sink.content != AudioContent.ANY
            and source.content != sink.content
        ):
            reasons.append("content")
        for reason, first, second in (
            ("codec", source.codecs, sink.codecs),
            ("sample_format", source.sample_formats, sink.sample_formats),
            ("rate", source.rates, sink.rates),
            ("layout", source.layouts, sink.layouts),
        ):
            if not _sets_overlap(first, second):
                reasons.append(reason)
        if source.latency and sink.latency and not source.latency.overlaps(sink.latency):
            reasons.append("latency")
        if not set(sink.required_capabilities).issubset(source.capabilities):
            reasons.append("source_capability")
        if not set(source.required_capabilities).issubset(sink.capabilities):
            reasons.append("target_capability")
        return PortCompatibility(compatible=not reasons, reasons=tuple(reasons))
