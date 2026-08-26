from dataclasses import replace
from types import SimpleNamespace

from django.test import override_settings
from wyreplumber.runtime import FrozenDict

from core.orchestration.camilladsp_profiles import normalize_camilladsp_profile
from core.orchestration.managed_processor_controller import (
    ManagedProcessorController,
    ManagedProcessorConvergence,
    ManagedProcessorInstance,
)
from core.plugin_system.contracts import ProcessingDriverResult
from tests.test_live_reconciliation import _processor_chain_world

FEATURES = {
    "orchestration_api": True,
    "runtime_observation": True,
    "shadow_resolution": True,
    "processor_management": True,
    "live_reconciliation": True,
}


def _profile():
    contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "sampleFormats": ["FLOAT32LE"],
        "rates": [48000],
        "layouts": [
            {
                "channels": 8,
                "positions": ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"],
            }
        ],
    }
    return normalize_camilladsp_profile(
        {
            "schemaVersion": 1,
            "title": "Limited live passthrough",
            "parameters": [],
            "signalContracts": {"input": contract, "output": contract},
            "processing": {"chunksize": 1024, "pipeline": []},
        }
    )


def _headset_profile():
    input_contract = {
        "mediaKind": "audio",
        "content": "pcm",
        "sampleFormats": ["FLOAT32LE"],
        "rates": [48000],
        "layouts": [
            {
                "channels": 8,
                "positions": ["FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"],
            }
        ],
    }
    output_contract = {
        **input_contract,
        "layouts": [{"channels": 2, "positions": ["FL", "FR"]}],
    }
    return normalize_camilladsp_profile(
        {
            "schemaVersion": 1,
            "title": "Headset downmix",
            "parameters": [],
            "signalContracts": {"input": input_contract, "output": output_contract},
            "processing": {
                "chunksize": 1024,
                "mixers": {
                    "headset_downmix": {
                        "channels": {"in": 8, "out": 2},
                        "mapping": [
                            {"dest": 0, "sources": [{"channel": 0, "gain": 0.0}]},
                            {"dest": 1, "sources": [{"channel": 1, "gain": 0.0}]},
                        ],
                    }
                },
                "pipeline": [],
            },
        }
    )


class FakeDriver:
    def __init__(self, kind):
        self.kind = kind
        self.requests = []

    def prepare(self, request):
        self.requests.append(("prepare", request))
        return ProcessingDriverResult("prepared", {"validation": "valid"})

    def activate(self, request):
        self.requests.append(("activate", request))
        return ProcessingDriverResult(
            "unhealthy" if self.kind == "camilladsp" else "active",
            {"readiness": False},
        )

    def observe(self, request):
        self.requests.append(("observe", request))
        if self.kind == "camilladsp":
            return ProcessingDriverResult(
                "healthy",
                {"readiness": True, "engineState": "running"},
            )
        return ProcessingDriverResult(
            "healthy",
            {"statusChannel": "connected", "lifecycle": "ready"},
            {"protocolVersion": 2},
        )


