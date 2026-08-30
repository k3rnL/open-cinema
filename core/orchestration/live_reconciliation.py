from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from django.db import transaction

from core.plugin_system.contracts import ProcessingDriverRequest

from api.audio_v1.catalogue import api_node_type_registry
from api.models import (
    AppliedPlanState,
    AppliedPlanStatus,
    EndpointAudioLevel,
    GraphActivation,
    MasterAudioLevel,
    OrchestrationEvent,
    OrchestrationEventSeverity,
    ResolvedPlan,
    ResolvedPlanMode,
    TransitionStatus,
)

from .action_planning import (
    PhasedDriverAction,
    ReconciliationPhase,
    evaluate_action_verification,
)
from .feature_flags import get_audio_orchestration_feature_flags
from .idempotent_execution import (
    IdempotentActionExecutor,
    IdempotentExecutionDisposition,
)
from .managed_source_nodes import managed_source_endpoint_for_node
from .resolved_plan import ResolvedPlanOutput, effective_plan_digest, resolve_plan
from .resolution_context import build_resolver_inputs
from .camilladsp_resources import CamillaDSPDeploymentPolicy
from .decoder_driver import DecoderInstanceConfiguration
from .processor_runtime import ProcessorNodeMatchStatus, match_managed_processor_node
from .processor_topology import (
    ExpectedManagedLink,
    ProcessorTopologyExpectation,
    ProcessorTopologyVerification,
    TopologyLinkStatus,
    verify_processor_topology,
)
from .resolver_inputs import ResolverInputs, ResolverSignalFactsInput
from .runtime_world import OrchestratorWorldSnapshot
from .transition_journal import TransitionJournalStore
from .wireplumber_driver import (
    OPEN_CINEMA_LINK_OWNER,
    ManagedLinkShape,
    WirePlumberControlRegistry,
    WirePlumberDriverAdapter,
    build_managed_link_action,
    build_endpoint_mute_action,
    build_endpoint_volume_action,
    build_remove_managed_link_action,
    observe_managed_link,
    register_endpoint_audio_controls,
    register_managed_link_controls,
)


class UnsupportedLiveGraph(RuntimeError):
    """Raised when a resolved route has no safe live driver translation yet."""


class IncompleteProcessorTopology(UnsupportedLiveGraph):
    def __init__(
        self,
        *,
        node_id: str,
        edge_id: str,
        direction: str,
        expected_port_ids: set[int],
        paired_port_ids: set[int],
        expected_channels: tuple[str, ...] = (),
        paired_channels: tuple[str, ...] = (),
    ) -> None:
        missing_port_ids = tuple(sorted(expected_port_ids - paired_port_ids))
        self.evidence = {
            "code": "processor-port-contract-incomplete",
            "nodeId": node_id,
            "edgeId": edge_id,
            "direction": direction,
            "expectedPortIds": sorted(expected_port_ids),
            "pairedPortIds": sorted(paired_port_ids),
            "missingPortIds": list(missing_port_ids),
            "expectedChannels": list(expected_channels),
            "pairedChannels": list(paired_channels),
            "missingChannels": [
                channel for channel in expected_channels if channel not in paired_channels
            ],
        }
        super().__init__(
            f"Processor node {node_id!r} has an incomplete {direction} port contract "
            f"on edge {edge_id!r}; missing runtime ports {list(missing_port_ids)}."
        )


class AudioLevelUnavailable(UnsupportedLiveGraph):
    def __init__(self, code: str, message: str, **evidence: object) -> None:
        self.evidence = {"code": code, **evidence}
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LiveReconciliationResult:
    plan: ResolvedPlan
    applied: bool
    action_count: int
    transition_generation: int | None
    reason: str
    catchup_required: bool = False


@dataclass(frozen=True, slots=True)
class LiveRouteActionPlan:
    actions: tuple[PhasedDriverAction, ...]
    topology: ProcessorTopologyExpectation | None


@dataclass(frozen=True, slots=True)
class _DesiredRoute:
    desired_id: str
    edge_id: str
    channel: str
    processor_edge: bool
    ingress: bool
    downstream_depth: int
    channel_index: int
    source_node_id: int
    source_runtime_key: str
    output_port: object
    target_node_id: int
    target_runtime_key: str
    input_port: object


_CHANNEL_LAYOUTS = {
    "stereo": ("FL", "FR"),
    "5.1-side": ("FL", "FR", "FC", "LFE", "SL", "SR"),
    "5.1-rear": ("FL", "FR", "FC", "LFE", "RL", "RR"),
    "7.1": ("FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR"),
}
_UNKNOWN_CHANNELS = {"UNK", "UNKNOWN"}
_PORT_INDEX = re.compile(r"_(?P<index>[0-9]+)$")
_ENDPOINT_SELECTOR_NODE_TYPES = {
    "core.ordered-selector",
    "core.fallback-selector",
    "core.exclusive-choice",
}


def _port_runtime_key(generation: int, port_id: int) -> str:
    return f"runtime:{generation}:port:{port_id}"


def _port_channel(port) -> str | None:
    channel = port.channel or port.properties.get("audio.channel")
    if channel is None or str(channel).upper() in _UNKNOWN_CHANNELS:
        return None
    return str(channel)


def _port_sort_key(port):
    name = port.name or str(port.properties.get("port.name", ""))
    match = _PORT_INDEX.search(name)
    return (
        0 if match is not None else 1,
        int(match.group("index")) if match is not None else 0,
        name,
        port.id,
    )


def _ports_by_channel(ports, channels: tuple[str, ...]):
    labelled = {_port_channel(port): port for port in ports if _port_channel(port) is not None}
    if labelled:
        if not all(channel in labelled for channel in channels):
            raise UnsupportedLiveGraph(
                "A selected route has incomplete channel labels for its declared layout."
            )
        return {channel: labelled[channel] for channel in channels}
    if len(ports) != len(channels):
        raise UnsupportedLiveGraph(
            "A selected route has an incompatible port count for its declared layout."
        )
    return dict(zip(channels, sorted(ports, key=_port_sort_key), strict=True))


