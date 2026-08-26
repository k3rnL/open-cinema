"""Feature gates for incrementally introducing audio orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass


class AudioMutationDisabled(RuntimeError):
    """Raised when code tries to mutate audio outside live-control mode."""


class ProcessorManagementDisabled(RuntimeError):
    """Raised when code tries to manage processors before their rollout stage."""


@dataclass(frozen=True, slots=True)
class AudioOrchestrationFeatureFlags:
    """Raw rollout flags plus the single derived audio-mutation gate.

    Raw flags are intentionally independent so observation, APIs, and shadow
    planning can be exercised separately. Owned processor lifecycle uses its
    narrower gate; ordinary routing requires :meth:`require_audio_mutation`.
    """

    orchestration_api: bool = False
    runtime_observation: bool = False
    shadow_resolution: bool = False
    processor_management: bool = False
    live_reconciliation: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "AudioOrchestrationFeatureFlags":
        return cls(
            orchestration_api=bool(values.get("orchestration_api", False)),
            runtime_observation=bool(values.get("runtime_observation", False)),
            shadow_resolution=bool(values.get("shadow_resolution", False)),
            processor_management=bool(values.get("processor_management", False)),
            live_reconciliation=bool(values.get("live_reconciliation", False)),
        )

    @property
    def audio_mutation_enabled(self) -> bool:
        """True only when the complete observation-to-apply path is enabled."""
        return all(
            (
                self.runtime_observation,
                self.shadow_resolution,
                self.processor_management,
                self.live_reconciliation,
            )
        )

    @property
    def processor_management_enabled(self) -> bool:
        """Allow owned processor lifecycle without authorizing ordinary routing."""

        return all(
            (
                self.runtime_observation,
                self.shadow_resolution,
                self.processor_management,
            )
        )

    @property
    def live_control_blockers(self) -> tuple[str, ...]:
        required = {
            "runtime_observation": self.runtime_observation,
            "shadow_resolution": self.shadow_resolution,
            "processor_management": self.processor_management,
            "live_reconciliation": self.live_reconciliation,
        }
        return tuple(name for name, enabled in required.items() if not enabled)

    def require_audio_mutation(self) -> None:
        if self.audio_mutation_enabled:
            return
        blockers = ", ".join(self.live_control_blockers)
        raise AudioMutationDisabled(f"Audio mutation is disabled by feature flags: {blockers}")

    def require_processor_management(self) -> None:
        if self.processor_management_enabled:
            return
        blockers = tuple(
            name
            for name in (
                "runtime_observation",
                "shadow_resolution",
                "processor_management",
            )
            if not getattr(self, name)
        )
        raise ProcessorManagementDisabled(
            "Processor management is disabled by feature flags: " + ", ".join(blockers)
        )

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


def get_audio_orchestration_feature_flags() -> AudioOrchestrationFeatureFlags:
    """Read the current Django configuration without importing it at module load."""
    from django.conf import settings

    return AudioOrchestrationFeatureFlags.from_mapping(settings.AUDIO_ORCHESTRATION_FEATURES)


def live_graph_reconciliation_allowed(definition_id: str) -> bool:
    """Apply the deployment's exact graph allowlist at the mutation boundary."""

    from django.conf import settings

    if not isinstance(definition_id, str) or not definition_id:
        raise ValueError("definition_id must be a non-empty string")
    configured = tuple(settings.AUDIO_LIVE_GRAPH_ALLOWLIST)
    return "*" in configured or definition_id in configured
