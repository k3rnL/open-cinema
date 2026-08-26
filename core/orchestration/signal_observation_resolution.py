from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import FrozenDict

from .signal_descriptors import AudioFormatDescriptor, SignalDescriptor


class SignalObservationHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class DecodedOutputSource(StrEnum):
    DECODER_OBSERVED = "decoder-observed"
    PIPEWIRE_OBSERVED = "pipewire-observed"
    CODEC_ASSUMPTION = "codec-assumption"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DecodedOutputResolution:
    format: AudioFormatDescriptor | None
    source: DecodedOutputSource
    health: SignalObservationHealth
    disagreements: tuple[str, ...]
    reason: str

    def to_document(self) -> dict[str, object]:
        return {
            "format": self.format.to_document() if self.format is not None else None,
            "source": self.source.value,
            "health": self.health.value,
            "disagreements": list(self.disagreements),
            "reason": self.reason,
        }

    def to_processor_facts(self, processor_id: str) -> FrozenDict:
        if not isinstance(processor_id, str) or not processor_id:
            raise ValueError("processor_id must be a non-empty string")
        prefix = f"processor.{processor_id}"
        return FrozenDict(
            {
                f"{prefix}.health": self.health.value,
                f"{prefix}.ready": self.format is not None,
                f"{prefix}.outputSource": self.source.value,
                f"{prefix}.observationDisagreements": list(self.disagreements),
            }
        )


def _format_disagreements(
    decoder: AudioFormatDescriptor,
    pipewire: AudioFormatDescriptor,
) -> tuple[str, ...]:
    disagreements = []
    if (
        decoder.sample_format is not None
        and pipewire.sample_format is not None
        and decoder.sample_format != pipewire.sample_format
    ):
        disagreements.append("sample_format")
    if decoder.rate is not None and pipewire.rate is not None and decoder.rate != pipewire.rate:
        disagreements.append("rate")
    if decoder.layout is not None and pipewire.layout is not None:
        if decoder.layout.channels != pipewire.layout.channels:
            disagreements.append("channels")
        elif (
            decoder.layout.positions
            and pipewire.layout.positions
            and decoder.layout.positions != pipewire.layout.positions
        ):
            disagreements.append("channel_layout")
    return tuple(disagreements)


def resolve_decoded_output_observation(
    descriptor: SignalDescriptor,
    *,
    pipewire_output: AudioFormatDescriptor | None = None,
    codec_maximum_assumption: AudioFormatDescriptor | None = None,
) -> DecodedOutputResolution:
    """Select actual observations before static codec-capability assumptions."""

    if not isinstance(descriptor, SignalDescriptor):
        raise TypeError("descriptor must be a SignalDescriptor")
    for name, value in (
        ("pipewire_output", pipewire_output),
        ("codec_maximum_assumption", codec_maximum_assumption),
    ):
        if value is not None and not isinstance(value, AudioFormatDescriptor):
            raise TypeError(f"{name} must be an AudioFormatDescriptor or null")
    decoder_output = descriptor.decoded_output
    if decoder_output is not None:
        disagreements = (
            _format_disagreements(decoder_output, pipewire_output)
            if pipewire_output is not None
            else ()
        )
        if disagreements:
            return DecodedOutputResolution(
                format=decoder_output,
                source=DecodedOutputSource.DECODER_OBSERVED,
                health=SignalObservationHealth.DEGRADED,
                disagreements=disagreements,
                reason="decoder_and_pipewire_output_disagree",
            )
        return DecodedOutputResolution(
            format=decoder_output,
            source=DecodedOutputSource.DECODER_OBSERVED,
            health=SignalObservationHealth.HEALTHY,
            disagreements=(),
            reason="decoded_frame_output_is_authoritative",
        )
    if pipewire_output is not None:
        return DecodedOutputResolution(
            format=pipewire_output,
            source=DecodedOutputSource.PIPEWIRE_OBSERVED,
            health=SignalObservationHealth.DEGRADED,
            disagreements=("decoder_output_missing",),
            reason="using_pipewire_output_while_decoder_observation_is_missing",
        )
    if codec_maximum_assumption is not None:
        return DecodedOutputResolution(
            format=codec_maximum_assumption,
            source=DecodedOutputSource.CODEC_ASSUMPTION,
            health=SignalObservationHealth.UNKNOWN,
            disagreements=("actual_output_unobserved",),
            reason="codec_assumption_is_non_authoritative",
        )
    return DecodedOutputResolution(
        format=None,
        source=DecodedOutputSource.UNAVAILABLE,
        health=SignalObservationHealth.UNKNOWN,
        disagreements=("actual_output_unavailable",),
        reason="no_decoded_output_observation",
    )
