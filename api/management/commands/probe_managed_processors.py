from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from core.orchestration.camilladsp_driver import (
    CamillaDSPInstanceConfiguration,
    CamillaDSPDriver,
    SystemdCamillaDSPProcessManager,
)
from core.orchestration.camilladsp_resources import CamillaDSPDeploymentPolicy
from core.orchestration.decoder_driver import (
    DecoderDriver,
    DecoderInstanceConfiguration,
    SystemdDecoderProcessManager,
)
from core.orchestration.feature_flags import get_audio_orchestration_feature_flags
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.live_reconciliation import _pair_audio_ports
from core.orchestration.runtime_world import WyrePlumberRuntimeOwner
from core.orchestration.wireplumber_driver import (
    OPEN_CINEMA_LINK_OWNER,
    ManagedLinkShape,
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_managed_link_action,
    build_remove_managed_link_action,
    register_managed_link_controls,
)
from core.plugin_system.contracts import ProcessingDriverRequest


_POSITIONS = ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")
_LINK_PREFIX = "processor-rollout:decoder-0-to-camilladsp-0:"


def decoder_probe_request() -> ProcessingDriverRequest:
    return ProcessingDriverRequest(
        node_instance_id="rollout-decoder",
        idempotency_key="processor-rollout:decoder-0",
        configuration={
            "instanceId": "decoder-0",
            "captureDescriptor": {
                "sampleFormat": "S16LE",
                "rate": 48_000,
                "layout": {"channels": 2, "positions": ["FL", "FR"]},
            },
            "outputDescriptor": {
                "sampleFormat": "FLOAT32LE",
                "rate": 48_000,
                "layout": {"channels": 8, "positions": list(_POSITIONS)},
            },
            "startupTimeoutSeconds": 10,
        },
        plan={},
    )


def camilladsp_probe_request() -> ProcessingDriverRequest:
    policy = CamillaDSPDeploymentPolicy(instance_count=1)
    capture, playback = policy.endpoints(0)
    configuration = {
        "title": "Open Cinema processor rollout probe",
        "devices": {
            "samplerate": 48_000,
            "chunksize": 1024,
            "capture": {
                "type": "PipeWire",
                "channels": 8,
                "node_name": capture.node_name,
                "node_description": capture.node_description,
                "node_group_name": capture.node_group_name,
                "autoconnect_to": None,
            },
            "playback": {
                "type": "PipeWire",
                "channels": 8,
                "node_name": playback.node_name,
                "node_description": playback.node_description,
                "node_group_name": playback.node_group_name,
                "autoconnect_to": None,
            },
        },
        "filters": {},
        "pipeline": [],
    }
    descriptor = {
        "sampleFormat": "FLOAT32LE",
        "rate": 48_000,
        "layout": {"channels": 8, "positions": list(_POSITIONS)},
    }
    return ProcessingDriverRequest(
        node_instance_id="rollout-camilladsp",
        idempotency_key="processor-rollout:camilladsp-0",
        configuration={
            **policy.driver_defaults(0),
            "generatedConfiguration": configuration,
            "configurationDigest": graph_content_digest(configuration),
            "profileDigest": graph_content_digest(
                {"kind": "processor-rollout-probe", "version": 1}
            ),
            "inputDescriptor": descriptor,
            "outputDescriptor": descriptor,
            "startupTimeoutSeconds": 10,
        },
        plan={"materialFormatChange": False},
    )


def _result_document(result) -> dict[str, object]:
    return {
        "status": result.status,
        "facts": result.facts.to_dict(),
        "details": result.details.to_dict(),
    }


def _wireplumber_adapter(owner: WyrePlumberRuntimeOwner) -> WirePlumberDriverAdapter:
    controls = WirePlumberControlRegistry()
    register_managed_link_controls(controls)
    return WirePlumberDriverAdapter(lambda: owner.connection, registry=controls)


def _remove_probe_links() -> tuple[str, ...]:
    owner = WyrePlumberRuntimeOwner()
    try:
        world = owner.start()
        adapter = _wireplumber_adapter(owner)
        removed = []
        for link in world.runtime.links:
            if (
                link.owner != OPEN_CINEMA_LINK_OWNER
                or not link.desired_id
                or not link.desired_id.startswith(_LINK_PREFIX)
            ):
                continue
            action = build_remove_managed_link_action(
                link=link,
                shape=ManagedLinkShape.PROCESSOR_INTERNAL,
                runtime_generation=world.runtime.generation,
                intent_scope="processor-rollout:cleanup",
                timeout_seconds=5,
            )
            adapter.perform(action)
            removed.append(link.desired_id)
        return tuple(sorted(removed))
    finally:
        owner.stop()