def _pair_audio_ports(
    runtime,
    output_node_id: int,
    input_node_id: int,
    *,
    channel_order: tuple[str, ...] | None = None,
    allow_channel_subset: bool = False,
):
    outputs = sorted(
        (
            port
            for port in runtime.ports
            if port.node_id == output_node_id and port.direction.value == "output"
        ),
        key=_port_sort_key,
    )
    inputs = sorted(
        (
            port
            for port in runtime.ports
            if port.node_id == input_node_id and port.direction.value == "input"
        ),
        key=_port_sort_key,
    )
    if not outputs or not inputs:
        raise UnsupportedLiveGraph("A selected endpoint route has no connectable audio ports.")

    outputs_by_channel = {
        _port_channel(port): port for port in outputs if _port_channel(port) is not None
    }
    inputs_by_channel = {
        _port_channel(port): port for port in inputs if _port_channel(port) is not None
    }
    if channel_order is not None and allow_channel_subset:
        if not outputs_by_channel and len(outputs) <= len(channel_order):
            outputs_by_channel = dict(
                zip(channel_order, sorted(outputs, key=_port_sort_key), strict=False)
            )
        if not inputs_by_channel and len(inputs) <= len(channel_order):
            inputs_by_channel = dict(
                zip(channel_order, sorted(inputs, key=_port_sort_key), strict=False)
            )
        shared_channels = tuple(
            channel
            for channel in channel_order
            if channel in outputs_by_channel and channel in inputs_by_channel
        )
        if shared_channels:
            return tuple(
                (channel, outputs_by_channel[channel], inputs_by_channel[channel])
                for channel in shared_channels
            )
    if channel_order is not None and outputs_by_channel and inputs_by_channel:
        shared_channels = tuple(
            channel
            for channel in channel_order
            if channel in outputs_by_channel and channel in inputs_by_channel
        )
        if shared_channels:
            return tuple(
                (channel, outputs_by_channel[channel], inputs_by_channel[channel])
                for channel in shared_channels
            )

    if channel_order is not None:
        outputs_by_channel = _ports_by_channel(outputs, channel_order)
        inputs_by_channel = _ports_by_channel(inputs, channel_order)
        return tuple(
            (channel, outputs_by_channel[channel], inputs_by_channel[channel])
            for channel in channel_order
        )

    shared_channels = sorted(set(outputs_by_channel).intersection(inputs_by_channel))
    if shared_channels:
        return tuple(
            (channel, outputs_by_channel[channel], inputs_by_channel[channel])
            for channel in shared_channels
        )
    if len(outputs) != len(inputs):
        raise UnsupportedLiveGraph(
            "A selected endpoint route has incompatible unlabelled channel counts."
        )
    return tuple(
        (f"channel-{index + 1}", output, input_)
        for index, (output, input_) in enumerate(zip(outputs, inputs, strict=True))
    )


def _processor_edge_channel_order(source, target, nodes, edges, selected_edge_ids):
    for node in (source, target):
        if node.get("type") != "processor.pcm-auto-decoder":
            continue
        layout = node.get("configuration", {}).get("workingLayout", "7.1")
        if layout not in _CHANNEL_LAYOUTS:
            raise UnsupportedLiveGraph(f"The decoder layout {layout!r} is not supported live.")
        return _CHANNEL_LAYOUTS[layout]
    if not any(
        node.get("type") == "processor.camilladsp-profile-selector" for node in (source, target)
    ):
        return None
    processor_ids = {source.get("id"), target.get("id")}
    for edge_id in selected_edge_ids:
        edge = edges[edge_id]
        if edge.get("to", {}).get("node") not in processor_ids:
            continue
        predecessor = nodes.get(edge.get("from", {}).get("node"), {})
        if predecessor.get("type") != "processor.pcm-auto-decoder":
            continue
        layout = predecessor.get("configuration", {}).get("workingLayout", "7.1")
        if layout not in _CHANNEL_LAYOUTS:
            raise UnsupportedLiveGraph(f"The decoder layout {layout!r} is not supported live.")
        return _CHANNEL_LAYOUTS[layout]
    raise UnsupportedLiveGraph(
        "A live CamillaDSP route has no declared upstream decoder channel layout."
    )


def _selected_edge_downstream_depths(edges, selected_edge_ids) -> dict[str, int]:
    selected = {edge_id: edges[edge_id] for edge_id in selected_edge_ids}
    successors: dict[str, list[str]] = {}
    for edge in selected.values():
        successors.setdefault(edge["from"]["node"], []).append(edge["to"]["node"])
    cache: dict[str, int] = {}

    def node_depth(node_id: str, visiting: frozenset[str] = frozenset()) -> int:
        if node_id in cache:
            return cache[node_id]
        if node_id in visiting:
            raise UnsupportedLiveGraph("The selected live route contains a cycle.")
        targets = successors.get(node_id, ())
        depth = (
            0
            if not targets
            else 1 + max(node_depth(target, visiting | {node_id}) for target in targets)
        )
        cache[node_id] = depth
        return depth

    return {edge_id: node_depth(edge["to"]["node"]) for edge_id, edge in selected.items()}


def _processor_port_ids(runtime, node_id: int, direction: str) -> set[int]:
    return {
        port.id
        for port in runtime.ports
        if port.node_id == node_id and port.direction.value == direction
    }


def _require_complete_processor_port_coverage(
    runtime,
    *,
    source,
    target,
    edge_id: str,
    source_node_id: int,
    target_node_id: int,
    pairs,
    required_channels: tuple[str, ...] | None,
) -> None:
    paired_output_ids = {output.id for _channel, output, _input in pairs}
    paired_input_ids = {input_.id for _channel, _output, input_ in pairs}
    paired_channels = tuple(channel for channel, _output, _input in pairs)
    if (
        str(source.get("type", "")).startswith("processor.")
        and str(target.get("type", "")).startswith("processor.")
        and required_channels is not None
        and set(paired_channels) != set(required_channels)
    ):
        raise IncompleteProcessorTopology(
            node_id=f"{source.get('id')}->{target.get('id')}",
            edge_id=edge_id,
            direction="processor-bus",
            expected_port_ids=_processor_port_ids(runtime, source_node_id, "output"),
            paired_port_ids=paired_output_ids,
            expected_channels=required_channels,
            paired_channels=paired_channels,
        )
    if str(source.get("type", "")).startswith("processor."):
        expected = _processor_port_ids(runtime, source_node_id, "output")
        if expected != paired_output_ids:
            raise IncompleteProcessorTopology(
                node_id=str(source.get("id")),
                edge_id=edge_id,
                direction="output",
                expected_port_ids=expected,
                paired_port_ids=paired_output_ids,
            )
    if str(target.get("type", "")).startswith("processor."):
        expected = _processor_port_ids(runtime, target_node_id, "input")
        if expected != paired_input_ids:
            raise IncompleteProcessorTopology(
                node_id=str(target.get("id")),
                edge_id=edge_id,
                direction="input",
                expected_port_ids=expected,
                paired_port_ids=paired_input_ids,
            )


def _resource_index(resource_id: object, kind: str) -> int:
    prefix = f"{kind}:"
    if not isinstance(resource_id, str) or not resource_id.startswith(prefix):
        raise UnsupportedLiveGraph(
            f"The selected {kind} processor has no compatible deployed resource."
        )
    try:
        index = int(resource_id.removeprefix(prefix))
    except ValueError as error:
        raise UnsupportedLiveGraph(f"The selected {kind} resource identity is invalid.") from error
    if index < 0:
        raise UnsupportedLiveGraph(f"The selected {kind} resource identity is invalid.")
    return index