def _resolved():
    return SimpleNamespace(
        digest="a" * 64,
        document=FrozenDict(
            {
                "expandedGraph": {
                    "nodes": [
                        {
                            "id": "decoder",
                            "type": "processor.pcm-auto-decoder",
                            "configuration": {
                                "workingSampleFormat": "FLOAT32LE",
                                "workingRate": 48000,
                                "workingLayout": "7.1",
                                "detectionWindowMs": 150,
                            },
                        },
                        {
                            "id": "dsp",
                            "type": "processor.camilladsp-profile-selector",
                            "configuration": {
                                "profileId": "11111111-1111-1111-1111-111111111111",
                                "profileVersion": 1,
                            },
                        },
                    ],
                    "edges": [
                        {
                            "id": "decoder-to-dsp",
                            "from": {"node": "decoder", "port": "output"},
                            "to": {"node": "dsp", "port": "input"},
                        }
                    ],
                },
                "paths": {"selectedEdgeIds": ["decoder-to-dsp"]},
                "resourceAssignments": {
                    "decoder": {"resourceId": "decoder:0", "units": 1},
                    "dsp": {"resourceId": "camilladsp:0", "units": 1},
                },
            }
        ),
    )


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_controller_builds_stable_requests_and_verifies_after_routing() -> None:
    decoder = FakeDriver("decoder")
    camilladsp = FakeDriver("camilladsp")
    controller = ManagedProcessorController(
        decoder_driver=decoder,
        camilladsp_driver=camilladsp,
        profile_loader=lambda activation, configuration: _profile(),
        readiness_timeout_seconds=0.2,
    )
    activation = SimpleNamespace(definition=SimpleNamespace(owner=object()))

    convergence = controller.converge(activation, _resolved())
    verified, observations = controller.verify(convergence)

    assert [instance.kind for instance in convergence.instances] == [
        "decoder",
        "camilladsp",
    ]
    decoder_request = convergence.instances[0].request.configuration
    assert decoder_request["instanceId"] == "decoder-0"
    assert decoder_request["outputDescriptor"]["layout"]["channels"] == 8
    assert decoder_request["detectionWindowMs"] == 150
    camilla_request = convergence.instances[1].request.configuration
    assert camilla_request["instanceId"] == "camilladsp-0"
    assert (
        camilla_request["generatedConfiguration"]["devices"]["capture"]["node_name"]
        == "opencinema.camilladsp.0.capture"
    )
    assert (
        camilla_request["generatedConfiguration"]["devices"]["playback"]["autoconnect_to"] is None
    )
    assert verified is True
    assert observations["decoder"]["details"]["protocolVersion"] == 2
    assert observations["dsp"]["facts"]["engineState"] == "running"


def test_runtime_readiness_requires_every_declared_processor_port() -> None:
    controller = ManagedProcessorController(
        decoder_driver=FakeDriver("decoder"),
        camilladsp_driver=FakeDriver("camilladsp"),
        profile_loader=lambda activation, configuration: _profile(),
        readiness_timeout_seconds=0.2,
    )
    activation = SimpleNamespace(definition=SimpleNamespace(owner=object()))
    instances = controller._requests(activation, _resolved())
    world = _processor_chain_world()

    assert controller.runtime_resources_ready(world, instances) is True

    runtime = world.runtime
    incomplete_nodes = tuple(
        replace(node, output_port_ids=node.output_port_ids[:-1]) if node.id == 43 else node
        for node in runtime.nodes
    )
    incomplete_world = SimpleNamespace(
        runtime=replace(
            runtime,
            nodes=incomplete_nodes,
            ports=tuple(port for port in runtime.ports if port.id != 438),
        )
    )

    assert controller.runtime_resources_ready(incomplete_world, instances) is False
    keys, evidence = controller.runtime_instance_observation(
        incomplete_world,
        instances[1],
    )
    playback = evidence["identities"][1]
    assert keys is None
    assert playback["stableKey"].endswith(":playback")
    assert playback["expectedPortCount"] == 8
    assert playback["observedPortCount"] == 7
    assert playback["ready"] is False


@override_settings(AUDIO_ORCHESTRATION_FEATURES=FEATURES)
def test_controller_selects_output_profile_and_generates_stereo_playback() -> None:
    resolved = _resolved()
    document = resolved.document.to_dict()
    document["expandedGraph"]["nodes"].append(
        {
            "id": "output-selector",
            "type": "core.ordered-selector",
            "configuration": {},
        }
    )
    document["expandedGraph"]["edges"].append(
        {
            "id": "dsp-to-output",
            "from": {"node": "dsp", "port": "output"},
            "to": {"node": "output-selector", "port": "input"},
        }
    )
    document["paths"]["selectedEdgeIds"].append("dsp-to-output")
    document["expandedGraph"]["nodes"][1]["configuration"] = {
        "profiles": [
            {
                "output": "endpoint:headset",
                "profile": "22222222-2222-2222-2222-222222222222",
                "profileVersion": 1,
            }
        ],
        "channelAdaptation": {"mixer": "headset_downmix"},
    }
    document["selections"] = {
        "output-selector": {
            "selected": [{"referenceId": "endpoint:headset"}],
        }
    }
    resolved = SimpleNamespace(digest="b" * 64, document=FrozenDict(document))
    decoder = FakeDriver("decoder")
    camilladsp = FakeDriver("camilladsp")
    loaded = []

    def load_profile(activation, configuration):
        loaded.append(configuration)
        return _headset_profile()

    controller = ManagedProcessorController(
        decoder_driver=decoder,
        camilladsp_driver=camilladsp,
        profile_loader=load_profile,
        readiness_timeout_seconds=0.2,
    )
    activation = SimpleNamespace(definition=SimpleNamespace(owner=object()))

    convergence = controller.converge(activation, resolved)

    request = convergence.instances[1].request
    assert loaded == [
        {
            "profileId": "22222222-2222-2222-2222-222222222222",
            "profileVersion": 1,
            "parameterBindings": {},
        }
    ]
    assert request.configuration["generatedConfiguration"]["devices"]["capture"]["channels"] == 8
    assert request.configuration["generatedConfiguration"]["devices"]["playback"]["channels"] == 2
    assert request.configuration["generatedConfiguration"]["pipeline"][0] == {
        "type": "Mixer",
        "name": "headset_downmix",
    }
    assert request.plan["materialFormatChange"] is True


