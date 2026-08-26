from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .node_catalogue import NodePortDefinition, NodeTypeDefinition
from .signal_contracts import (
    AudioContent,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)
from .signal_descriptors import AudioFormatDescriptor, SignalContentKind, SignalDescriptor
from .signal_negotiation import (
    signal_contract_from_audio_format,
    signal_contract_from_descriptor,
)
from .world_state_scheduler import WorldStateStabilityPolicy

DEFAULT_DECODER_CODECS = ("ac3", "dts", "eac3")


class PcmBehavior(StrEnum):
    BYPASS = "bypass"
    SILENCE = "silence"
    ERROR = "error"


class EncodedBehavior(StrEnum):
    DECODE = "decode"
    PASSTHROUGH = "passthrough"
    SILENCE = "silence"
    ERROR = "error"


class UnsupportedBehavior(StrEnum):
    PASSTHROUGH = "passthrough"
    SILENCE = "silence"
    ERROR = "error"


class AdaptiveDecoderChoice(StrEnum):
    PCM_BYPASS = "pcm-bypass"
    DECODE = "decode"
    PASSTHROUGH = "passthrough"
    SILENCE = "silence"
    ERROR = "error"
    WAITING = "waiting"


class AdaptiveDecoderDecisionStatus(StrEnum):
    RESOLVED = "resolved"
    WAITING = "waiting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AdaptiveDecoderPolicy:
    pcm_behavior: PcmBehavior
    encoded_behavior: EncodedBehavior
    unsupported_behavior: UnsupportedBehavior
    supported_codecs: tuple[str, ...] = DEFAULT_DECODER_CODECS
    minimum_confidence: float = 0.9
    detection_window_ms: int = 0
    confidence_hysteresis: float = 0.0
    debounce_ms: int = 0
    stable_duration_ms: int = 0
    cooldown_ms: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "pcm_behavior", PcmBehavior(self.pcm_behavior))
        object.__setattr__(
            self,
            "encoded_behavior",
            EncodedBehavior(self.encoded_behavior),
        )
        object.__setattr__(
            self,
            "unsupported_behavior",
            UnsupportedBehavior(self.unsupported_behavior),
        )
        codecs = tuple(sorted(set(self.supported_codecs)))
        if any(not isinstance(codec, str) or not codec for codec in codecs):
            raise ValueError("supported_codecs must contain non-empty codec tokens")
        object.__setattr__(self, "supported_codecs", codecs)
        if isinstance(self.minimum_confidence, bool) or not isinstance(
            self.minimum_confidence, (int, float)
        ):
            raise TypeError("minimum_confidence must be a number")
        threshold = float(self.minimum_confidence)
        if not 0 <= threshold <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        object.__setattr__(self, "minimum_confidence", threshold)
        self.stability_policy

    @property
    def stability_policy(self) -> WorldStateStabilityPolicy:
        return WorldStateStabilityPolicy(
            minimum_confidence=self.minimum_confidence,
            detection_window_ms=self.detection_window_ms,
            confidence_hysteresis=self.confidence_hysteresis,
            debounce_ms=self.debounce_ms,
            stable_duration_ms=self.stable_duration_ms,
            cooldown_ms=self.cooldown_ms,
        )

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> AdaptiveDecoderPolicy:
        definition = adaptive_decoder_node_type_definition()
        issues = definition.validate_configuration(document)
        if issues:
            raise ValueError(
                "invalid adaptive decoder configuration: "
                + "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            )
        return cls(
            pcm_behavior=document["pcmBehavior"],
            encoded_behavior=document["encodedBehavior"],
            unsupported_behavior=document["unsupportedBehavior"],
            supported_codecs=tuple(document.get("supportedCodecs", DEFAULT_DECODER_CODECS)),
            minimum_confidence=document.get("minimumConfidence", 0.9),
            detection_window_ms=document.get("detectionWindowMs", 0),
            confidence_hysteresis=document.get("confidenceHysteresis", 0.0),
            debounce_ms=document.get("debounceMs", 0),
            stable_duration_ms=document.get("stableDurationMs", 0),
            cooldown_ms=document.get("cooldownMs", 0),
        )


@dataclass(frozen=True, slots=True)
class AdaptiveDecoderDecision:
    choice: AdaptiveDecoderChoice
    status: AdaptiveDecoderDecisionStatus
    output_contract: SignalContract | None
    codec: str | None
    reason: str

    def to_document(self) -> dict[str, object]:
        return {
            "choice": self.choice.value,
            "status": self.status.value,
            "codec": self.codec,
            "outputContract": (
                self.output_contract.to_document() if self.output_contract is not None else None
            ),
            "reason": self.reason,
        }


def _decision(
    choice: AdaptiveDecoderChoice,
    *,
    output: SignalContract | None,
    codec: str | None,
    reason: str,
    status: AdaptiveDecoderDecisionStatus = AdaptiveDecoderDecisionStatus.RESOLVED,
) -> AdaptiveDecoderDecision:
    return AdaptiveDecoderDecision(choice, status, output, codec, reason)


def _silence(codec: str | None, reason: str) -> AdaptiveDecoderDecision:
    return _decision(
        AdaptiveDecoderChoice.SILENCE,
        output=None,
        codec=codec,
        reason=reason,
    )


def _error(codec: str | None, reason: str) -> AdaptiveDecoderDecision:
    return _decision(
        AdaptiveDecoderChoice.ERROR,
        status=AdaptiveDecoderDecisionStatus.ERROR,
        output=None,
        codec=codec,
        reason=reason,
    )


def resolve_adaptive_decoder_choice(
    descriptor: SignalDescriptor,
    policy: AdaptiveDecoderPolicy,
    *,
    decoder_available: bool = True,
    emitted_output: AudioFormatDescriptor | None = None,
) -> AdaptiveDecoderDecision:
    if not isinstance(descriptor, SignalDescriptor):
        raise TypeError("descriptor must be a SignalDescriptor")
    if not isinstance(policy, AdaptiveDecoderPolicy):
        raise TypeError("policy must be an AdaptiveDecoderPolicy")
    if not isinstance(decoder_available, bool):
        raise TypeError("decoder_available must be a boolean")
    if emitted_output is not None and not isinstance(emitted_output, AudioFormatDescriptor):
        raise TypeError("emitted_output must be an AudioFormatDescriptor or null")
    normalized_output = (
        signal_contract_from_audio_format(emitted_output) if emitted_output is not None else None
    )
    if descriptor.confidence < policy.minimum_confidence:
        return _decision(
            AdaptiveDecoderChoice.WAITING,
            status=AdaptiveDecoderDecisionStatus.WAITING,
            output=None,
            codec=descriptor.content.codec,
            reason="signal_confidence_below_minimum",
        )
    if descriptor.content.kind is SignalContentKind.UNKNOWN:
        return _decision(
            AdaptiveDecoderChoice.WAITING,
            status=AdaptiveDecoderDecisionStatus.WAITING,
            output=None,
            codec=None,
            reason="signal_content_unknown",
        )
    if descriptor.content.kind is SignalContentKind.SILENCE:
        return _silence(None, "input_silence")
    if descriptor.content.kind is SignalContentKind.PCM:
        if policy.pcm_behavior is PcmBehavior.BYPASS:
            return _decision(
                AdaptiveDecoderChoice.PCM_BYPASS,
                output=normalized_output or signal_contract_from_descriptor(descriptor),
                codec=None,
                reason="pcm_bypass_explicitly_allowed",
            )
        if policy.pcm_behavior is PcmBehavior.SILENCE:
            return _silence(None, "pcm_silence_policy")
        return _error(None, "pcm_rejected_by_policy")

    codec = descriptor.content.codec
    supported = codec in policy.supported_codecs
    behavior = policy.encoded_behavior if supported else policy.unsupported_behavior
    if behavior is EncodedBehavior.DECODE:
        if not decoder_available:
            return _decision(
                AdaptiveDecoderChoice.DECODE,
                status=AdaptiveDecoderDecisionStatus.WAITING,
                output=None,
                codec=codec,
                reason="decoder_unavailable",
            )
        if descriptor.decoded_output is None:
            return _decision(
                AdaptiveDecoderChoice.DECODE,
                status=AdaptiveDecoderDecisionStatus.WAITING,
                output=SignalContract(
                    media_kind=MediaKind.AUDIO,
                    content=AudioContent.PCM,
                ),
                codec=codec,
                reason="decoded_output_not_observed",
            )
        return _decision(
            AdaptiveDecoderChoice.DECODE,
            output=(
                normalized_output
                or signal_contract_from_descriptor(descriptor, decoded_output=True)
            ),
            codec=codec,
            reason="observed_decoded_output_authoritative",
        )
    if behavior in {EncodedBehavior.PASSTHROUGH, UnsupportedBehavior.PASSTHROUGH}:
        return _decision(
            AdaptiveDecoderChoice.PASSTHROUGH,
            output=signal_contract_from_descriptor(descriptor),
            codec=codec,
            reason=(
                "supported_codec_passthrough_policy"
                if supported
                else "unsupported_codec_passthrough_policy"
            ),
        )
    if behavior in {EncodedBehavior.SILENCE, UnsupportedBehavior.SILENCE}:
        return _silence(
            codec,
            "supported_codec_silence_policy" if supported else "unsupported_codec_silence_policy",
        )
    return _error(
        codec,
        "supported_codec_error_policy" if supported else "unsupported_codec_error_policy",
    )


def adaptive_decoder_node_type_definition() -> NodeTypeDefinition:
    audio_any = SignalContract(media_kind=MediaKind.AUDIO, content=AudioContent.ANY)
    return NodeTypeDefinition(
        type_id="processor.pcm-auto-decoder",
        version=1,
        display_name="Adaptive PCM/encoded decoder",
        category="processing",
        description=(
            "Detects PCM or IEC-61937 content and emits one stable PCM working bus, "
            "using silence while the content mode is uncertain."
        ),
        ports=(
            NodePortDefinition(
                PortContract("input", PortDirection.INPUT, audio_any),
                description="PCM carrier or IEC-61937 input.",
            ),
            NodePortDefinition(
                PortContract("output", PortDirection.OUTPUT, audio_any),
                description="Stable adaptive PCM output with an explicit working layout.",
            ),
        ),
        configuration_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": [
                "pcmBehavior",
                "encodedBehavior",
                "unsupportedBehavior",
            ],
            "additionalProperties": False,
            "properties": {
                "pcmBehavior": {"enum": ["bypass", "silence", "error"]},
                "encodedBehavior": {"enum": ["decode", "passthrough", "silence", "error"]},
                "unsupportedBehavior": {"enum": ["passthrough", "silence", "error"]},
                "supportedCodecs": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[a-z0-9][a-z0-9._+-]{0,63}$",
                    },
                },
                "minimumConfidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "resourcePriority": {"type": "integer"},
                "detectionWindowMs": {"type": "integer", "minimum": 0},
                "confidenceHysteresis": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "debounceMs": {"type": "integer", "minimum": 0},
                "stableDurationMs": {"type": "integer", "minimum": 0},
                "cooldownMs": {"type": "integer", "minimum": 0},
                "workingSampleFormat": {
                    "enum": ["FLOAT32LE", "S32LE", "S16LE"],
                    "default": "FLOAT32LE",
                },
                "workingRate": {
                    "type": "integer",
                    "minimum": 8000,
                    "maximum": 384000,
                    "default": 48000,
                },
                "workingLayout": {
                    "enum": ["stereo", "5.1-side", "5.1-rear", "7.1"],
                    "default": "7.1",
                },
            },
        },
    )