def _processor_runtime_node(runtime, node, port_name: str, assignment):
    type_id = node.get("type")
    resource_id = assignment.get("resourceId") if isinstance(assignment, Mapping) else None
    if type_id == "processor.pcm-auto-decoder":
        index = _resource_index(resource_id, "decoder")
        configuration = DecoderInstanceConfiguration.from_request(
            ProcessingDriverRequest(
                node_instance_id=str(node["id"]),
                idempotency_key=f"runtime-identity:{node['id']}",
                configuration={"instanceId": f"decoder-{index}"},
                plan={},
            )
        )
        identity_by_port = {
            "input": configuration.runtime_identities[0],
            "output": configuration.runtime_identities[1],
        }
    elif type_id == "processor.camilladsp-profile-selector":
        index = _resource_index(resource_id, "camilladsp")
        try:
            capture, playback = CamillaDSPDeploymentPolicy(
                instance_count=index + 1
            ).runtime_identities(index)
        except ValueError as error:
            raise UnsupportedLiveGraph(str(error)) from error
        identity_by_port = {"input": capture, "output": playback}
    else:
        raise UnsupportedLiveGraph(
            f"Processor node {node.get('id')!r} has no live runtime translation."
        )
    identity = identity_by_port.get(port_name)
    if identity is None:
        raise UnsupportedLiveGraph(
            f"Processor node {node.get('id')!r} has no runtime port {port_name!r}."
        )
    match = match_managed_processor_node(runtime, identity)
    if match.status is not ProcessorNodeMatchStatus.MATCHED or match.selected is None:
        raise UnsupportedLiveGraph(
            f"Processor resource {identity.stable_key!r} is {match.status.value}."
        )
    return match.selected.runtime_node_id, match.selected.runtime_key


