from io import StringIO

import pytest
from django.core.management import call_command

from api.management.commands.probe_managed_processors import (
    camilladsp_probe_request,
    decoder_probe_request,
)
from core.orchestration.feature_flags import ProcessorManagementDisabled


def test_probe_requests_use_stable_native_pipewire_instances_without_targets() -> None:
    decoder = decoder_probe_request().configuration
    camilladsp = camilladsp_probe_request().configuration

    assert decoder["instanceId"] == "decoder-0"
    assert decoder["outputDescriptor"]["layout"]["channels"] == 8
    generated = camilladsp["generatedConfiguration"]
    assert camilladsp["instanceId"] == "camilladsp-0"
    assert generated["devices"]["capture"]["type"] == "PipeWire"
    assert generated["devices"]["playback"]["type"] == "PipeWire"
    assert generated["devices"]["capture"]["autoconnect_to"] is None
    assert generated["devices"]["playback"]["autoconnect_to"] is None


def test_probe_refuses_processor_lifecycle_before_mutation_gate() -> None:
    with pytest.raises(ProcessorManagementDisabled):
        call_command("probe_managed_processors", cleanup_only=True, stdout=StringIO())
