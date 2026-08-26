from itertools import product

import pytest
from django.conf import settings
from django.test import override_settings

from core.orchestration.feature_flags import (
    AudioMutationDisabled,
    AudioOrchestrationFeatureFlags,
    ProcessorManagementDisabled,
    get_audio_orchestration_feature_flags,
    live_graph_reconciliation_allowed,
)


FLAG_NAMES = tuple(AudioOrchestrationFeatureFlags.__dataclass_fields__)
MUTATION_PREREQUISITES = {
    "runtime_observation",
    "shadow_resolution",
    "processor_management",
    "live_reconciliation",
}


def test_all_orchestration_features_default_to_disabled() -> None:
    assert settings.AUDIO_ORCHESTRATION_FEATURES == {
        "orchestration_api": False,
        "runtime_observation": False,
        "shadow_resolution": False,
        "processor_management": False,
        "live_reconciliation": False,
    }
    assert not get_audio_orchestration_feature_flags().audio_mutation_enabled
    assert settings.AUDIO_LIVE_GRAPH_ALLOWLIST == ()


@override_settings(
    AUDIO_LIVE_GRAPH_ALLOWLIST=("00000000-0000-0000-0000-000000000001",)
)
def test_live_graph_allowlist_is_exact_and_fail_closed() -> None:
    assert live_graph_reconciliation_allowed("00000000-0000-0000-0000-000000000001")
    assert not live_graph_reconciliation_allowed("00000000-0000-0000-0000-000000000002")


@override_settings(AUDIO_LIVE_GRAPH_ALLOWLIST=("*",))
def test_wildcard_allows_every_active_graph() -> None:
    assert live_graph_reconciliation_allowed("any-active-graph")


@pytest.mark.parametrize("values", product((False, True), repeat=len(FLAG_NAMES)))
def test_every_flag_combination_has_an_explicit_safe_mutation_gate(values) -> None:
    configured = dict(zip(FLAG_NAMES, values, strict=True))
    flags = AudioOrchestrationFeatureFlags.from_mapping(configured)
    expected_mutation = all(configured[name] for name in MUTATION_PREREQUISITES)

    assert flags.as_dict() == configured
    assert flags.audio_mutation_enabled is expected_mutation
    expected_processor_management = all(
        configured[name]
        for name in ("runtime_observation", "shadow_resolution", "processor_management")
    )
    assert flags.processor_management_enabled is expected_processor_management

    if expected_mutation:
        flags.require_audio_mutation()
    else:
        with pytest.raises(AudioMutationDisabled, match="Audio mutation is disabled"):
            flags.require_audio_mutation()

    if expected_processor_management:
        flags.require_processor_management()
    else:
        with pytest.raises(ProcessorManagementDisabled, match="Processor management is disabled"):
            flags.require_processor_management()


def test_api_can_be_disabled_while_an_explicit_live_controller_runs() -> None:
    flags = AudioOrchestrationFeatureFlags(
        orchestration_api=False,
        runtime_observation=True,
        shadow_resolution=True,
        processor_management=True,
        live_reconciliation=True,
    )

    assert flags.audio_mutation_enabled
    flags.require_audio_mutation()