class StaleRuntimeDriver:
    def __init__(self):
        self.calls = []
        self.recycled = False

    def deactivate(self, request):
        self.calls.append(("deactivate", request))
        return ProcessingDriverResult("inactive", {"readiness": False})

    def activate(self, request):
        self.calls.append(("activate", request))
        self.recycled = True
        return ProcessingDriverResult("active", {"readiness": True})


def test_wait_for_runtime_recycles_process_stranded_on_old_pipewire_generation() -> None:
    driver = StaleRuntimeDriver()
    request = object()
    instance = ManagedProcessorInstance(
        node_id="dsp",
        kind="camilladsp",
        request=request,
        driver=driver,
        runtime_identities=(object(), object()),
    )
    convergence = ManagedProcessorConvergence(
        instances=(instance,),
        lifecycle=(),
    )
    controller = ManagedProcessorController(
        decoder_driver=FakeDriver("decoder"),
        camilladsp_driver=FakeDriver("camilladsp"),
        readiness_timeout_seconds=0.2,
    )
    controller.runtime_instance_keys = lambda observed_world, observed: (
        ("runtime:1:node:9",) if driver.recycled else None
    )
    world = SimpleNamespace(runtime=object())

    refreshed = controller.wait_for_runtime(world, lambda: world, convergence)

    assert refreshed is world
    assert driver.calls == [("deactivate", request), ("activate", request)]


def test_wait_for_runtime_returns_existing_world_without_refresh_when_resources_match() -> None:
    instance = ManagedProcessorInstance(
        node_id="dsp",
        kind="camilladsp",
        request=object(),
        driver=FakeDriver("camilladsp"),
        runtime_identities=(object(),),
    )
    convergence = ManagedProcessorConvergence((instance,), ())
    controller = ManagedProcessorController(
        decoder_driver=FakeDriver("decoder"),
        camilladsp_driver=FakeDriver("camilladsp"),
        readiness_timeout_seconds=0.2,
    )
    world = SimpleNamespace(runtime=object())
    controller.runtime_instance_keys = lambda observed_world, observed: ("runtime:1:node:4",)
    refreshes = []

    refreshed = controller.wait_for_runtime(
        world,
        lambda: refreshes.append(True) or world,
        convergence,
    )

    assert refreshed is world
    assert refreshes == []


def test_wait_for_runtime_requires_new_keys_after_material_reconfiguration() -> None:
    instance = ManagedProcessorInstance(
        node_id="dsp",
        kind="camilladsp",
        request=object(),
        driver=FakeDriver("camilladsp"),
        runtime_identities=(object(),),
    )
    convergence = ManagedProcessorConvergence((instance,), (), (instance,))
    controller = ManagedProcessorController(
        decoder_driver=FakeDriver("decoder"),
        camilladsp_driver=FakeDriver("camilladsp"),
        readiness_timeout_seconds=0.2,
    )
    old_world = SimpleNamespace(runtime=object())
    new_world = SimpleNamespace(runtime=object())
    keys = {
        id(old_world): ("runtime:1:node:4",),
        id(new_world): ("runtime:1:node:9",),
    }
    controller.runtime_instance_keys = lambda observed_world, observed: keys[id(observed_world)]
    worlds = iter((new_world,))

    refreshed = controller.wait_for_runtime(old_world, lambda: next(worlds), convergence)

    assert refreshed is new_world