def _create_probe_links(
    decoder_request: ProcessingDriverRequest,
    camilladsp_request: ProcessingDriverRequest,
    *,
    timeout: float,
) -> tuple[tuple[str, ...], dict[str, object]]:
    decoder = DecoderInstanceConfiguration.from_request(decoder_request)
    camilladsp = CamillaDSPInstanceConfiguration.from_request(camilladsp_request)
    output_name = decoder.streams["outputNodeName"]
    input_name = camilladsp.capture_endpoint["nodeName"]
    owner = WyrePlumberRuntimeOwner()
    try:
        world = owner.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            nodes = {node.name: node for node in world.runtime.nodes}
            if output_name in nodes and input_name in nodes:
                break
            time.sleep(0.1)
            world = owner.refresh()
        else:
            raise CommandError(
                "processor PipeWire nodes did not appear before the rollout timeout"
            )
        output = nodes[output_name]
        input_ = nodes[input_name]
        adapter = _wireplumber_adapter(owner)
        created = []
        for channel, output_port, input_port in _pair_audio_ports(
            world.runtime,
            output.id,
            input_.id,
        ):
            desired_id = f"{_LINK_PREFIX}{channel}"
            action = build_managed_link_action(
                desired_link_id=desired_id,
                shape=ManagedLinkShape.PROCESSOR_INTERNAL,
                runtime_generation=world.runtime.generation,
                output_node_runtime_key=(
                    f"runtime:{world.runtime.generation}:node:{output.id}"
                ),
                output_port_runtime_key=(
                    f"runtime:{world.runtime.generation}:port:{output_port.id}"
                ),
                input_node_runtime_key=(
                    f"runtime:{world.runtime.generation}:node:{input_.id}"
                ),
                input_port_runtime_key=(
                    f"runtime:{world.runtime.generation}:port:{input_port.id}"
                ),
                properties={
                    "open-cinema.processor-stage": "rollout-probe",
                    "audio.channel": channel,
                },
                intent_scope="processor-rollout:probe",
                timeout_seconds=5,
            )
            adapter.perform(action)
            created.append(desired_id)
        return tuple(sorted(created)), {
            "runtimeGeneration": world.runtime.generation,
            "decoderOutput": {
                "stableNodeName": output_name,
                "runtimeKey": f"runtime:{world.runtime.generation}:node:{output.id}",
            },
            "camilladspCapture": {
                "stableNodeName": input_name,
                "runtimeKey": f"runtime:{world.runtime.generation}:node:{input_.id}",
            },
        }
    finally:
        owner.stop()


class Command(BaseCommand):
    help = (
        "Exercise the production CamillaDSP and decoder drivers without creating "
        "ordinary PipeWire routes."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--keep-active",
            action="store_true",
            help="Leave the owned probe instances active for runtime/UI inspection.",
        )
        parser.add_argument(
            "--cleanup-only",
            action="store_true",
            help="Stop and remove only the known owned probe instances.",
        )
        parser.add_argument("--timeout", type=float, default=15.0)

    def handle(self, *args, **options) -> None:
        get_audio_orchestration_feature_flags().require_processor_management()
        timeout = float(options["timeout"])
        if not 0 < timeout <= 60:
            raise CommandError("timeout must be greater than zero and at most 60 seconds")

        decoder_request = decoder_probe_request()
        camilladsp_request = camilladsp_probe_request()
        decoder = DecoderDriver(SystemdDecoderProcessManager())
        camilladsp = CamillaDSPDriver(SystemdCamillaDSPProcessManager())
        drivers = (
            ("decoder", decoder, decoder_request),
            ("camilladsp", camilladsp, camilladsp_request),
        )
        if options["cleanup_only"]:
            removed_links = _remove_probe_links()
            cleaned = {
                name: _result_document(driver.cleanup(request))
                for name, driver, request in drivers
            }
            self.stdout.write(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "removedManagedLinks": list(removed_links),
                        "cleanup": cleaned,
                    },
                    sort_keys=True,
                )
            )
            return

        report: dict[str, object] = {"schemaVersion": 1, "processors": {}}
        activated = []
        succeeded = False
        try:
            for name, driver, request in drivers:
                prepare = driver.prepare(request)
                activate = driver.activate(request)
                activated.append((name, driver, request))
                report["processors"][name] = {  # type: ignore[index]
                    "prepare": _result_document(prepare),
                    "activate": _result_document(activate),
                }

            created_links, runtime_identity = _create_probe_links(
                decoder_request,
                camilladsp_request,
                timeout=timeout,
            )
            report["temporaryManagedLinks"] = list(created_links)
            report["linksRetainedAfterProbe"] = False
            report["runtimeIdentity"] = runtime_identity
            for name, driver, request in drivers:
                deadline = time.monotonic() + timeout
                observed = driver.observe(request)
                while not self._ready(name, observed) and time.monotonic() < deadline:
                    time.sleep(0.1)
                    observed = driver.observe(request)
                report["processors"][name]["observe"] = _result_document(observed)  # type: ignore[index]
                if not self._ready(name, observed):
                    self.stderr.write(json.dumps(report, sort_keys=True))
                    raise CommandError(
                        f"{name} did not reach its managed readiness contract: {observed.status}"
                    )
            report["keptActive"] = bool(options["keep_active"])
            succeeded = True
            self.stdout.write(json.dumps(report, sort_keys=True))
        finally:
            if not options["keep_active"] or not succeeded:
                _remove_probe_links()
                for _name, driver, request in reversed(activated):
                    driver.cleanup(request)

    @staticmethod
    def _ready(name: str, result) -> bool:
        if name == "camilladsp":
            return result.status == "healthy" and result.facts.get("readiness") is True
        return result.status == "healthy" and result.facts.get("statusChannel") == "connected"
