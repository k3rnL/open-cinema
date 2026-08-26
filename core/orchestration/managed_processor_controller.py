from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from django.utils import timezone

from api.models import CamillaDSPProfile
from core.plugin_system.contracts import ProcessingDriverRequest, ProcessingDriverResult

from .camilladsp_config import ChannelAdaptation, generate_camilladsp_config
from .camilladsp_driver import (
    CamillaDSPDriver,
    SystemdCamillaDSPProcessManager,
)
from .camilladsp_profiles import normalize_camilladsp_profile
from .camilladsp_resources import CamillaDSPDeploymentPolicy
from .decoder_driver import (
    DecoderDriver,
    DecoderInstanceConfiguration,
    SystemdDecoderProcessManager,
)
from .feature_flags import get_audio_orchestration_feature_flags
from .processor_runtime import ProcessorNodeMatchStatus, match_managed_processor_node
from .signal_contracts import ChannelLayout
from .signal_descriptors import (
    SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
    AudioFormatDescriptor,
    SignalContentDescriptor,
    SignalContentKind,
    SignalDescriptor,
    SignalObservationSource,
    SignalObservationSourceKind,
    SignalTransportDescriptor,
    SignalTransportKind,
)

_LAYOUTS = {
    "stereo": ChannelLayout(2, ("FL", "FR")),
    "5.1-side": ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR")),
    "5.1-rear": ChannelLayout(6, ("FL", "FR", "FC", "LFE", "RL", "RR")),
    "7.1": ChannelLayout(8, ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR")),
}

logger = logging.getLogger(__name__)


class ManagedProcessorControllerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "managed-processor-controller-error",
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence = {"code": code, **dict(evidence or {})}


@dataclass(frozen=True, slots=True)
class ManagedProcessorInstance:
    node_id: str
    kind: str
    request: ProcessingDriverRequest
    driver: object
    runtime_identities: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class ManagedProcessorConvergence:
    instances: tuple[ManagedProcessorInstance, ...]
    lifecycle: tuple[dict[str, object], ...]
    runtime_replacements: tuple[ManagedProcessorInstance, ...] = ()


def _driver_result(result: ProcessingDriverResult) -> dict[str, object]:
    return {
        "status": result.status,
        "facts": result.facts.to_dict(),
        "details": result.details.to_dict(),
    }


def _resource_index(resource_id: object, kind: str) -> int:
    prefix = f"{kind}:"
    if not isinstance(resource_id, str) or not resource_id.startswith(prefix):
        raise ManagedProcessorControllerError(
            f"processor assignment requires a {kind}:<index> resource"
        )
    try:
        index = int(resource_id.removeprefix(prefix))
    except ValueError as error:
        raise ManagedProcessorControllerError(
            f"processor resource {resource_id!r} has an invalid index"
        ) from error
    if index < 0:
        raise ManagedProcessorControllerError(
            f"processor resource {resource_id!r} has an invalid index"
        )
    return index


def _decoder_output_descriptor(configuration: Mapping[str, object]) -> AudioFormatDescriptor:
    layout_name = configuration.get("workingLayout", "7.1")
    try:
        layout = _LAYOUTS[layout_name]
    except (KeyError, TypeError) as error:
        raise ManagedProcessorControllerError(
            f"decoder working layout {layout_name!r} is not supported"
        ) from error
    return AudioFormatDescriptor(
        str(configuration.get("workingSampleFormat", "FLOAT32LE")),
        int(configuration.get("workingRate", 48_000)),
        layout,
    )


def _pcm_signal(descriptor: AudioFormatDescriptor, source_id: str) -> SignalDescriptor:
    return SignalDescriptor(
        SIGNAL_DESCRIPTOR_SCHEMA_VERSION,
        SignalTransportDescriptor(SignalTransportKind.PCM, descriptor),
        SignalContentDescriptor(SignalContentKind.PCM),
        None,
        1.0,
        SignalObservationSource(
            SignalObservationSourceKind.WIREPLUMBER,
            source_id,
        ),
        timezone.now().isoformat(),
    )


def _selected_output_reference(
    processor_id: str,
    graph_nodes: Mapping[str, Mapping[str, object]],
    selected_edges: Mapping[str, Mapping[str, object]],
    selections: Mapping[str, object],
) -> str | None:
    successors: dict[str, list[str]] = {}
    for edge in selected_edges.values():
        successors.setdefault(edge["from"]["node"], []).append(edge["to"]["node"])
    pending = list(successors.get(processor_id, ()))
    visited = {processor_id}
    references: set[str] = set()
    while pending:
        node_id = pending.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = graph_nodes.get(node_id, {})
        if node.get("type") == "core.endpoint-reference":
            endpoint_id = node.get("configuration", {}).get("logicalEndpointId")
            if isinstance(endpoint_id, str) and endpoint_id:
                references.add(endpoint_id)
            continue
        decision = selections.get(node_id)
        selected = decision.get("selected") if isinstance(decision, Mapping) else None
        if isinstance(selected, list):
            for item in selected:
                if isinstance(item, Mapping):
                    reference_id = item.get("referenceId")
                    if isinstance(reference_id, str) and reference_id:
                        references.add(reference_id)
            if references:
                continue
        pending.extend(successors.get(node_id, ()))
    if len(references) > 1:
        raise ManagedProcessorControllerError(
            "limited live CamillaDSP profile selection requires one output endpoint"
        )
    return next(iter(references), None)


def _selected_profile_configuration(
    configuration: Mapping[str, object],
    output_reference: str | None,
) -> dict[str, object]:
    if "profileId" in configuration:
        return {
            "profileId": configuration.get("profileId"),
            "profileVersion": configuration.get("profileVersion"),
            "parameterBindings": configuration.get("parameterBindings", {}),
        }
    profiles = configuration.get("profiles")
    if not isinstance(profiles, list) or output_reference is None:
        raise ManagedProcessorControllerError(
            "output-specific CamillaDSP profiles require one selected output endpoint"
        )
    matches = [
        item
        for item in profiles
        if isinstance(item, Mapping) and item.get("output") == output_reference
    ]
    if len(matches) != 1:
        raise ManagedProcessorControllerError(
            f"selected output {output_reference!r} requires exactly one CamillaDSP profile"
        )
    selected = matches[0]
    return {
        "profileId": selected.get("profile"),
        "profileVersion": selected.get("profileVersion", 1),
        "parameterBindings": selected.get("parameterBindings", {}),
    }


def _profile_output_descriptor(
    profile,
    input_descriptor: AudioFormatDescriptor,
) -> AudioFormatDescriptor:
    contract = profile.output_contract

    def choose(values, current, field):
        if not values or current in values:
            return current
        if len(values) == 1:
            return values[0]
        raise ManagedProcessorControllerError(
            f"CamillaDSP output profile has ambiguous {field} choices"
        )

    layout = choose(contract.layouts, input_descriptor.layout, "channel layout")
    sample_format = choose(
        contract.sample_formats,
        input_descriptor.sample_format,
        "sample format",
    )
    rate = choose(contract.rates, input_descriptor.rate, "sample rate")
    if layout is None or sample_format is None or rate is None:
        raise ManagedProcessorControllerError(
            "CamillaDSP output profile must resolve format, rate, and channel layout"
        )
    return AudioFormatDescriptor(str(sample_format), int(rate), layout)


def _channel_adaptation(
    configuration: Mapping[str, object],
    input_descriptor: AudioFormatDescriptor,
    output_descriptor: AudioFormatDescriptor,
) -> ChannelAdaptation | None:
    if input_descriptor.layout == output_descriptor.layout:
        return None
    decision = configuration.get("channelAdaptation")
    mixer = decision.get("mixer") if isinstance(decision, Mapping) else None
    if not isinstance(mixer, str) or not mixer:
        raise ManagedProcessorControllerError(
            "CamillaDSP channel changes require a configured profile mixer"
        )
    return ChannelAdaptation(
        mixer,
        input_descriptor.layout,
        output_descriptor.layout,
        existing_mixer=True,
    )


class ManagedProcessorController:
    """Converge graph-assigned processors before persistent route mutation."""

    def __init__(
        self,
        *,
        decoder_driver: DecoderDriver | None = None,
        camilladsp_driver: CamillaDSPDriver | None = None,
        profile_loader: Callable[[object, Mapping[str, object]], object] | None = None,
        readiness_timeout_seconds: float = 20.0,
    ) -> None:
        if (
            isinstance(readiness_timeout_seconds, bool)
            or not isinstance(readiness_timeout_seconds, (int, float))
            or not 0 < readiness_timeout_seconds <= 60
        ):
            raise ValueError("readiness_timeout_seconds must be between zero and 60")
        self.decoder_driver = decoder_driver or DecoderDriver(SystemdDecoderProcessManager())
        self.camilladsp_driver = camilladsp_driver or CamillaDSPDriver(
            SystemdCamillaDSPProcessManager()
        )
        self.profile_loader = profile_loader or self._load_profile
        self.readiness_timeout_seconds = float(readiness_timeout_seconds)

    @staticmethod
    def _load_profile(activation, configuration: Mapping[str, object]):
        profile_id = configuration.get("profileId")
        profile_version = configuration.get("profileVersion")
        if not isinstance(profile_id, str) or not isinstance(profile_version, int):
            raise ManagedProcessorControllerError(
                "limited live CamillaDSP nodes require profileId and profileVersion"
            )
        try:
            model = CamillaDSPProfile.objects.get(
                profile_id=profile_id,
                version=profile_version,
                owner=activation.definition.owner,
            )
        except (CamillaDSPProfile.DoesNotExist, ValueError) as error:
            raise ManagedProcessorControllerError(
                f"CamillaDSP profile {profile_id} v{profile_version} is unavailable"
            ) from error
        return normalize_camilladsp_profile(model.content)

    def _requests(self, activation, resolved) -> tuple[ManagedProcessorInstance, ...]:
        document = resolved.document.to_dict()
        graph_nodes = {node["id"]: node for node in document["expandedGraph"].get("nodes", ())}
        assignments = document.get("resourceAssignments", {})
        selected_edges = {
            edge["id"]: edge
            for edge in document["expandedGraph"].get("edges", ())
            if edge["id"] in document["paths"]["selectedEdgeIds"]
        }
        selections = document.get("selections", {})
        decoder_descriptors: dict[str, AudioFormatDescriptor] = {}
        instances = []

        for node_id in sorted(assignments):
            node = graph_nodes[node_id]
            if node.get("type") != "processor.pcm-auto-decoder":
                continue
            index = _resource_index(assignments[node_id].get("resourceId"), "decoder")
            node_configuration = node.get("configuration", {})
            output_descriptor = _decoder_output_descriptor(node_configuration)
            request = ProcessingDriverRequest(
                node_instance_id=node_id,
                idempotency_key=f"plan:{resolved.digest}:{node_id}",
                configuration={
                    "instanceId": f"decoder-{index}",
                    "captureDescriptor": AudioFormatDescriptor(
                        "S16LE",
                        48_000,
                        _LAYOUTS["stereo"],
                    ).to_document(),
                    "outputDescriptor": output_descriptor.to_document(),
                    "detectionWindowMs": node_configuration.get("detectionWindowMs", 250),
                    "startupTimeoutSeconds": self.readiness_timeout_seconds,
                },
                plan={},
            )
            decoder_configuration = DecoderInstanceConfiguration.from_request(request)
            decoder_descriptors[node_id] = output_descriptor
            instances.append(
                ManagedProcessorInstance(
                    node_id,
                    "decoder",
                    request,
                    self.decoder_driver,
                    decoder_configuration.runtime_identities,
                )
            )

        for node_id in sorted(assignments):
            node = graph_nodes[node_id]
            if node.get("type") != "processor.camilladsp-profile-selector":
                continue
            index = _resource_index(assignments[node_id].get("resourceId"), "camilladsp")
            predecessors = [
                edge["from"]["node"]
                for edge in selected_edges.values()
                if edge["to"]["node"] == node_id
            ]
            descriptor = next(
                (
                    decoder_descriptors[predecessor]
                    for predecessor in predecessors
                    if predecessor in decoder_descriptors
                ),
                None,
            )
            if descriptor is None:
                raise ManagedProcessorControllerError(
                    "limited live CamillaDSP requires an assigned decoder immediately upstream"
                )
            node_configuration = node.get("configuration", {})
            output_reference = _selected_output_reference(
                node_id,
                graph_nodes,
                selected_edges,
                selections,
            )
            profile_configuration = _selected_profile_configuration(
                node_configuration,
                output_reference,
            )
            profile = self.profile_loader(activation, profile_configuration)
            output_descriptor = _profile_output_descriptor(profile, descriptor)
            policy = CamillaDSPDeploymentPolicy(instance_count=index + 1)
            capture, playback = policy.endpoints(index)
            generated = generate_camilladsp_config(
                profile,
                capture_endpoint=capture,
                playback_endpoint=playback,
                signal=_pcm_signal(descriptor, node_id),
                input_descriptor=descriptor,
                output_descriptor=output_descriptor,
                parameter_bindings=profile_configuration.get("parameterBindings", {}),
                channel_adaptation=_channel_adaptation(
                    node_configuration,
                    descriptor,
                    output_descriptor,
                ),
            )
            request = ProcessingDriverRequest(
                node_instance_id=node_id,
                idempotency_key=f"plan:{resolved.digest}:{node_id}",
                configuration={
                    **policy.driver_defaults(index),
                    **generated.to_driver_configuration(),
                    "startupTimeoutSeconds": self.readiness_timeout_seconds,
                },
                plan={"materialFormatChange": output_descriptor != descriptor},
            )
            instances.append(
                ManagedProcessorInstance(
                    node_id,
                    "camilladsp",
                    request,
                    self.camilladsp_driver,
                    policy.runtime_identities(index),
                )
            )
        return tuple(instances)

    def converge(self, activation, resolved) -> ManagedProcessorConvergence:
        get_audio_orchestration_feature_flags().require_processor_management()
        instances = self._requests(activation, resolved)
        lifecycle = []
        runtime_replacements = []
        for instance in instances:
            prepare = instance.driver.prepare(instance.request)
            if prepare.status not in {"prepared", "already-prepared"}:
                raise ManagedProcessorControllerError(
                    f"{instance.node_id} prepare failed: {prepare.status}"
                )
            activate = instance.driver.activate(instance.request)
            accepted = {"active", "already-active"}
            if instance.kind == "camilladsp":
                # An explicitly unlinked native capture may be stalled until the
                # route phase supplies its clock. Final readiness is checked after links.
                accepted.add("unhealthy")
            if activate.status not in accepted:
                raise ManagedProcessorControllerError(
                    f"{instance.node_id} activation failed: {activate.status}"
                )
            if activate.details.get("runtimeResourcesRecreated") is True:
                runtime_replacements.append(instance)
            lifecycle.append(
                {
                    "nodeId": instance.node_id,
                    "kind": instance.kind,
                    "prepare": _driver_result(prepare),
                    "activate": _driver_result(activate),
                }
            )
        return ManagedProcessorConvergence(
            instances,
            tuple(lifecycle),
            tuple(runtime_replacements),
        )

    @staticmethod
    def _required_port_count(
        instance: ManagedProcessorInstance,
        port_name: str,
    ) -> int:
        configuration = instance.request.configuration
        if instance.kind == "decoder":
            descriptor_name = "captureDescriptor" if port_name == "capture" else "outputDescriptor"
            descriptor = configuration.get(descriptor_name, {})
            layout = descriptor.get("layout", {}) if isinstance(descriptor, Mapping) else {}
            channels = layout.get("channels") if isinstance(layout, Mapping) else None
        elif instance.kind == "camilladsp":
            generated = configuration.get("generatedConfiguration", {})
            devices = generated.get("devices", {}) if isinstance(generated, Mapping) else {}
            device = devices.get(port_name, {}) if isinstance(devices, Mapping) else {}
            channels = device.get("channels") if isinstance(device, Mapping) else None
        else:  # pragma: no cover - instances are constructed by _requests.
            channels = None
        if isinstance(channels, bool) or not isinstance(channels, int) or channels < 1:
            raise ManagedProcessorControllerError(
                f"{instance.node_id} has no valid declared channel count for {port_name}",
                code="processor-port-contract-invalid",
                evidence={"nodeId": instance.node_id, "port": port_name},
            )
        return channels

    def runtime_instance_observation(
        self,
        world,
        instance: ManagedProcessorInstance,
    ) -> tuple[tuple[str, ...] | None, dict[str, object]]:
        keys = []
        identities = []
        ready = True
        for identity in instance.runtime_identities:
            match = match_managed_processor_node(world.runtime, identity)
            expected_ports = self._required_port_count(instance, identity.port)
            direction = "input" if identity.port == "capture" else "output"
            observed_ports = (
                tuple(
                    port.id
                    for port in world.runtime.ports
                    if match.selected is not None
                    and port.node_id == match.selected.runtime_node_id
                    and port.direction.value == direction
                )
                if match.status is ProcessorNodeMatchStatus.MATCHED
                else ()
            )
            identity_ready = bool(
                match.status is ProcessorNodeMatchStatus.MATCHED
                and match.selected is not None
                and len(observed_ports) == expected_ports
            )
            if identity_ready:
                keys.append(match.selected.runtime_key)
            ready = ready and identity_ready
            identities.append(
                {
                    "stableKey": identity.stable_key,
                    "matchStatus": match.status.value,
                    "runtimeKey": (
                        match.selected.runtime_key if match.selected is not None else None
                    ),
                    "direction": direction,
                    "expectedPortCount": expected_ports,
                    "observedPortCount": len(observed_ports),
                    "observedPortIds": list(observed_ports),
                    "ready": identity_ready,
                }
            )
        return (tuple(keys) if ready else None), {
            "nodeId": instance.node_id,
            "kind": instance.kind,
            "ready": ready,
            "identities": identities,
        }

    def runtime_instance_keys(
        self,
        world,
        instance: ManagedProcessorInstance,
    ) -> tuple[str, ...] | None:
        keys, _evidence = self.runtime_instance_observation(world, instance)
        return keys

    def runtime_instance_ready(self, world, instance: ManagedProcessorInstance) -> bool:
        return self.runtime_instance_keys(world, instance) is not None

    def runtime_resources_ready(
        self,
        world,
        instances: tuple[ManagedProcessorInstance, ...],
        *,
        replaced_runtime_keys: Mapping[str, tuple[str, ...] | None] | None = None,
    ) -> bool:
        replaced_runtime_keys = replaced_runtime_keys or {}
        for instance in instances:
            current_keys = self.runtime_instance_keys(world, instance)
            if current_keys is None:
                return False
            if (
                instance.node_id in replaced_runtime_keys
                and replaced_runtime_keys[instance.node_id] is not None
                and current_keys == replaced_runtime_keys[instance.node_id]
            ):
                return False
        return True

    def _recycle_missing_runtime_instances(
        self,
        world,
        convergence,
        *,
        replaced_runtime_keys: Mapping[str, tuple[str, ...] | None] | None = None,
    ) -> None:
        """Recycle a live process whose PipeWire objects belong to an old server.

        Some native clients keep their process and control socket alive after a
        PipeWire server restart without reconnecting their nodes.  A bounded
        stop/start is safe here because routing has not begun and only graph-
        assigned, orchestrator-owned processor instances are considered.
        """

        replaced_runtime_keys = replaced_runtime_keys or {}
        for instance in convergence.instances:
            current_keys = self.runtime_instance_keys(world, instance)
            previous_keys = replaced_runtime_keys.get(instance.node_id)
            if current_keys is not None and (
                instance.node_id not in replaced_runtime_keys
                or previous_keys is None
                or current_keys != previous_keys
            ):
                continue
            deactivate = instance.driver.deactivate(instance.request)
            if deactivate.status not in {"inactive", "already-inactive"}:
                raise ManagedProcessorControllerError(
                    f"{instance.node_id} stale-runtime recycle failed to stop: "
                    f"{deactivate.status}"
                )
            activate = instance.driver.activate(instance.request)
            accepted = {"active", "already-active"}
            if instance.kind == "camilladsp":
                accepted.add("unhealthy")
            if activate.status not in accepted:
                raise ManagedProcessorControllerError(
                    f"{instance.node_id} stale-runtime recycle failed to start: "
                    f"{activate.status}"
                )
            logger.warning(
                "Recycled managed processor %s after its PipeWire resources "
                "did not reappear in the current runtime generation.",
                instance.node_id,
            )

    def wait_for_runtime(self, initial_world, refresher, convergence):
        if not convergence.instances:
            return initial_world
        if not callable(refresher):
            raise ManagedProcessorControllerError(
                "processor startup requires an authoritative runtime refresher"
            )
        world = initial_world
        replaced_runtime_keys = {
            instance.node_id: self.runtime_instance_keys(initial_world, instance)
            for instance in convergence.runtime_replacements
        }
        if self.runtime_resources_ready(
            world,
            convergence.instances,
            replaced_runtime_keys=replaced_runtime_keys,
        ):
            # The common steady-state path must not manufacture a new runtime
            # sequence merely by taking another authoritative snapshot.
            return world
        # Give newly started instances a short registration grace period.  If
        # their stable identities remain absent, recycle them once; this is the
        # recovery path for processes stranded on a restarted PipeWire server.
        grace_deadline = time.monotonic() + min(
            1.0,
            self.readiness_timeout_seconds / 4,
        )
        while time.monotonic() < grace_deadline:
            world = refresher()
            if self.runtime_resources_ready(
                world,
                convergence.instances,
                replaced_runtime_keys=replaced_runtime_keys,
            ):
                return world
            time.sleep(0.05)
        self._recycle_missing_runtime_instances(
            world,
            convergence,
            replaced_runtime_keys=replaced_runtime_keys,
        )

        deadline = time.monotonic() + self.readiness_timeout_seconds
        while time.monotonic() < deadline:
            world = refresher()
            if self.runtime_resources_ready(
                world,
                convergence.instances,
                replaced_runtime_keys=replaced_runtime_keys,
            ):
                return world
            time.sleep(0.05)
        raise ManagedProcessorControllerError(
            "managed processor PipeWire resources did not appear before timeout",
            code="processor-runtime-resources-timeout",
            evidence={
                "processors": {
                    instance.node_id: self.runtime_instance_observation(world, instance)[1]
                    for instance in convergence.instances
                }
            },
        )

    def verify(self, convergence: ManagedProcessorConvergence) -> tuple[bool, dict[str, object]]:
        deadline = time.monotonic() + self.readiness_timeout_seconds
        observations: dict[str, object] = {}
        while time.monotonic() < deadline:
            ready = True
            for instance in convergence.instances:
                result = instance.driver.observe(instance.request)
                observations[instance.node_id] = _driver_result(result)
                if instance.kind == "camilladsp":
                    accepted = result.status == "healthy" and result.facts.get("readiness") is True
                else:
                    accepted = (
                        result.status == "healthy"
                        and result.facts.get("statusChannel") == "connected"
                        and result.facts.get("lifecycle") == "ready"
                    )
                ready = ready and accepted
            if ready:
                return True, observations
            time.sleep(0.1)
        return False, observations