class LiveGraphReconciler:
    """Resolve one active graph and apply supported endpoint routes through WirePlumber."""

    def __init__(
        self,
        connection_provider: Callable[[], object],
        *,
        adapter: WirePlumberDriverAdapter | None = None,
        journal_store: TransitionJournalStore | None = None,
        registry=None,
        action_timeout_seconds: float = 5.0,
        signal_facts_provider: Callable[[], ResolverSignalFactsInput] | None = None,
        processor_controller=None,
        runtime_refresher: Callable[[], OrchestratorWorldSnapshot] | None = None,
    ) -> None:
        if not callable(connection_provider):
            raise TypeError("connection_provider must be callable")
        if adapter is None:
            controls = WirePlumberControlRegistry()
            register_managed_link_controls(controls)
            register_endpoint_audio_controls(controls)
            adapter = WirePlumberDriverAdapter(connection_provider, registry=controls)
        self.adapter = adapter
        self.journal_store = journal_store or TransitionJournalStore()
        self.executor = IdempotentActionExecutor(self.journal_store)
        self.registry = registry or api_node_type_registry()
        self.action_timeout_seconds = action_timeout_seconds
        self.signal_facts_provider = signal_facts_provider or (
            lambda: ResolverSignalFactsInput(0, {})
        )
        self.processor_controller = processor_controller
        self.runtime_refresher = runtime_refresher

    def reconcile(
        self,
        definition_id: str,
        world: OrchestratorWorldSnapshot,
        *,
        before_mutation: Callable[[ResolvedPlan], None] | None = None,
    ) -> LiveReconciliationResult:
        if not isinstance(world, OrchestratorWorldSnapshot):
            raise TypeError("world must be an OrchestratorWorldSnapshot")
        activation = GraphActivation.objects.select_related(
            "definition", "definition__owner", "revision"
        ).get(definition_id=definition_id)
        if not activation.enabled:
            return self._reconcile_deactivation(
                activation,
                world,
                before_mutation=before_mutation,
            )
        inputs = self._resolver_inputs(activation, world)
        resolved = resolve_plan(inputs, registry=self.registry)
        plan = self._persist_plan(activation, world, resolved)
        policy = resolved.document["currentPlanPolicy"]
        if not policy["mayExecuteActions"]:
            reason = str(policy["reason"])
            self._record_unapplied(plan, reason)
            return LiveReconciliationResult(plan, False, 0, None, reason)

        processor_convergence = None
        if self.processor_controller is not None:
            self._record_topology_phase(plan, "preparing-processors")
            try:
                processor_convergence = self.processor_controller.converge(
                    activation,
                    resolved,
                )
                world = self.processor_controller.wait_for_runtime(
                    world,
                    self.runtime_refresher,
                    processor_convergence,
                )
                self._record_topology_phase(
                    plan,
                    "processor-runtime-resources-ready",
                    evidence={
                        "runtimeGeneration": world.runtime.generation,
                        "runtimeSequence": world.runtime.sequence,
                        "processors": list(processor_convergence.lifecycle),
                    },
                )
            except Exception as error:
                reason = f"Managed processor convergence failed: {error}"
                self._record_topology_phase(
                    plan,
                    "processor-runtime-resources-failed",
                    evidence=getattr(error, "evidence", None),
                    severity=OrchestrationEventSeverity.ERROR,
                )
                self._record_unapplied(
                    plan,
                    reason,
                    evidence=getattr(error, "evidence", None),
                )
                return LiveReconciliationResult(plan, False, 0, None, reason)

        try:
            route_plan = self._route_actions(activation, world, resolved)
        except UnsupportedLiveGraph as error:
            reason = str(error)
            self._record_unapplied(
                plan,
                reason,
                evidence=getattr(error, "evidence", None),
            )
            return LiveReconciliationResult(plan, False, 0, None, reason)
        actions = route_plan.actions
        if route_plan.topology is not None and not callable(self.runtime_refresher):
            reason = "Managed processor topology verification requires a runtime refresher."
            self._record_unapplied(
                plan,
                reason,
                evidence={"code": "processor-topology-refresh-unavailable"},
            )
            return LiveReconciliationResult(plan, False, 0, None, reason)

        if self._is_effective_noop(plan, actions, route_plan.topology):
            self._record_noop(plan)
            return LiveReconciliationResult(
                plan,
                False,
                0,
                None,
                "The observation changed, but the effective runtime plan is already satisfied.",
            )

        return self._execute_plan(
            plan,
            actions,
            before_mutation=before_mutation,
            converge=self._converge_transition,
            success_reason="The selected endpoint routes converged.",
            post_actions_verification=(
                (lambda: self.processor_controller.verify(processor_convergence))
                if processor_convergence is not None
                else None
            ),
            verification_failure_actions=(
                (
                    lambda: self._processor_topology_cleanup_actions(
                        activation,
                        self.runtime_refresher(),
                        route_plan.topology,
                        intent_scope=f"plan:{resolved.digest}:readiness-rollback",
                    )
                )
                if route_plan.topology is not None and self.runtime_refresher is not None
                else None
            ),
            topology_expectation=route_plan.topology,
        )

    def _reconcile_deactivation(
        self,
        activation,
        world: OrchestratorWorldSnapshot,
        *,
        before_mutation: Callable[[ResolvedPlan], None] | None,
    ) -> LiveReconciliationResult:
        plan = self._persist_deactivation_plan(activation, world)
        actions = self._graph_cleanup_actions(
            activation,
            world,
            desired_ids=set(),
            intent_scope=f"deactivate:{activation.definition_id}:v{activation.desired_state_version}",
        )
        return self._execute_plan(
            plan,
            actions,
            before_mutation=before_mutation,
            converge=self._converge_deactivation,
            success_reason="The graph is inactive and its managed routes were removed.",
        )

    def _execute_plan(
        self,
        plan: ResolvedPlan,
        actions: tuple[PhasedDriverAction, ...],
        *,
        before_mutation: Callable[[ResolvedPlan], None] | None,
        converge: Callable[[AppliedPlanState, ResolvedPlan], None],
        success_reason: str,
        post_actions_verification: Callable[[], tuple[bool, Mapping[str, object]]] | None = None,
        verification_failure_actions: Callable[[], tuple[PhasedDriverAction, ...]] | None = None,
        topology_expectation: ProcessorTopologyExpectation | None = None,
    ) -> LiveReconciliationResult:
        get_audio_orchestration_feature_flags().require_audio_mutation()
        if before_mutation is not None:
            before_mutation(plan)
        state, transition_generation = self._begin_transition(plan)
        journal = self.journal_store.start(plan, generation=transition_generation)

        def fail_verification(
            *,
            code: str,
            reason: str,
            observations: Mapping[str, object],
        ) -> LiveReconciliationResult:
            nonlocal journal
            details = {
                "code": code,
                "message": reason,
                "observations": dict(observations),
            }
            rollback_succeeded = verification_failure_actions is not None
            if verification_failure_actions is not None:
                for rollback_action in verification_failure_actions():
                    rollback = self.executor.execute(
                        journal,
                        rollback_action,
                        observe=self._observe,
                        perform=self.adapter.perform,
                    )
                    journal = rollback.journal
                    if rollback.disposition is IdempotentExecutionDisposition.FAILED:
                        rollback_succeeded = False
                        break
            details["ownedLinksRemoved"] = rollback_succeeded
            self.journal_store.finish_recovery(
                journal,
                status=(
                    TransitionStatus.ROLLED_BACK if rollback_succeeded else TransitionStatus.FAILED
                ),
                summary=details,
            )
            self._fail_transition(state, plan, details)
            self._record_topology_phase(
                plan,
                "safely-suppressed" if rollback_succeeded else "recovery-failed",
                evidence=details,
                severity=(
                    OrchestrationEventSeverity.WARNING
                    if rollback_succeeded
                    else OrchestrationEventSeverity.ERROR
                ),
            )
            return LiveReconciliationResult(
                plan,
                False,
                len(actions),
                transition_generation,
                reason,
                catchup_required=True,
            )

        try:
            downstream_verified = topology_expectation is None
            ingress_activation_started = False
            for phased_action in actions:
                if (
                    topology_expectation is not None
                    and not downstream_verified
                    and phased_action.phase is ReconciliationPhase.UNSUPPRESS
                ):
                    self._record_topology_phase(plan, "verifying-downstream-topology")
                    downstream = self._verify_topology_fresh(
                        topology_expectation,
                        include_ingress=False,
                    )
                    if not downstream.satisfied:
                        return fail_verification(
                            code="processor-downstream-topology-incomplete",
                            reason=(
                                "Managed processor downstream topology did not converge; "
                                "programme ingress remained suppressed."
                            ),
                            observations=downstream.to_document(),
                        )
                    downstream_verified = True
                    self._record_topology_phase(
                        plan,
                        "downstream-topology-ready",
                        evidence=downstream.to_document(),
                    )
                if (
                    topology_expectation is not None
                    and phased_action.phase is ReconciliationPhase.UNSUPPRESS
                    and not ingress_activation_started
                ):
                    ingress_activation_started = True
                    self._record_topology_phase(plan, "activating-programme-ingress")
                result = self.executor.execute(
                    journal,
                    phased_action,
                    observe=self._observe,
                    perform=self.adapter.perform,
                )
                journal = result.journal
                if result.disposition is IdempotentExecutionDisposition.FAILED:
                    failure = result.failure
                    reason = failure.message if failure is not None else "Driver action failed."
                    details = failure.to_document() if failure is not None else {"reason": reason}
                    return fail_verification(
                        code=str(details.get("code", "driver-action-failed")),
                        reason=reason,
                        observations=details,
                    )
            if topology_expectation is not None:
                self._record_topology_phase(plan, "verifying-complete-topology")
                complete = self._verify_topology_fresh(
                    topology_expectation,
                    include_ingress=True,
                )
                if not complete.satisfied:
                    return fail_verification(
                        code="processor-topology-incomplete",
                        reason=(
                            "Managed processor topology did not converge as a complete "
                            "current-generation link set."
                        ),
                        observations=complete.to_document(),
                    )
                self._record_topology_phase(
                    plan,
                    "complete-topology-ready",
                    evidence=complete.to_document(),
                )
            if post_actions_verification is not None:
                verified, verification = post_actions_verification()
                if not verified:
                    reason = "Managed processors did not satisfy post-route readiness."
                    return fail_verification(
                        code="processor-post-route-readiness-failed",
                        reason=reason,
                        observations=verification,
                    )
            self.journal_store.complete(journal)
            converge(state, plan)
        except Exception as error:
            current = type(journal).objects.get(pk=journal.pk)
            if current.status in {TransitionStatus.PENDING, TransitionStatus.RUNNING}:
                self.journal_store.finish_recovery(
                    current,
                    status=TransitionStatus.FAILED,
                    summary={"exception": type(error).__name__, "message": str(error)},
                )
            self._fail_transition(
                state,
                plan,
                {"exception": type(error).__name__, "message": str(error)},
            )
            raise
        return LiveReconciliationResult(
            plan,
            True,
            len(actions),
            transition_generation,
            success_reason,
            catchup_required=bool(actions),
        )

    def _resolver_inputs(self, activation, world) -> ResolverInputs:
        return build_resolver_inputs(
            activation,
            world,
            signal_facts_provider=self.signal_facts_provider,
        )

    @staticmethod
    def _persist_plan(activation, world, resolved: ResolvedPlanOutput) -> ResolvedPlan:
        return ResolvedPlan.objects.create(
            graph_definition=activation.definition,
            graph_revision=activation.revision,
            desired_state_version=activation.desired_state_version,
            world_generation=world.runtime.generation,
            world_sequence=world.runtime.sequence,
            resolution_mode=ResolvedPlanMode.LIVE,
            status=resolved.status.value,
            document=resolved.document.to_dict(),
            explanation=resolved.explanation.to_dict(),
        )

    @staticmethod
    def _persist_deactivation_plan(activation, world) -> ResolvedPlan:
        return ResolvedPlan.objects.create(
            graph_definition=activation.definition,
            graph_revision=activation.revision,
            desired_state_version=activation.desired_state_version,
            world_generation=world.runtime.generation,
            world_sequence=world.runtime.sequence,
            resolution_mode=ResolvedPlanMode.LIVE,
            status="resolved",
            document={
                "kind": "graph-deactivation",
                "activation": {
                    "definitionId": str(activation.definition_id),
                    "enabled": False,
                    "desiredStateVersion": activation.desired_state_version,
                },
                "world": {
                    "version": f"{world.runtime.generation}:{world.runtime.sequence}",
                    "runtimeGeneration": world.runtime.generation,
                    "runtimeSequence": world.runtime.sequence,
                },
                "paths": {"selectedEdgeIds": []},
            },
            explanation={
                "kind": "graph-deactivation",
                "status": "resolved",
                "summary": "The graph no longer contributes desired runtime routes.",
            },
        )

    def _route_actions(
        self,
        activation,
        world,
        resolved: ResolvedPlanOutput,
    ) -> LiveRouteActionPlan:
        document = resolved.document.to_dict()
        graph = document["expandedGraph"]
        nodes = {node["id"]: node for node in graph.get("nodes", [])}
        edges = {edge["id"]: edge for edge in graph.get("edges", [])}
        selections = document.get("selections", {})
        bindings = {
            item["logicalEndpointId"]: item["runtimeKey"]
            for item in document.get("endpointBindings", [])
        }
        candidates = {candidate.runtime_key: candidate for candidate in world.endpoints.candidates}
        assignments = document.get("resourceAssignments", {})
        selected_edge_ids = document["paths"]["selectedEdgeIds"]
        downstream_depths = _selected_edge_downstream_depths(edges, selected_edge_ids)
        desired_routes: list[_DesiredRoute] = []
        for edge_id in selected_edge_ids:
            edge = edges[edge_id]
            source = nodes[edge["from"]["node"]]
            target = nodes[edge["to"]["node"]]
            source_node_id, source_runtime_key = self._runtime_edge_node(
                source,
                edge["from"]["port"],
                world,
                assignments,
                bindings,
                candidates,
                selections,
                edge_role="source",
                registry=self.registry,
            )
            target_node_id, target_runtime_key = self._runtime_edge_node(
                target,
                edge["to"]["port"],
                world,
                assignments,
                bindings,
                candidates,
                selections,
                edge_role="target",
                registry=self.registry,
            )
            source_is_processor = source.get("type", "").startswith("processor.")
            target_is_processor = target.get("type", "").startswith("processor.")
            pairs = _pair_audio_ports(
                world.runtime,
                source_node_id,
                target_node_id,
                channel_order=_processor_edge_channel_order(
                    source,
                    target,
                    nodes,
                    edges,
                    selected_edge_ids,
                ),
                allow_channel_subset=not (source_is_processor and target_is_processor),
            )
            if source_is_processor or target_is_processor:
                _require_complete_processor_port_coverage(
                    world.runtime,
                    source=source,
                    target=target,
                    edge_id=edge_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    pairs=pairs,
                    required_channels=_processor_edge_channel_order(
                        source,
                        target,
                        nodes,
                        edges,
                        selected_edge_ids,
                    ),
                )
            for channel_index, (channel, output_port, input_port) in enumerate(pairs):
                desired_id = f"{activation.definition_id}:{edge_id}:{channel}"
                processor_edge = source_is_processor or target_is_processor
                desired_routes.append(
                    _DesiredRoute(
                        desired_id=desired_id,
                        edge_id=edge_id,
                        channel=channel,
                        processor_edge=processor_edge,
                        ingress=not source_is_processor and target_is_processor,
                        downstream_depth=downstream_depths[edge_id],
                        channel_index=channel_index,
                        source_node_id=source_node_id,
                        source_runtime_key=source_runtime_key,
                        output_port=output_port,
                        target_node_id=target_node_id,
                        target_runtime_key=target_runtime_key,
                        input_port=input_port,
                    )
                )

        desired_ids = {route.desired_id for route in desired_routes}
        graph_prefix = f"{activation.definition_id}:"

        def existing_links(route: _DesiredRoute):
            return tuple(
                link
                for link in world.runtime.links
                if link.owner == OPEN_CINEMA_LINK_OWNER and link.desired_id == route.desired_id
            )

        def expected_endpoints(route: _DesiredRoute):
            return (
                route.source_node_id,
                route.output_port.id,
                route.target_node_id,
                route.input_port.id,
            )

        downstream_requires_mutation = any(
            len(existing_links(route)) != 1
            or (
                existing_links(route)[0].output_node_id,
                existing_links(route)[0].output_port_id,
                existing_links(route)[0].input_node_id,
                existing_links(route)[0].input_port_id,
            )
            != expected_endpoints(route)
            for route in desired_routes
            if route.processor_edge and not route.ingress
        )

        suppressed_ids: set[str] = set()
        suppress_actions: list[PhasedDriverAction] = []
        route_actions: list[tuple[_DesiredRoute, PhasedDriverAction]] = []
        ingress_actions: list[tuple[_DesiredRoute, PhasedDriverAction]] = []
        for route in desired_routes:
            desired_id = route.desired_id
            processor_edge = route.processor_edge
            existing = tuple(
                link
                for link in world.runtime.links
                if link.owner == OPEN_CINEMA_LINK_OWNER and link.desired_id == desired_id
            )
            if len(existing) > 1:
                raise UnsupportedLiveGraph(
                    f"Managed route {desired_id!r} has conflicting runtime owners."
                )
            endpoints = expected_endpoints(route)
            topology_conflicts = tuple(
                link
                for link in world.runtime.links
                if link.owner == OPEN_CINEMA_LINK_OWNER
                and link.desired_id
                and link.desired_id.startswith(graph_prefix)
                and link.desired_id not in desired_ids
                and (
                    link.output_node_id,
                    link.output_port_id,
                    link.input_node_id,
                    link.input_port_id,
                )
                == endpoints
            )
            for conflict in topology_conflicts:
                if conflict.desired_id in suppressed_ids:
                    continue
                suppress_actions.append(
                    PhasedDriverAction(
                        ReconciliationPhase.SUPPRESS,
                        build_remove_managed_link_action(
                            link=conflict,
                            shape=(
                                ManagedLinkShape.PROCESSOR_INTERNAL
                                if processor_edge
                                else ManagedLinkShape.ENDPOINT_ROUTE
                            ),
                            runtime_generation=world.runtime.generation,
                            intent_scope=f"plan:{resolved.digest}:replace-identity",
                            timeout_seconds=self.action_timeout_seconds,
                        ),
                    )
                )
                suppressed_ids.add(conflict.desired_id)
            existing_endpoints = (
                (
                    existing[0].output_node_id,
                    existing[0].output_port_id,
                    existing[0].input_node_id,
                    existing[0].input_port_id,
                )
                if existing
                else None
            )
            suppress_existing = bool(
                existing
                and (
                    existing_endpoints != endpoints
                    or (route.ingress and downstream_requires_mutation)
                )
            )
            if suppress_existing and desired_id not in suppressed_ids:
                suppress_actions.append(
                    PhasedDriverAction(
                        ReconciliationPhase.SUPPRESS,
                        build_remove_managed_link_action(
                            link=existing[0],
                            shape=(
                                ManagedLinkShape.PROCESSOR_INTERNAL
                                if processor_edge
                                else ManagedLinkShape.ENDPOINT_ROUTE
                            ),
                            runtime_generation=world.runtime.generation,
                            intent_scope=f"plan:{resolved.digest}:replace-route",
                            timeout_seconds=self.action_timeout_seconds,
                        ),
                    )
                )
                suppressed_ids.add(desired_id)
            action = build_managed_link_action(
                desired_link_id=desired_id,
                shape=(
                    ManagedLinkShape.PROCESSOR_INTERNAL
                    if processor_edge
                    else ManagedLinkShape.ENDPOINT_ROUTE
                ),
                runtime_generation=world.runtime.generation,
                output_node_runtime_key=route.source_runtime_key,
                output_port_runtime_key=_port_runtime_key(
                    world.runtime.generation, route.output_port.id
                ),
                input_node_runtime_key=route.target_runtime_key,
                input_port_runtime_key=_port_runtime_key(
                    world.runtime.generation, route.input_port.id
                ),
                properties={
                    "open-cinema.graph-definition": str(activation.definition_id),
                    "open-cinema.graph-edge": route.edge_id,
                    "audio.channel": route.channel,
                },
                intent_scope=f"plan:{resolved.digest}",
                timeout_seconds=self.action_timeout_seconds,
            )
            phased = PhasedDriverAction(
                ReconciliationPhase.UNSUPPRESS if route.ingress else ReconciliationPhase.ROUTE,
                action,
            )
            (ingress_actions if route.ingress else route_actions).append((route, phased))

        cleanup_actions = self._graph_cleanup_actions(
            activation,
            world,
            desired_ids=desired_ids,
            intent_scope=f"plan:{resolved.digest}",
            excluded_desired_ids=suppressed_ids,
        )
        suppress_actions.sort(key=lambda item: item.action.identity.resource_id)
        route_actions.sort(
            key=lambda item: (
                item[0].downstream_depth,
                item[0].edge_id,
                item[0].channel_index,
                item[0].desired_id,
            )
        )
        ingress_actions.sort(
            key=lambda item: (
                -item[0].downstream_depth,
                item[0].edge_id,
                item[0].channel_index,
                item[0].desired_id,
            )
        )
        level_actions = self._audio_level_actions(
            graph=graph,
            edges=edges,
            selected_edge_ids=selected_edge_ids,
            selections=selections,
            bindings=bindings,
            candidates=candidates,
            plan_digest=resolved.digest,
        )
        actions = (
            *suppress_actions,
            *level_actions,
            *(item[1] for item in route_actions),
            *(item[1] for item in ingress_actions),
            *cleanup_actions,
        )
        expected_links = tuple(
            ExpectedManagedLink(
                desired_id=route.desired_id,
                edge_id=route.edge_id,
                channel=route.channel,
                runtime_generation=world.runtime.generation,
                output_node_id=route.source_node_id,
                output_port_id=route.output_port.id,
                input_node_id=route.target_node_id,
                input_port_id=route.input_port.id,
                processor_edge=route.processor_edge,
                ingress=route.ingress,
            )
            for route in desired_routes
            if route.processor_edge
        )
        topology = (
            ProcessorTopologyExpectation(
                str(activation.definition_id),
                world.runtime.generation,
                expected_links,
            )
            if expected_links
            else None
        )
        return LiveRouteActionPlan(tuple(actions), topology)

    def _audio_level_actions(
        self,
        *,
        graph,
        edges,
        selected_edge_ids,
        selections,
        bindings,
        candidates,
        plan_digest: str,
    ) -> tuple[PhasedDriverAction, ...]:
        nodes = {node["id"]: node for node in graph.get("nodes", ())}

        def endpoint_id(node, role: str) -> str | None:
            managed_source_id = managed_source_endpoint_for_node(node, self.registry)
            if managed_source_id is not None:
                return managed_source_id if role == "source" else None
            if node.get("type") == "core.endpoint-reference":
                value = node.get("configuration", {}).get("logicalEndpointId")
                return value if isinstance(value, str) and value else None
            if node.get("type") in _ENDPOINT_SELECTOR_NODE_TYPES:
                decision = selections.get(node.get("id"))
                selected = decision.get("selected") if isinstance(decision, Mapping) else None
                if not isinstance(selected, list) or len(selected) != 1:
                    return None
                value = selected[0].get("referenceId")
                return value if isinstance(value, str) and value else None
            return None

        active: dict[str, str] = {}
        for edge_id in selected_edge_ids:
            edge = edges[edge_id]
            for role, side, direction in (
                ("source", "from", "input"),
                ("target", "to", "output"),
            ):
                selected_id = endpoint_id(nodes[edge[side]["node"]], role)
                candidate = candidates.get(bindings.get(selected_id))
                if (
                    selected_id is not None
                    and candidate is not None
                    and candidate.direction.value == direction
                ):
                    active[selected_id] = direction

        master = MasterAudioLevel.objects.filter(pk=1).first()
        endpoint_values = {
            str(item.endpoint_id): item
            for item in EndpointAudioLevel.objects.filter(endpoint_id__in=bindings)
        }
        # Explicit endpoint preferences remain actionable while an available
        # endpoint is not selected by the current route. This is especially
        # important for inputs: muting a source can make an activity selector
        # fall back, but the user must still be able to unmute that source.
        for logical_id in endpoint_values:
            candidate = candidates.get(bindings.get(logical_id))
            if candidate is not None:
                active.setdefault(logical_id, candidate.direction.value)
        if not active:
            return ()
        actions = []
        for logical_id, direction in sorted(active.items()):
            endpoint_value = endpoint_values.get(logical_id)
            if endpoint_value is None and (master is None or direction == "input"):
                continue
            candidate = candidates.get(bindings.get(logical_id))
            if candidate is None:
                raise AudioLevelUnavailable(
                    "audio-level-endpoint-unavailable",
                    "An active logical endpoint disappeared before its audio level could apply.",
                    endpointId=logical_id,
                )
            endpoint_level = endpoint_value.level if endpoint_value is not None else 1.0
            endpoint_muted = endpoint_value.muted if endpoint_value is not None else False
            desired_level = endpoint_level
            desired_muted = endpoint_muted
            if direction == "output" and master is not None:
                desired_level *= master.level
                desired_muted = desired_muted or master.muted
            if candidate.volume is None or candidate.mute is None:
                raise AudioLevelUnavailable(
                    "audio-level-observation-unknown",
                    "An active endpoint does not expose enough observed audio state for safe control.",
                    endpointId=logical_id,
                    runtimeKey=candidate.runtime_key,
                )
            if abs(float(candidate.volume) - float(desired_level)) > 0.0001:
                if not candidate.volume_writable:
                    raise AudioLevelUnavailable(
                        "audio-level-volume-read-only",
                        "The active endpoint volume differs from desired state but is read-only.",
                        endpointId=logical_id,
                        requested=desired_level,
                        observed=candidate.volume,
                    )
                actions.append(
                    PhasedDriverAction(
                        ReconciliationPhase.CONFIGURE,
                        build_endpoint_volume_action(
                            logical_endpoint_id=logical_id,
                            candidate=candidate,
                            volume=desired_level,
                            intent_scope=f"plan:{plan_digest}:audio-level",
                            timeout_seconds=self.action_timeout_seconds,
                        ),
                    )
                )
            if candidate.mute is not desired_muted:
                if not candidate.mute_writable:
                    raise AudioLevelUnavailable(
                        "audio-level-mute-read-only",
                        "The active endpoint mute differs from desired state but is read-only.",
                        endpointId=logical_id,
                        requested=desired_muted,
                        observed=candidate.mute,
                    )
                actions.append(
                    PhasedDriverAction(
                        ReconciliationPhase.CONFIGURE,
                        build_endpoint_mute_action(
                            logical_endpoint_id=logical_id,
                            candidate=candidate,
                            mute=desired_muted,
                            intent_scope=f"plan:{plan_digest}:audio-level",
                            timeout_seconds=self.action_timeout_seconds,
                        ),
                    )
                )
        return tuple(actions)

    @staticmethod
    def _runtime_edge_node(
        node,
        port_name: str,
        world: OrchestratorWorldSnapshot,
        assignments,
        bindings,
        candidates,
        selections,
        *,
        edge_role: str,
        registry=None,
    ) -> tuple[int, str]:
        managed_source_id = (
            managed_source_endpoint_for_node(node, registry) if registry is not None else None
        )
        if managed_source_id is not None:
            candidate = candidates.get(bindings.get(managed_source_id))
            if candidate is None:
                raise UnsupportedLiveGraph(
                    f"Managed source node {node.get('id')!r} no longer has a runtime match."
                )
            if (
                edge_role != "source"
                or port_name != "audio"
                or candidate.direction.value != "input"
            ):
                raise UnsupportedLiveGraph(
                    f"Managed source node {node.get('id')!r} cannot translate port "
                    f"{port_name!r} as an {edge_role} endpoint."
                )
            return candidate.runtime.node_id, candidate.runtime_key
        if node.get("type") == "core.endpoint-reference":
            endpoint_id = node.get("configuration", {}).get("logicalEndpointId")
            candidate = candidates.get(bindings.get(endpoint_id))
            if candidate is None:
                raise UnsupportedLiveGraph(
                    f"Endpoint node {node.get('id')!r} no longer has a runtime match."
                )
            return candidate.runtime.node_id, candidate.runtime_key
        if node.get("type") in _ENDPOINT_SELECTOR_NODE_TYPES:
            decision = selections.get(node.get("id"))
            selected = decision.get("selected") if isinstance(decision, Mapping) else None
            if not isinstance(selected, list) or len(selected) != 1:
                raise UnsupportedLiveGraph(
                    f"Selector node {node.get('id')!r} has no single live endpoint selection."
                )
            endpoint_id = selected[0].get("referenceId")
            candidate = candidates.get(bindings.get(endpoint_id))
            if candidate is None:
                raise UnsupportedLiveGraph(
                    f"Selector node {node.get('id')!r} selected an unavailable endpoint."
                )
            expected_direction = "input" if edge_role == "source" else "output"
            expected_port = "audio" if edge_role == "source" else "input"
            if port_name != expected_port or candidate.direction.value != expected_direction:
                raise UnsupportedLiveGraph(
                    f"Selector node {node.get('id')!r} cannot translate port {port_name!r} "
                    f"as an {edge_role} endpoint."
                )
            return candidate.runtime.node_id, candidate.runtime_key
        if str(node.get("type", "")).startswith("processor."):
            return _processor_runtime_node(
                world.runtime,
                node,
                port_name,
                assignments.get(node.get("id")),
            )
        raise UnsupportedLiveGraph(f"Node {node.get('id')!r} has no live runtime translation.")

    def _graph_cleanup_actions(
        self,
        activation,
        world: OrchestratorWorldSnapshot,
        *,
        desired_ids: set[str],
        intent_scope: str,
        excluded_desired_ids: set[str] | None = None,
    ) -> tuple[PhasedDriverAction, ...]:
        graph_prefix = f"{activation.definition_id}:"
        excluded_desired_ids = excluded_desired_ids or set()
        actions = []
        for link in world.runtime.links:
            if (
                link.owner == OPEN_CINEMA_LINK_OWNER
                and link.desired_id
                and link.desired_id.startswith(graph_prefix)
                and link.desired_id not in desired_ids
                and link.desired_id not in excluded_desired_ids
            ):
                action = build_remove_managed_link_action(
                    link=link,
                    shape=ManagedLinkShape.ENDPOINT_ROUTE,
                    runtime_generation=world.runtime.generation,
                    intent_scope=intent_scope,
                    timeout_seconds=self.action_timeout_seconds,
                )
                actions.append(PhasedDriverAction(ReconciliationPhase.CLEANUP, action))
        return tuple(sorted(actions, key=lambda item: item.action.identity.resource_id))

    def _processor_topology_cleanup_actions(
        self,
        activation,
        world: OrchestratorWorldSnapshot,
        topology: ProcessorTopologyExpectation,
        *,
        intent_scope: str,
    ) -> tuple[PhasedDriverAction, ...]:
        desired_ids = {link.desired_id for link in topology.processor_links}
        actions = []
        for link in world.runtime.links:
            if link.owner != OPEN_CINEMA_LINK_OWNER or link.desired_id not in desired_ids:
                continue
            action = build_remove_managed_link_action(
                link=link,
                shape=ManagedLinkShape.PROCESSOR_INTERNAL,
                runtime_generation=world.runtime.generation,
                intent_scope=intent_scope,
                timeout_seconds=self.action_timeout_seconds,
            )
            actions.append(PhasedDriverAction(ReconciliationPhase.CLEANUP, action))
        return tuple(sorted(actions, key=lambda item: item.action.identity.resource_id))

    def _observe(self, action) -> Mapping[str, object]:
        if action.command.operation in {"set-endpoint-volume", "set-endpoint-mute"}:
            return self.adapter.observe_endpoint_controls(
                action.identity.resource_id,
                str(action.command.arguments["runtimeKey"]),
            )
        return observe_managed_link(self.adapter, action.identity.resource_id)

    def _verify_topology_fresh(
        self,
        topology: ProcessorTopologyExpectation,
        *,
        include_ingress: bool,
    ) -> ProcessorTopologyVerification:
        if not callable(self.runtime_refresher):
            raise RuntimeError("processor topology verification requires a runtime refresher")
        deadline = time.monotonic() + self.action_timeout_seconds
        while True:
            world = self.runtime_refresher()
            verification = verify_processor_topology(
                world.runtime,
                topology,
                include_ingress=include_ingress,
            )
            if verification.satisfied:
                return verification
            statuses = {item.status for item in verification.links}
            if (
                TopologyLinkStatus.STALE_GENERATION in statuses
                or TopologyLinkStatus.DUPLICATE in statuses
                or TopologyLinkStatus.ENDPOINT_MISMATCH in statuses
                or time.monotonic() >= deadline
            ):
                return verification
            time.sleep(0.05)

    def _is_effective_noop(
        self,
        plan: ResolvedPlan,
        actions: tuple[PhasedDriverAction, ...],
        topology: ProcessorTopologyExpectation | None = None,
    ) -> bool:
        state = (
            AppliedPlanState.objects.select_related("current_plan")
            .filter(graph_definition=plan.graph_definition)
            .first()
        )
        if (
            state is None
            or state.current_plan is None
            or state.status != AppliedPlanStatus.CONVERGED
        ):
            return False
        try:
            same_intent = effective_plan_digest(
                state.current_plan.document
            ) == effective_plan_digest(plan.document)
        except (TypeError, ValueError):
            return False
        if not same_intent:
            return False
        if topology is not None:
            verification = self._verify_topology_fresh(
                topology,
                include_ingress=True,
            )
            if not verification.satisfied:
                return False
        return all(
            evaluate_action_verification(phased.action, self._observe(phased.action))[0]
            for phased in actions
        )

    @staticmethod
    def _record_noop(plan: ResolvedPlan) -> None:
        with transaction.atomic():
            state = AppliedPlanState.objects.select_for_update().get(
                graph_definition=plan.graph_definition
            )
            previous = state.current_plan
            if previous is not None and previous.pk != plan.pk:
                state.previous_plan = previous
            state.current_plan = plan
            state.status = AppliedPlanStatus.CONVERGED
            state.correlation_id = plan.correlation_id
            state.last_error = None
            state.full_clean()
            state.save()
            OrchestrationEvent.objects.create(
                correlation_id=plan.correlation_id,
                graph_definition=plan.graph_definition,
                event_type="reconciliation-noop",
                severity=OrchestrationEventSeverity.INFO,
                payload={
                    "resolvedPlanId": str(plan.pk),
                    "previousPlanId": str(previous.pk) if previous is not None else None,
                    "effectivePlanDigest": effective_plan_digest(plan.document),
                    "reason": "effective-runtime-intent-unchanged-and-satisfied",
                },
            )

    @staticmethod
    def _record_unapplied(
        plan: ResolvedPlan,
        reason: str,
        *,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        state, _ = AppliedPlanState.objects.get_or_create(
            graph_definition=plan.graph_definition,
        )
        state.status = AppliedPlanStatus.DEGRADED
        state.correlation_id = plan.correlation_id
        state.last_error = {
            "code": (
                str(evidence.get("code"))
                if evidence is not None and evidence.get("code")
                else "live-plan-not-executable"
            ),
            "message": reason,
            "resolvedPlanId": str(plan.pk),
            **({"evidence": dict(evidence)} if evidence is not None else {}),
        }
        state.full_clean()
        state.save()

    @staticmethod
    def _record_topology_phase(
        plan: ResolvedPlan,
        phase: str,
        *,
        evidence: Mapping[str, object] | None = None,
        severity=OrchestrationEventSeverity.INFO,
    ) -> None:
        payload = {
            "phase": phase,
            "resolvedPlanId": str(plan.pk),
            "runtimeGeneration": plan.world_generation,
            "runtimeSequence": plan.world_sequence,
        }
        if evidence is not None:
            payload["evidence"] = dict(evidence)
        OrchestrationEvent.objects.create(
            correlation_id=plan.correlation_id,
            graph_definition=plan.graph_definition,
            event_type="processor-topology-transition",
            severity=severity,
            payload=payload,
        )

    @staticmethod
    def _begin_transition(plan: ResolvedPlan):
        with transaction.atomic():
            state, _ = AppliedPlanState.objects.select_for_update().get_or_create(
                graph_definition=plan.graph_definition,
            )
            state.transition_generation += 1
            state.status = AppliedPlanStatus.APPLYING
            state.correlation_id = plan.correlation_id
            state.last_error = None
            state.full_clean()
            state.save()
            return state, state.transition_generation

    @staticmethod
    def _fail_transition(state: AppliedPlanState, plan: ResolvedPlan, error) -> None:
        with transaction.atomic():
            current = AppliedPlanState.objects.select_for_update().get(pk=state.pk)
            current.status = AppliedPlanStatus.FAILED
            current.correlation_id = plan.correlation_id
            current.last_error = dict(error)
            current.full_clean()
            current.save()

    @staticmethod
    def _converge_transition(state: AppliedPlanState, plan: ResolvedPlan) -> None:
        with transaction.atomic():
            current = AppliedPlanState.objects.select_for_update().get(pk=state.pk)
            if current.current_plan_id != plan.pk:
                current.previous_plan = current.current_plan
                current.current_plan = plan
            current.status = AppliedPlanStatus.CONVERGED
            current.correlation_id = plan.correlation_id
            current.last_error = None
            current.full_clean()
            current.save()

    @staticmethod
    def _converge_deactivation(state: AppliedPlanState, plan: ResolvedPlan) -> None:
        with transaction.atomic():
            current = AppliedPlanState.objects.select_for_update().get(pk=state.pk)
            if current.current_plan_id is not None:
                current.previous_plan = current.current_plan
            current.current_plan = None
            current.status = AppliedPlanStatus.IDLE
            current.correlation_id = plan.correlation_id
            current.last_error = None
            current.full_clean()
            current.save()
