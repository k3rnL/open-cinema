from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from enum import StrEnum

from wyreplumber.runtime import (
    FrozenDict,
    LinkValue,
    MutationFailureCode,
    MutationOutcome,
    MutationStatus,
    RuntimeSnapshot,
    capture_runtime_snapshot,
    require_orchestration_contract,
)

from .driver_actions import (
    ActionAssertionOperator,
    ActionFailure,
    ActionFailureClassification,
    ActionPrecondition,
    ActionRecoveryMode,
    ActionRecoveryPolicy,
    ActionRecoveryStep,
    ActionVerification,
    DriverAction,
    DriverActionIdentity,
    DriverActionError,
    DriverCommand,
)
from .endpoint_inventory import (
    EndpointProfileSummary,
    EndpointRouteSummary,
    RuntimeEndpointCandidate,
    map_runtime_endpoints,
)

WirePlumberControlHandler = Callable[[object, DriverAction, RuntimeSnapshot], MutationOutcome]


class WirePlumberControlRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, WirePlumberControlHandler] = {}

    def register(self, operation: str, handler: WirePlumberControlHandler) -> None:
        if not isinstance(operation, str) or not operation:
            raise ValueError("WirePlumber operation must be a non-empty string")
        if not callable(handler):
            raise TypeError("WirePlumber control handler must be callable")
        if operation in self._handlers:
            raise ValueError(f"WirePlumber operation {operation!r} is already registered")
        self._handlers[operation] = handler

    def handler(self, operation: str) -> WirePlumberControlHandler | None:
        return self._handlers.get(operation)

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


_STALE_CODES = {
    MutationFailureCode.STALE_GENERATION,
    MutationFailureCode.STALE_SEQUENCE,
    MutationFailureCode.TARGET_NOT_FOUND,
    MutationFailureCode.TARGET_IDENTITY_CHANGED,
}
_DEPENDENCY_CODES = {
    MutationFailureCode.TARGET_UNAVAILABLE,
    MutationFailureCode.GENERATION_LOST,
    MutationFailureCode.RUNTIME_STOPPED,
}
_SAFETY_CODES = {
    MutationFailureCode.OWNERSHIP_CONFLICT,
}
_TRANSIENT_CODES = {
    MutationFailureCode.NATIVE_REJECTED,
    MutationFailureCode.CONFIRMATION_TIMEOUT,
    MutationFailureCode.DEADLINE_EXPIRED,
    MutationFailureCode.CALLER_CANCELLED,
    MutationFailureCode.INTERNAL_ERROR,
}


def classify_wireplumber_failure(code: MutationFailureCode) -> ActionFailureClassification:
    code = MutationFailureCode(code)
    if code in _STALE_CODES:
        return ActionFailureClassification.STALE_PRECONDITION
    if code in _DEPENDENCY_CODES:
        return ActionFailureClassification.DEPENDENCY
    if code in _SAFETY_CODES:
        return ActionFailureClassification.SAFETY
    if code in _TRANSIENT_CODES:
        return ActionFailureClassification.TRANSIENT
    return ActionFailureClassification.PERMANENT


class WirePlumberDriverAdapter:
    """Translate detached driver actions at the released binding boundary."""

    DRIVER_ID = "wireplumber"
    _MAX_STALE_SEQUENCE_RETRIES = 4

    def __init__(
        self,
        connection_provider: Callable[[], object],
        *,
        registry: WirePlumberControlRegistry | None = None,
        snapshot_capture: Callable[[object], RuntimeSnapshot] = capture_runtime_snapshot,
        contract_checker: Callable[[int, int], object] = require_orchestration_contract,
    ) -> None:
        if not callable(connection_provider):
            raise TypeError("connection_provider must be callable")
        if not callable(snapshot_capture) or not callable(contract_checker):
            raise TypeError("snapshot_capture and contract_checker must be callable")
        self.connection_provider = connection_provider
        self.registry = registry or WirePlumberControlRegistry()
        if not isinstance(self.registry, WirePlumberControlRegistry):
            raise TypeError("registry must be a WirePlumberControlRegistry")
        self.snapshot_capture = snapshot_capture
        self.contract_info = contract_checker(1, 1)

    def observe_runtime(self) -> RuntimeSnapshot:
        connection = self.connection_provider()
        snapshot = self.snapshot_capture(connection)
        if not isinstance(snapshot, RuntimeSnapshot):
            raise TypeError("WyrePlumber snapshot capture must return RuntimeSnapshot")
        return snapshot

    @staticmethod
    def _failure_from_outcome(outcome: MutationOutcome) -> ActionFailure:
        failure = outcome.failure
        if failure is None:  # pragma: no cover - enforced by MutationOutcome.
            raise ValueError("unsuccessful WyrePlumber outcome lacks failure details")
        return ActionFailure(
            classification=classify_wireplumber_failure(failure.code),
            code=f"wireplumber:{failure.code.value}",
            message=failure.message,
            details={
                "bindingPhase": failure.phase.value,
                "bindingStatus": outcome.status.value,
                "bindingRetryable": failure.retryable,
                "bindingDetails": failure.details.to_dict(),
                "requestId": outcome.request_id,
                "generation": outcome.generation,
            },
        )

    def perform(self, action: DriverAction) -> Mapping[str, object]:
        if not isinstance(action, DriverAction):
            raise TypeError("action must be a DriverAction")
        if action.identity.driver != self.DRIVER_ID:
            raise ValueError(
                f"WirePlumber adapter cannot execute driver {action.identity.driver!r}"
            )
        handler = self.registry.handler(action.command.operation)
        if handler is None:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.PERMANENT,
                    "wireplumber:unsupported-driver-operation",
                    f"No WirePlumber adapter is registered for {action.command.operation!r}.",
                    {"supportedOperations": list(self.registry.operations)},
                ),
            )
        connection = self.connection_provider()
        stale_sequence_retries = 0
        while True:
            snapshot = self.snapshot_capture(connection)
            if not isinstance(snapshot, RuntimeSnapshot):
                raise TypeError("WyrePlumber snapshot capture must return RuntimeSnapshot")
            attempt_action = action
            if stale_sequence_retries:
                attempt_action = replace(
                    action,
                    idempotency_key=(
                        f"{action.idempotency_key[:220]}:stale-sequence:"
                        f"{stale_sequence_retries}"
                    ),
                )
            try:
                outcome = handler(connection, attempt_action, snapshot)
            except DriverActionError:
                raise
            except (TypeError, ValueError) as error:
                raise DriverActionError(
                    action,
                    ActionFailure(
                        ActionFailureClassification.PERMANENT,
                        "wireplumber:invalid-control-request",
                        str(error),
                        {"exception": type(error).__name__},
                    ),
                ) from error
            except RuntimeError as error:
                raise DriverActionError(
                    action,
                    ActionFailure(
                        ActionFailureClassification.DEPENDENCY,
                        "wireplumber:runtime-call-failed",
                        str(error),
                        {"exception": type(error).__name__},
                    ),
                ) from error
            if not isinstance(outcome, MutationOutcome):
                raise TypeError("WirePlumber control handler must return MutationOutcome")
            if outcome.status is MutationStatus.CONFIRMED:
                break
            if (
                outcome.failure is not None
                and outcome.failure.code is MutationFailureCode.STALE_SEQUENCE
                and stale_sequence_retries < self._MAX_STALE_SEQUENCE_RETRIES
            ):
                # PipeWire link creation and processor state changes advance the
                # same optimistic sequence used by the next control dispatch.
                # Recapture and revalidate every runtime identity before a
                # bounded retry with a distinct native request identity.
                stale_sequence_retries += 1
                continue
            break
        if outcome.status is not MutationStatus.CONFIRMED:
            raise DriverActionError(action, self._failure_from_outcome(outcome))
        return {
            "bindingOutcome": outcome.to_dict(),
            "runtimeGeneration": outcome.generation,
            "operation": outcome.operation.value,
            "status": outcome.status.value,
            "staleSequenceRetries": stale_sequence_retries,
        }

    def observe_endpoint_controls(
        self,
        logical_endpoint_id: str,
        runtime_key: str,
    ) -> Mapping[str, object]:
        if not isinstance(logical_endpoint_id, str) or not logical_endpoint_id:
            raise ValueError("logical_endpoint_id must be a non-empty string")
        snapshot = self.observe_runtime()
        candidate = _endpoint_candidate(snapshot, runtime_key)
        writable = _node_props_writable(snapshot, candidate.runtime.node_id)
        prefix = f"endpoint.{logical_endpoint_id}"
        return {
            f"{prefix}.runtimeKey": candidate.runtime_key,
            f"{prefix}.volume": candidate.volume,
            f"{prefix}.mute": candidate.mute,
            f"{prefix}.volumeSupported": writable,
            f"{prefix}.muteSupported": writable,
            "runtime.generation": snapshot.generation,
            "runtime.sequence": snapshot.sequence,
        }

    def observe_default_node(self, media_class: str) -> Mapping[str, object]:
        field, fact_name = _default_target_field(media_class)
        snapshot = self.observe_runtime()
        default = getattr(snapshot.defaults, field)
        resolved_key = None
        configured_name = None
        if default is not None:
            configured_name = default.configured_name
            if default.resolved_node_id in snapshot.nodes_by_id:
                resolved_key = _node_runtime_key(snapshot, default.resolved_node_id)
        prefix = f"routing.default.{fact_name}"
        return {
            f"{prefix}.runtimeKey": resolved_key,
            f"{prefix}.configuredName": configured_name,
            "runtime.generation": snapshot.generation,
            "runtime.sequence": snapshot.sequence,
        }

    def observe_stream_target(
        self,
        logical_stream_id: str,
        stream_runtime_key: str,
    ) -> Mapping[str, object]:
        if not isinstance(logical_stream_id, str) or not logical_stream_id:
            raise ValueError("logical_stream_id must be a non-empty string")
        snapshot = self.observe_runtime()
        stream = _runtime_node(snapshot, stream_runtime_key)
        _require_stream_node(stream)
        entry = _stream_target_entry(snapshot, stream.id)
        target = _stream_target_node(snapshot, entry)
        prefix = f"routing.stream.{logical_stream_id}"
        return {
            f"{prefix}.runtimeKey": _node_runtime_key(snapshot, stream.id),
            f"{prefix}.targetRuntimeKey": (
                _node_runtime_key(snapshot, target.id) if target is not None else None
            ),
            f"{prefix}.targetConfiguredValue": entry.value if entry is not None else None,
            f"{prefix}.targetConfiguredType": (entry.type_name if entry is not None else None),
            "runtime.generation": snapshot.generation,
            "runtime.sequence": snapshot.sequence,
        }

    def observe_endpoint_configuration(
        self,
        logical_endpoint_id: str,
        runtime_key: str,
    ) -> Mapping[str, object]:
        if not isinstance(logical_endpoint_id, str) or not logical_endpoint_id:
            raise ValueError("logical_endpoint_id must be a non-empty string")
        snapshot = self.observe_runtime()
        candidate = _endpoint_candidate(snapshot, runtime_key)
        prefix = f"endpoint.{logical_endpoint_id}"
        facts = {
            f"{prefix}.runtimeKey": candidate.runtime_key,
            f"{prefix}.activeProfiles": tuple(
                profile.name for profile in candidate.profiles if profile.active
            ),
            f"{prefix}.activeRoutes": tuple(
                route.name for route in candidate.routes if route.active
            ),
            "runtime.generation": snapshot.generation,
            "runtime.sequence": snapshot.sequence,
        }
        facts.update(
            {
                f"{prefix}.profile.{profile.name}.active": profile.active
                for profile in candidate.profiles
            }
        )
        facts.update(
            {f"{prefix}.route.{route.name}.active": route.active for route in candidate.routes}
        )
        return facts


def _endpoint_candidate(
    snapshot: RuntimeSnapshot,
    runtime_key: object,
) -> RuntimeEndpointCandidate:
    if not isinstance(runtime_key, str) or not runtime_key:
        raise ValueError("runtimeKey must be a non-empty string")
    candidate = next(
        (
            item
            for item in map_runtime_endpoints(snapshot).candidates
            if item.runtime_key == runtime_key
        ),
        None,
    )
    if candidate is None:
        raise KeyError(runtime_key)
    return candidate


def _node_props_writable(snapshot: RuntimeSnapshot, node_id: int) -> bool:
    parameter = snapshot.parameters_by_key.get(("node", node_id, "Props"))
    return bool(parameter is not None and "w" in parameter.permissions.lower())


_DEFAULT_TARGET_FIELDS = {
    "Audio/Sink": ("audio_sink", "audio-sink"),
    "Audio/Source": ("audio_source", "audio-source"),
    "Video/Source": ("video_source", "video-source"),
}


def _default_target_field(media_class: object) -> tuple[str, str]:
    try:
        return _DEFAULT_TARGET_FIELDS[media_class]
    except (KeyError, TypeError) as error:
        raise ValueError("media_class must be Audio/Sink, Audio/Source, or Video/Source") from error


def _node_runtime_key(snapshot: RuntimeSnapshot, node_id: int) -> str:
    return f"runtime:{snapshot.generation}:node:{node_id}"


def _runtime_node(snapshot: RuntimeSnapshot, runtime_key: object):
    if not isinstance(runtime_key, str) or not runtime_key:
        raise ValueError("runtimeKey must be a non-empty string")
    return next(
        (node for node in snapshot.nodes if _node_runtime_key(snapshot, node.id) == runtime_key),
        None,
    ) or _raise_missing_runtime_node(runtime_key)


def _raise_missing_runtime_node(runtime_key: str):
    raise KeyError(runtime_key)


def _require_stream_node(node) -> None:
    if not node.media_class or not node.media_class.startswith("Stream/"):
        raise ValueError("the runtime node is not an audio stream")


def _default_metadata(snapshot: RuntimeSnapshot):
    metadata = next((item for item in snapshot.metadata if item.name == "default"), None)
    if metadata is None and snapshot.defaults.metadata_id is not None:
        metadata = snapshot.metadata_by_id.get(snapshot.defaults.metadata_id)
    return metadata


def _stream_target_entry(snapshot: RuntimeSnapshot, stream_node_id: int):
    metadata = _default_metadata(snapshot)
    if metadata is None:
        return None
    return next(
        (
            item
            for item in metadata.entries
            if item.subject == stream_node_id and item.key == "target.object"
        ),
        None,
    )


def _stream_target_node(snapshot: RuntimeSnapshot, entry):
    if entry is None or entry.value is None:
        return None
    if entry.type_name == "Spa:Id":
        return next(
            (
                node
                for node in snapshot.nodes
                if str(node.properties.get("object.serial")) == entry.value
            ),
            None,
        )
    return next(
        (
            node
            for node in snapshot.nodes
            if (node.name or node.properties.get("node.name")) == entry.value
        ),
        None,
    )


def _require_action_generation(action: DriverAction, snapshot: RuntimeSnapshot) -> None:
    expected = action.command.arguments.get("runtimeGeneration")
    if expected != snapshot.generation:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.STALE_PRECONDITION,
                "wireplumber:routing-generation-stale",
                "The routing action belongs to another runtime generation.",
                {
                    "expectedGeneration": expected,
                    "observedGeneration": snapshot.generation,
                },
            ),
        )


def _runtime_node_for_action(
    action: DriverAction,
    snapshot: RuntimeSnapshot,
    argument: str,
):
    try:
        return _runtime_node(snapshot, action.command.arguments.get(argument))
    except KeyError as error:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.STALE_PRECONDITION,
                "wireplumber:routing-runtime-key-stale",
                "A generation-scoped routing node disappeared.",
                {
                    "argument": argument,
                    "runtimeKey": action.command.arguments.get(argument),
                    "runtimeGeneration": snapshot.generation,
                },
            ),
        ) from error


def _endpoint_control_handler(control: Callable, field: str) -> WirePlumberControlHandler:
    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        arguments = action.command.arguments
        try:
            candidate = _endpoint_candidate(snapshot, arguments.get("runtimeKey"))
        except KeyError as error:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.STALE_PRECONDITION,
                    "wireplumber:endpoint-runtime-key-stale",
                    "The logical endpoint's generation-scoped runtime node disappeared.",
                    {
                        "runtimeKey": arguments.get("runtimeKey"),
                        "runtimeGeneration": snapshot.generation,
                    },
                ),
            ) from error
        if not _node_props_writable(snapshot, candidate.runtime.node_id):
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.PERMANENT,
                    "wireplumber:endpoint-control-read-only",
                    f"The current node does not expose writable Props for {field}.",
                    {
                        "logicalEndpointId": action.identity.resource_id,
                        "runtimeKey": candidate.runtime_key,
                        "field": field,
                    },
                ),
            )
        expected_generation = arguments.get("runtimeGeneration")
        if expected_generation != snapshot.generation:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.STALE_PRECONDITION,
                    "wireplumber:endpoint-generation-stale",
                    "The endpoint action belongs to another runtime generation.",
                    {
                        "expectedGeneration": expected_generation,
                        "observedGeneration": snapshot.generation,
                    },
                ),
            )
        return control(
            connection,
            node_id=candidate.runtime.node_id,
            expected_generation=snapshot.generation,
            expected_sequence=snapshot.sequence,
            timeout=action.timeout_seconds,
            request_id=action.idempotency_key,
            **{field: arguments.get(field)},
        )

    return handler


def register_endpoint_audio_controls(
    registry: WirePlumberControlRegistry,
    *,
    set_volume=None,
    set_mute=None,
) -> None:
    if not isinstance(registry, WirePlumberControlRegistry):
        raise TypeError("registry must be a WirePlumberControlRegistry")
    if set_volume is None or set_mute is None:
        from wyreplumber.runtime import set_node_mute, set_node_volume

        set_volume = set_volume or set_node_volume
        set_mute = set_mute or set_node_mute
    registry.register(
        "set-endpoint-volume",
        _endpoint_control_handler(set_volume, "volume"),
    )
    registry.register(
        "set-endpoint-mute",
        _endpoint_control_handler(set_mute, "mute"),
    )


def _endpoint_control_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    field: str,
    value: object,
    previous_value: object,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(logical_endpoint_id, str) or not logical_endpoint_id:
        raise ValueError("logical_endpoint_id must be a non-empty string")
    if not isinstance(candidate, RuntimeEndpointCandidate):
        raise TypeError("candidate must be a detached RuntimeEndpointCandidate")
    operation = f"set-endpoint-{field}"
    arguments = {
        "runtimeKey": candidate.runtime_key,
        "runtimeGeneration": candidate.runtime.generation,
        field: value,
    }
    inverse_arguments = {
        "runtimeKey": candidate.runtime_key,
        "runtimeGeneration": candidate.runtime.generation,
        field: previous_value,
    }
    verification = ActionVerification(
        f"endpoint.{logical_endpoint_id}.{field}",
        ActionAssertionOperator.EQUALS,
        value,
    )
    inverse_verification = ActionVerification(
        f"endpoint.{logical_endpoint_id}.{field}",
        ActionAssertionOperator.EQUALS,
        previous_value,
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "logical-endpoint",
            logical_endpoint_id,
            operation,
        ),
        command=DriverCommand(operation, arguments),
        intent_scope=intent_scope,
        preconditions=(
            ActionPrecondition(
                "runtime.generation",
                ActionAssertionOperator.EQUALS,
                candidate.runtime.generation,
                "Reject the action after PipeWire recreates endpoint nodes.",
            ),
        ),
        timeout_seconds=timeout_seconds,
        verification=(verification,),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            f"Restore the endpoint's previously observed {field} value.",
            inverse=ActionRecoveryStep(
                DriverCommand(operation, inverse_arguments),
                (inverse_verification,),
                f"Restore prior endpoint {field}.",
            ),
        ),
        metadata=FrozenDict({"runtimeIdentityIsEphemeral": True}),
    )


def build_endpoint_volume_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    volume: float,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
        raise ValueError("volume must be a number between zero and one")
    if candidate.volume is None:
        raise ValueError("endpoint volume is unknown; a safe inverse cannot be declared")
    return _endpoint_control_action(
        logical_endpoint_id=logical_endpoint_id,
        candidate=candidate,
        field="volume",
        value=volume,
        previous_value=candidate.volume,
        intent_scope=intent_scope,
        timeout_seconds=timeout_seconds,
    )


def build_endpoint_mute_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    mute: bool,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(mute, bool):
        raise TypeError("mute must be a boolean")
    if candidate.mute is None:
        raise ValueError("endpoint mute is unknown; a safe inverse cannot be declared")
    return _endpoint_control_action(
        logical_endpoint_id=logical_endpoint_id,
        candidate=candidate,
        field="mute",
        value=mute,
        previous_value=candidate.mute,
        intent_scope=intent_scope,
        timeout_seconds=timeout_seconds,
    )


def _default_node_handler(control: Callable, *, clear: bool) -> WirePlumberControlHandler:
    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        _require_action_generation(action, snapshot)
        arguments = action.command.arguments
        common = {
            "expected_generation": snapshot.generation,
            "expected_sequence": snapshot.sequence,
            "timeout": action.timeout_seconds,
            "request_id": action.idempotency_key,
        }
        if clear:
            _default_target_field(arguments.get("mediaClass"))
            return control(
                connection,
                media_class=arguments.get("mediaClass"),
                **common,
            )
        node = _runtime_node_for_action(action, snapshot, "targetRuntimeKey")
        media_class = arguments.get("mediaClass")
        _default_target_field(media_class)
        if node.media_class != media_class:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.STALE_PRECONDITION,
                    "wireplumber:default-target-identity-changed",
                    "The resolved default target no longer has the planned media class.",
                    {
                        "runtimeKey": arguments.get("targetRuntimeKey"),
                        "expectedMediaClass": media_class,
                        "observedMediaClass": node.media_class,
                    },
                ),
            )
        return control(
            connection,
            node_id=node.id,
            media_class=media_class,
            **common,
        )

    return handler


def _stream_target_handler(control: Callable, *, clear: bool) -> WirePlumberControlHandler:
    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        _require_action_generation(action, snapshot)
        stream = _runtime_node_for_action(action, snapshot, "streamRuntimeKey")
        try:
            _require_stream_node(stream)
        except ValueError as error:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.STALE_PRECONDITION,
                    "wireplumber:stream-identity-changed",
                    str(error),
                    {"runtimeKey": action.command.arguments.get("streamRuntimeKey")},
                ),
            ) from error
        common = {
            "stream_node_id": stream.id,
            "expected_generation": snapshot.generation,
            "expected_sequence": snapshot.sequence,
            "timeout": action.timeout_seconds,
            "request_id": action.idempotency_key,
        }
        if clear:
            return control(connection, **common)
        target = _runtime_node_for_action(action, snapshot, "targetRuntimeKey")
        return control(connection, target_node_id=target.id, **common)

    return handler


def register_routing_controls(
    registry: WirePlumberControlRegistry,
    *,
    set_default=None,
    clear_default=None,
    set_stream=None,
    clear_stream=None,
) -> None:
    if not isinstance(registry, WirePlumberControlRegistry):
        raise TypeError("registry must be a WirePlumberControlRegistry")
    if any(control is None for control in (set_default, clear_default, set_stream, clear_stream)):
        from wyreplumber.runtime import (
            clear_default_node,
            clear_stream_target,
            set_default_node,
            set_stream_target,
        )

        set_default = set_default or set_default_node
        clear_default = clear_default or clear_default_node
        set_stream = set_stream or set_stream_target
        clear_stream = clear_stream or clear_stream_target
    registry.register(
        "set-default-node",
        _default_node_handler(set_default, clear=False),
    )
    registry.register(
        "clear-default-node",
        _default_node_handler(clear_default, clear=True),
    )
    registry.register(
        "set-stream-target",
        _stream_target_handler(set_stream, clear=False),
    )
    registry.register(
        "clear-stream-target",
        _stream_target_handler(clear_stream, clear=True),
    )


def _runtime_precondition(generation: int) -> tuple[ActionPrecondition, ...]:
    return (
        ActionPrecondition(
            "runtime.generation",
            ActionAssertionOperator.EQUALS,
            generation,
            "Reject the action after PipeWire recreates routing objects.",
        ),
    )


def _default_fact(media_class: str) -> str:
    _, fact_name = _default_target_field(media_class)
    return f"routing.default.{fact_name}.runtimeKey"


def _default_configured_fact(media_class: str) -> str:
    _, fact_name = _default_target_field(media_class)
    return f"routing.default.{fact_name}.configuredName"


def _stream_target_fact(logical_stream_id: str) -> str:
    if not isinstance(logical_stream_id, str) or not logical_stream_id:
        raise ValueError("logical_stream_id must be a non-empty string")
    return f"routing.stream.{logical_stream_id}.targetRuntimeKey"


def _stream_target_configured_fact(logical_stream_id: str) -> str:
    if not isinstance(logical_stream_id, str) or not logical_stream_id:
        raise ValueError("logical_stream_id must be a non-empty string")
    return f"routing.stream.{logical_stream_id}.targetConfiguredValue"


def _default_command(
    media_class: str,
    generation: int,
    candidate: RuntimeEndpointCandidate | None,
) -> DriverCommand:
    if candidate is None:
        return DriverCommand(
            "clear-default-node",
            {"mediaClass": media_class, "runtimeGeneration": generation},
        )
    return DriverCommand(
        "set-default-node",
        {
            "mediaClass": media_class,
            "runtimeGeneration": generation,
            "targetRuntimeKey": candidate.runtime_key,
        },
    )


def build_default_node_action(
    *,
    target_logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    previous_candidate: RuntimeEndpointCandidate | None,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(target_logical_endpoint_id, str) or not target_logical_endpoint_id:
        raise ValueError("target_logical_endpoint_id must be a non-empty string")
    if not isinstance(candidate, RuntimeEndpointCandidate):
        raise TypeError("candidate must be a detached RuntimeEndpointCandidate")
    media_class = candidate.media_class
    _default_target_field(media_class)
    if previous_candidate is not None:
        if not isinstance(previous_candidate, RuntimeEndpointCandidate):
            raise TypeError("previous_candidate must be a RuntimeEndpointCandidate or null")
        if previous_candidate.runtime.generation != candidate.runtime.generation:
            raise ValueError("previous default belongs to another runtime generation")
        if previous_candidate.media_class != media_class:
            raise ValueError("previous default has a different media class")
    inverse_command = _default_command(
        media_class,
        candidate.runtime.generation,
        previous_candidate,
    )
    inverse_value = previous_candidate.runtime_key if previous_candidate else None
    inverse_fact = (
        _default_fact(media_class)
        if previous_candidate is not None
        else _default_configured_fact(media_class)
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "default-node",
            f"default:{media_class}",
            "set-default-node",
        ),
        command=DriverCommand(
            "set-default-node",
            {
                "mediaClass": media_class,
                "runtimeGeneration": candidate.runtime.generation,
                "targetLogicalEndpointId": target_logical_endpoint_id,
                "targetRuntimeKey": candidate.runtime_key,
            },
        ),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(candidate.runtime.generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _default_fact(media_class),
                ActionAssertionOperator.EQUALS,
                candidate.runtime_key,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Restore the previously observed configured default.",
            inverse=ActionRecoveryStep(
                inverse_command,
                (
                    ActionVerification(
                        inverse_fact,
                        ActionAssertionOperator.EQUALS,
                        inverse_value,
                    ),
                ),
                "Restore the prior default metadata preference.",
            ),
        ),
        metadata={
            "routingMechanism": "wireplumber-default-metadata",
            "explicitLinks": False,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def build_clear_default_node_action(
    *,
    media_class: str,
    previous_logical_endpoint_id: str,
    previous_candidate: RuntimeEndpointCandidate,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    _default_target_field(media_class)
    if not isinstance(previous_logical_endpoint_id, str) or not previous_logical_endpoint_id:
        raise ValueError("previous_logical_endpoint_id must be a non-empty string")
    if not isinstance(previous_candidate, RuntimeEndpointCandidate):
        raise TypeError("previous_candidate must be a detached RuntimeEndpointCandidate")
    if previous_candidate.media_class != media_class:
        raise ValueError("previous default has a different media class")
    generation = previous_candidate.runtime.generation
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "default-node",
            f"default:{media_class}",
            "clear-default-node",
        ),
        command=_default_command(media_class, generation, None),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _default_configured_fact(media_class),
                ActionAssertionOperator.EQUALS,
                None,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Restore the explicitly cleared configured default.",
            inverse=ActionRecoveryStep(
                _default_command(media_class, generation, previous_candidate),
                (
                    ActionVerification(
                        _default_fact(media_class),
                        ActionAssertionOperator.EQUALS,
                        previous_candidate.runtime_key,
                    ),
                ),
                "Restore the prior default metadata preference.",
            ),
        ),
        metadata={
            "previousLogicalEndpointId": previous_logical_endpoint_id,
            "routingMechanism": "wireplumber-default-metadata",
            "explicitLinks": False,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def _stream_command(
    operation: str,
    *,
    stream_runtime_key: str,
    generation: int,
    target_candidate: RuntimeEndpointCandidate | None = None,
) -> DriverCommand:
    arguments = {
        "streamRuntimeKey": stream_runtime_key,
        "runtimeGeneration": generation,
    }
    if target_candidate is not None:
        arguments["targetRuntimeKey"] = target_candidate.runtime_key
    return DriverCommand(operation, arguments)


def _stream_target_recovery(
    *,
    logical_stream_id: str,
    stream_runtime_key: str,
    generation: int,
    previous_target_candidate: RuntimeEndpointCandidate | None,
) -> ActionRecoveryPolicy:
    if previous_target_candidate is None:
        operation = "clear-stream-target"
        previous_value = None
        verification_fact = _stream_target_configured_fact(logical_stream_id)
    else:
        if previous_target_candidate.runtime.generation != generation:
            raise ValueError("previous stream target belongs to another runtime generation")
        operation = "set-stream-target"
        previous_value = previous_target_candidate.runtime_key
        verification_fact = _stream_target_fact(logical_stream_id)
    return ActionRecoveryPolicy(
        ActionRecoveryMode.INVERSE,
        "Restore the previously observed per-stream target policy.",
        inverse=ActionRecoveryStep(
            _stream_command(
                operation,
                stream_runtime_key=stream_runtime_key,
                generation=generation,
                target_candidate=previous_target_candidate,
            ),
            (
                ActionVerification(
                    verification_fact,
                    ActionAssertionOperator.EQUALS,
                    previous_value,
                ),
            ),
            "Restore the prior target.object metadata value.",
        ),
    )


def build_stream_target_action(
    *,
    logical_stream_id: str,
    stream_runtime_key: str,
    target_logical_endpoint_id: str,
    target_candidate: RuntimeEndpointCandidate,
    previous_target_candidate: RuntimeEndpointCandidate | None,
    runtime_generation: int,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    _stream_target_fact(logical_stream_id)
    if not isinstance(target_logical_endpoint_id, str) or not target_logical_endpoint_id:
        raise ValueError("target_logical_endpoint_id must be a non-empty string")
    if not isinstance(target_candidate, RuntimeEndpointCandidate):
        raise TypeError("target_candidate must be a detached RuntimeEndpointCandidate")
    if target_candidate.runtime.generation != runtime_generation:
        raise ValueError("stream and target must belong to the same runtime generation")
    recovery = _stream_target_recovery(
        logical_stream_id=logical_stream_id,
        stream_runtime_key=stream_runtime_key,
        generation=runtime_generation,
        previous_target_candidate=previous_target_candidate,
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "logical-stream",
            logical_stream_id,
            "set-stream-target",
        ),
        command=DriverCommand(
            "set-stream-target",
            {
                "streamRuntimeKey": stream_runtime_key,
                "targetRuntimeKey": target_candidate.runtime_key,
                "targetLogicalEndpointId": target_logical_endpoint_id,
                "runtimeGeneration": runtime_generation,
            },
        ),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(runtime_generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _stream_target_fact(logical_stream_id),
                ActionAssertionOperator.EQUALS,
                target_candidate.runtime_key,
            ),
        ),
        recovery=recovery,
        metadata={
            "routingMechanism": "wireplumber-stream-target-metadata",
            "explicitLinks": False,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def build_clear_stream_target_action(
    *,
    logical_stream_id: str,
    stream_runtime_key: str,
    previous_target_candidate: RuntimeEndpointCandidate,
    runtime_generation: int,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    _stream_target_fact(logical_stream_id)
    if not isinstance(previous_target_candidate, RuntimeEndpointCandidate):
        raise TypeError("previous_target_candidate must be a detached RuntimeEndpointCandidate")
    recovery = _stream_target_recovery(
        logical_stream_id=logical_stream_id,
        stream_runtime_key=stream_runtime_key,
        generation=runtime_generation,
        previous_target_candidate=previous_target_candidate,
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "logical-stream",
            logical_stream_id,
            "clear-stream-target",
        ),
        command=_stream_command(
            "clear-stream-target",
            stream_runtime_key=stream_runtime_key,
            generation=runtime_generation,
        ),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(runtime_generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _stream_target_configured_fact(logical_stream_id),
                ActionAssertionOperator.EQUALS,
                None,
            ),
        ),
        recovery=recovery,
        metadata={
            "routingMechanism": "wireplumber-stream-target-metadata",
            "explicitLinks": False,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def _endpoint_configuration_handler(
    control: Callable,
    *,
    kind: str,
) -> WirePlumberControlHandler:
    if kind not in {"profile", "route"}:
        raise ValueError("endpoint configuration kind must be profile or route")

    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        _require_action_generation(action, snapshot)
        candidate = _runtime_endpoint_for_action(
            action,
            snapshot,
            "endpointRuntimeKey",
        )
        device_id = candidate.runtime.device_id
        if device_id is None:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.PERMANENT,
                    "wireplumber:endpoint-has-no-device",
                    f"The endpoint cannot expose a selectable {kind} without a device.",
                    {
                        "logicalEndpointId": action.identity.resource_id,
                        "runtimeKey": candidate.runtime_key,
                    },
                ),
            )
        name = action.command.arguments.get(f"{kind}Name")
        values = snapshot.profiles if kind == "profile" else snapshot.routes
        matches = tuple(
            value for value in values if value.device_id == device_id and value.name == name
        )
        if len(matches) != 1:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.STALE_PRECONDITION,
                    f"wireplumber:endpoint-{kind}-stale",
                    f"The named endpoint {kind} is missing or ambiguous in this generation.",
                    {
                        "runtimeKey": candidate.runtime_key,
                        f"{kind}Name": name,
                        "matchCount": len(matches),
                    },
                ),
            )
        return control(
            connection,
            **{kind: matches[0]},
            expected_generation=snapshot.generation,
            expected_sequence=snapshot.sequence,
            timeout=action.timeout_seconds,
            request_id=action.idempotency_key,
        )

    return handler


def _runtime_endpoint_for_action(
    action: DriverAction,
    snapshot: RuntimeSnapshot,
    argument: str,
) -> RuntimeEndpointCandidate:
    try:
        return _endpoint_candidate(snapshot, action.command.arguments.get(argument))
    except KeyError as error:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.STALE_PRECONDITION,
                "wireplumber:endpoint-configuration-generation-stale",
                "The generation-scoped endpoint disappeared before configuration.",
                {
                    "runtimeKey": action.command.arguments.get(argument),
                    "runtimeGeneration": snapshot.generation,
                },
            ),
        ) from error


def register_endpoint_configuration_controls(
    registry: WirePlumberControlRegistry,
    *,
    select_profile=None,
    select_route=None,
) -> None:
    if not isinstance(registry, WirePlumberControlRegistry):
        raise TypeError("registry must be a WirePlumberControlRegistry")
    if select_profile is None or select_route is None:
        from wyreplumber.runtime import select_device_profile, select_device_route

        select_profile = select_profile or select_device_profile
        select_route = select_route or select_device_route
    registry.register(
        "select-endpoint-profile",
        _endpoint_configuration_handler(select_profile, kind="profile"),
    )
    registry.register(
        "select-endpoint-route",
        _endpoint_configuration_handler(select_route, kind="route"),
    )


def _endpoint_configuration_fact(
    logical_endpoint_id: str,
    kind: str,
    name: str,
) -> str:
    if not isinstance(logical_endpoint_id, str) or not logical_endpoint_id:
        raise ValueError("logical_endpoint_id must be a non-empty string")
    if kind not in {"profile", "route"}:
        raise ValueError("endpoint configuration kind must be profile or route")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} name must be a non-empty string")
    return f"endpoint.{logical_endpoint_id}.{kind}.{name}.active"


def _validate_endpoint_configuration_summary(
    candidate: RuntimeEndpointCandidate,
    summary: EndpointProfileSummary | EndpointRouteSummary,
    *,
    kind: str,
) -> None:
    expected_type = EndpointProfileSummary if kind == "profile" else EndpointRouteSummary
    if not isinstance(summary, expected_type):
        raise TypeError(f"{kind} must be a detached {expected_type.__name__}")
    if summary.runtime.generation != candidate.runtime.generation:
        raise ValueError(f"{kind} belongs to another runtime generation")
    if summary.runtime.device_id != candidate.runtime.device_id:
        raise ValueError(f"{kind} belongs to another endpoint device")
    values = candidate.profiles if kind == "profile" else candidate.routes
    if summary not in values:
        raise ValueError(f"{kind} is not part of the endpoint inventory candidate")


def _build_endpoint_configuration_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    kind: str,
    selected: EndpointProfileSummary | EndpointRouteSummary,
    previous: EndpointProfileSummary | EndpointRouteSummary,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(candidate, RuntimeEndpointCandidate):
        raise TypeError("candidate must be a detached RuntimeEndpointCandidate")
    _validate_endpoint_configuration_summary(candidate, selected, kind=kind)
    _validate_endpoint_configuration_summary(candidate, previous, kind=kind)
    operation = f"select-endpoint-{kind}"
    generation = candidate.runtime.generation
    command_arguments = {
        "endpointRuntimeKey": candidate.runtime_key,
        "runtimeGeneration": generation,
        f"{kind}Name": selected.name,
    }
    inverse_arguments = {
        "endpointRuntimeKey": candidate.runtime_key,
        "runtimeGeneration": generation,
        f"{kind}Name": previous.name,
    }
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "logical-endpoint",
            logical_endpoint_id,
            operation,
        ),
        command=DriverCommand(operation, command_arguments),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _endpoint_configuration_fact(
                    logical_endpoint_id,
                    kind,
                    selected.name,
                ),
                ActionAssertionOperator.EQUALS,
                True,
                f"Confirm the selected {kind} in a fresh endpoint inventory.",
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            f"Restore the previously observed endpoint {kind}.",
            inverse=ActionRecoveryStep(
                DriverCommand(operation, inverse_arguments),
                (
                    ActionVerification(
                        _endpoint_configuration_fact(
                            logical_endpoint_id,
                            kind,
                            previous.name,
                        ),
                        ActionAssertionOperator.EQUALS,
                        True,
                    ),
                ),
                f"Restore prior endpoint {kind} {previous.name!r}.",
            ),
        ),
        metadata={
            "inventoryVerificationRequired": True,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def build_endpoint_profile_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    profile: EndpointProfileSummary,
    previous_profile: EndpointProfileSummary,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    return _build_endpoint_configuration_action(
        logical_endpoint_id=logical_endpoint_id,
        candidate=candidate,
        kind="profile",
        selected=profile,
        previous=previous_profile,
        intent_scope=intent_scope,
        timeout_seconds=timeout_seconds,
    )


def build_endpoint_route_action(
    *,
    logical_endpoint_id: str,
    candidate: RuntimeEndpointCandidate,
    route: EndpointRouteSummary,
    previous_route: EndpointRouteSummary,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    return _build_endpoint_configuration_action(
        logical_endpoint_id=logical_endpoint_id,
        candidate=candidate,
        kind="route",
        selected=route,
        previous=previous_route,
        intent_scope=intent_scope,
        timeout_seconds=timeout_seconds,
    )


OPEN_CINEMA_LINK_OWNER = "open-cinema.orchestrator"


class ManagedLinkShape(StrEnum):
    ENDPOINT_ROUTE = "endpoint-route"
    FAN_OUT = "fan-out"
    MIXER = "mixer"
    PROCESSOR_INTERNAL = "processor-internal"


def _managed_link_shape(value: object) -> ManagedLinkShape:
    try:
        return ManagedLinkShape(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "managed links require an endpoint-route or advanced fan-out, mixer, or "
            "processor-internal shape"
        ) from error


def _port_runtime_key(snapshot: RuntimeSnapshot, port_id: int) -> str:
    return f"runtime:{snapshot.generation}:port:{port_id}"


def _runtime_port(snapshot: RuntimeSnapshot, runtime_key: object):
    if not isinstance(runtime_key, str) or not runtime_key:
        raise ValueError("port runtime key must be a non-empty string")
    port = next(
        (item for item in snapshot.ports if _port_runtime_key(snapshot, item.id) == runtime_key),
        None,
    )
    if port is None:
        raise KeyError(runtime_key)
    return port


def _managed_link_fact(desired_link_id: str, field: str) -> str:
    if not isinstance(desired_link_id, str) or not desired_link_id:
        raise ValueError("desired_link_id must be a non-empty string")
    return f"managedLink.{OPEN_CINEMA_LINK_OWNER}.{desired_link_id}.{field}"


def _owned_links(snapshot: RuntimeSnapshot, desired_link_id: str) -> tuple[LinkValue, ...]:
    return tuple(
        link
        for link in snapshot.links
        if link.owner == OPEN_CINEMA_LINK_OWNER and link.desired_id == desired_link_id
    )


def _managed_link_facts(
    snapshot: RuntimeSnapshot,
    desired_link_id: str,
) -> Mapping[str, object]:
    matches = _owned_links(snapshot, desired_link_id)
    link = matches[0] if len(matches) == 1 else None
    prefix = f"managedLink.{OPEN_CINEMA_LINK_OWNER}.{desired_link_id}"
    return {
        f"{prefix}.present": link is not None,
        f"{prefix}.conflict": len(matches) > 1,
        f"{prefix}.matchCount": len(matches),
        f"{prefix}.tagged": bool(
            link is not None
            and link.properties.get("open-cinema.owner") == OPEN_CINEMA_LINK_OWNER
            and link.properties.get("open-cinema.desired-id") == desired_link_id
        ),
        f"{prefix}.outputNodeRuntimeKey": (
            _node_runtime_key(snapshot, link.output_node_id) if link else None
        ),
        f"{prefix}.outputPortRuntimeKey": (
            _port_runtime_key(snapshot, link.output_port_id) if link else None
        ),
        f"{prefix}.inputNodeRuntimeKey": (
            _node_runtime_key(snapshot, link.input_node_id) if link else None
        ),
        f"{prefix}.inputPortRuntimeKey": (
            _port_runtime_key(snapshot, link.input_port_id) if link else None
        ),
        "runtime.generation": snapshot.generation,
        "runtime.sequence": snapshot.sequence,
    }


def observe_managed_link(
    adapter: WirePlumberDriverAdapter,
    desired_link_id: str,
) -> Mapping[str, object]:
    if not isinstance(adapter, WirePlumberDriverAdapter):
        raise TypeError("adapter must be a WirePlumberDriverAdapter")
    return _managed_link_facts(adapter.observe_runtime(), desired_link_id)


def _managed_link_endpoint(
    action: DriverAction,
    snapshot: RuntimeSnapshot,
    *,
    node_argument: str,
    port_argument: str,
    direction: str,
) -> tuple[object, object]:
    node = _runtime_node_for_action(action, snapshot, node_argument)
    try:
        port = _runtime_port(snapshot, action.command.arguments.get(port_argument))
    except KeyError as error:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.STALE_PRECONDITION,
                "wireplumber:managed-link-port-stale",
                "A generation-scoped managed-link port disappeared.",
                {
                    "argument": port_argument,
                    "runtimeKey": action.command.arguments.get(port_argument),
                },
            ),
        ) from error
    if port.node_id != node.id or port.direction.value != direction:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.STALE_PRECONDITION,
                "wireplumber:managed-link-endpoint-changed",
                "A managed-link port no longer belongs to the planned node and direction.",
                {
                    "nodeRuntimeKey": action.command.arguments.get(node_argument),
                    "portRuntimeKey": action.command.arguments.get(port_argument),
                    "expectedDirection": direction,
                    "observedDirection": port.direction.value,
                },
            ),
        )
    return node, port


def _require_managed_link_action(action: DriverAction) -> tuple[str, ManagedLinkShape]:
    owner = action.command.arguments.get("owner")
    if owner != OPEN_CINEMA_LINK_OWNER:
        raise DriverActionError(
            action,
            ActionFailure(
                ActionFailureClassification.SAFETY,
                "wireplumber:managed-link-owner-refused",
                "The adapter refuses link operations outside its fixed ownership namespace.",
                {"requestedOwner": owner, "requiredOwner": OPEN_CINEMA_LINK_OWNER},
            ),
        )
    desired_link_id = action.command.arguments.get("desiredLinkId")
    if not isinstance(desired_link_id, str) or not desired_link_id:
        raise ValueError("desiredLinkId must be a non-empty string")
    return desired_link_id, _managed_link_shape(action.command.arguments.get("shape"))


def _create_managed_link_handler(control: Callable) -> WirePlumberControlHandler:
    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        _require_action_generation(action, snapshot)
        desired_link_id, _ = _require_managed_link_action(action)
        output_node, output_port = _managed_link_endpoint(
            action,
            snapshot,
            node_argument="outputNodeRuntimeKey",
            port_argument="outputPortRuntimeKey",
            direction="output",
        )
        input_node, input_port = _managed_link_endpoint(
            action,
            snapshot,
            node_argument="inputNodeRuntimeKey",
            port_argument="inputPortRuntimeKey",
            direction="input",
        )
        return control(
            connection,
            owner=OPEN_CINEMA_LINK_OWNER,
            desired_id=desired_link_id,
            output_node_id=output_node.id,
            output_port_id=output_port.id,
            input_node_id=input_node.id,
            input_port_id=input_port.id,
            expected_generation=snapshot.generation,
            expected_sequence=snapshot.sequence,
            passive=action.command.arguments.get("passive", False),
            properties=action.command.arguments.get("properties", FrozenDict()).to_dict(),
            timeout=action.timeout_seconds,
            request_id=action.idempotency_key,
        )

    return handler


def _remove_managed_link_handler(control: Callable) -> WirePlumberControlHandler:
    def handler(connection, action: DriverAction, snapshot: RuntimeSnapshot):
        _require_action_generation(action, snapshot)
        desired_link_id, _ = _require_managed_link_action(action)
        matches = _owned_links(snapshot, desired_link_id)
        if len(matches) > 1:
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.SAFETY,
                    "wireplumber:managed-link-identity-conflict",
                    "Multiple owned links claim the desired identity; none may be removed.",
                    {"desiredLinkId": desired_link_id, "matchCount": len(matches)},
                ),
            )
        if matches and not (
            matches[0].properties.get("open-cinema.owner") == OPEN_CINEMA_LINK_OWNER
            and matches[0].properties.get("open-cinema.desired-id") == desired_link_id
        ):
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.SAFETY,
                    "wireplumber:managed-link-tags-invalid",
                    "The observed link ownership fields and native tags disagree.",
                    {"desiredLinkId": desired_link_id},
                ),
            )
        if not matches and any(link.desired_id == desired_link_id for link in snapshot.links):
            raise DriverActionError(
                action,
                ActionFailure(
                    ActionFailureClassification.SAFETY,
                    "wireplumber:unmanaged-link-removal-refused",
                    "A link with this desired identity exists outside Open Cinema ownership.",
                    {"desiredLinkId": desired_link_id},
                ),
            )
        return control(
            connection,
            owner=OPEN_CINEMA_LINK_OWNER,
            desired_id=desired_link_id,
            expected_generation=snapshot.generation,
            expected_sequence=snapshot.sequence,
            timeout=action.timeout_seconds,
            request_id=action.idempotency_key,
        )

    return handler


def register_managed_link_controls(
    registry: WirePlumberControlRegistry,
    *,
    create_link=None,
    remove_link=None,
) -> None:
    if not isinstance(registry, WirePlumberControlRegistry):
        raise TypeError("registry must be a WirePlumberControlRegistry")
    if create_link is None or remove_link is None:
        from wyreplumber.runtime import create_managed_link, remove_managed_link

        create_link = create_link or create_managed_link
        remove_link = remove_link or remove_managed_link
    registry.register("create-managed-link", _create_managed_link_handler(create_link))
    registry.register("remove-managed-link", _remove_managed_link_handler(remove_link))


def _managed_link_arguments(
    *,
    desired_link_id: str,
    shape: ManagedLinkShape,
    generation: int,
    output_node_runtime_key: str,
    output_port_runtime_key: str,
    input_node_runtime_key: str,
    input_port_runtime_key: str,
    passive: bool,
    properties: Mapping[str, str],
) -> dict[str, object]:
    return {
        "owner": OPEN_CINEMA_LINK_OWNER,
        "desiredLinkId": desired_link_id,
        "shape": shape.value,
        "runtimeGeneration": generation,
        "outputNodeRuntimeKey": output_node_runtime_key,
        "outputPortRuntimeKey": output_port_runtime_key,
        "inputNodeRuntimeKey": input_node_runtime_key,
        "inputPortRuntimeKey": input_port_runtime_key,
        "passive": passive,
        "properties": dict(properties),
    }


def _validate_runtime_key(
    value: object,
    *,
    generation: int,
    kind: str,
) -> str:
    prefix = f"runtime:{generation}:{kind}:"
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or not value.removeprefix(prefix).isdecimal()
    ):
        raise ValueError(f"{kind} runtime key must belong to generation {generation}")
    return value


def _validate_managed_link_properties(properties: Mapping[str, str] | None) -> dict[str, str]:
    if properties is None:
        return {}
    if not isinstance(properties, Mapping):
        raise TypeError("managed link properties must be a mapping")
    result = {}
    for key, value in properties.items():
        if not isinstance(key, str) or not key:
            raise ValueError("managed link property names must be non-empty strings")
        if key in _RESERVED_OBSERVED_LINK_PROPERTIES:
            raise ValueError(f"managed link property {key!r} is assigned by the adapter")
        if not isinstance(value, str):
            raise TypeError("managed link property values must be strings")
        result[key] = value
    return result


def build_managed_link_action(
    *,
    desired_link_id: str,
    shape: ManagedLinkShape | str,
    runtime_generation: int,
    output_node_runtime_key: str,
    output_port_runtime_key: str,
    input_node_runtime_key: str,
    input_port_runtime_key: str,
    passive: bool = False,
    properties: Mapping[str, str] | None = None,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(desired_link_id, str) or not desired_link_id:
        raise ValueError("desired_link_id must be a non-empty string")
    selected_shape = _managed_link_shape(shape)
    if not isinstance(runtime_generation, int) or isinstance(runtime_generation, bool):
        raise TypeError("runtime_generation must be an integer")
    if not isinstance(passive, bool):
        raise TypeError("passive must be a boolean")
    selected_properties = _validate_managed_link_properties(properties)
    output_node_runtime_key = _validate_runtime_key(
        output_node_runtime_key,
        generation=runtime_generation,
        kind="node",
    )
    output_port_runtime_key = _validate_runtime_key(
        output_port_runtime_key,
        generation=runtime_generation,
        kind="port",
    )
    input_node_runtime_key = _validate_runtime_key(
        input_node_runtime_key,
        generation=runtime_generation,
        kind="node",
    )
    input_port_runtime_key = _validate_runtime_key(
        input_port_runtime_key,
        generation=runtime_generation,
        kind="port",
    )
    arguments = _managed_link_arguments(
        desired_link_id=desired_link_id,
        shape=selected_shape,
        generation=runtime_generation,
        output_node_runtime_key=output_node_runtime_key,
        output_port_runtime_key=output_port_runtime_key,
        input_node_runtime_key=input_node_runtime_key,
        input_port_runtime_key=input_port_runtime_key,
        passive=passive,
        properties=selected_properties,
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "managed-link",
            desired_link_id,
            "create-managed-link",
        ),
        command=DriverCommand("create-managed-link", arguments),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(runtime_generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _managed_link_fact(desired_link_id, "present"),
                ActionAssertionOperator.EQUALS,
                True,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "conflict"),
                ActionAssertionOperator.EQUALS,
                False,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "tagged"),
                ActionAssertionOperator.EQUALS,
                True,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "outputNodeRuntimeKey"),
                ActionAssertionOperator.EQUALS,
                output_node_runtime_key,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "outputPortRuntimeKey"),
                ActionAssertionOperator.EQUALS,
                output_port_runtime_key,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "inputNodeRuntimeKey"),
                ActionAssertionOperator.EQUALS,
                input_node_runtime_key,
            ),
            ActionVerification(
                _managed_link_fact(desired_link_id, "inputPortRuntimeKey"),
                ActionAssertionOperator.EQUALS,
                input_port_runtime_key,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Remove only the explicitly tagged link created by this action.",
            inverse=ActionRecoveryStep(
                DriverCommand(
                    "remove-managed-link",
                    {
                        "owner": OPEN_CINEMA_LINK_OWNER,
                        "desiredLinkId": desired_link_id,
                        "shape": selected_shape.value,
                        "runtimeGeneration": runtime_generation,
                    },
                ),
                (
                    ActionVerification(
                        _managed_link_fact(desired_link_id, "present"),
                        ActionAssertionOperator.EQUALS,
                        False,
                    ),
                    ActionVerification(
                        _managed_link_fact(desired_link_id, "conflict"),
                        ActionAssertionOperator.EQUALS,
                        False,
                    ),
                ),
                "Remove the exact Open Cinema-owned link identity.",
            ),
        ),
        metadata={
            "advancedShape": selected_shape.value,
            "explicitLinks": True,
            "owner": OPEN_CINEMA_LINK_OWNER,
            "runtimeIdentityIsEphemeral": True,
        },
    )


_RESERVED_OBSERVED_LINK_PROPERTIES = {
    "link.output.node",
    "link.output.port",
    "link.input.node",
    "link.input.port",
    "object.linger",
    "open-cinema.owner",
    "open-cinema.desired-id",
    "link.passive",
}


def build_remove_managed_link_action(
    *,
    link: LinkValue,
    shape: ManagedLinkShape | str,
    runtime_generation: int,
    intent_scope: str,
    timeout_seconds: float,
) -> DriverAction:
    if not isinstance(link, LinkValue):
        raise TypeError("link must be a detached LinkValue")
    if (
        link.owner != OPEN_CINEMA_LINK_OWNER
        or not link.desired_id
        or link.properties.get("open-cinema.owner") != OPEN_CINEMA_LINK_OWNER
        or link.properties.get("open-cinema.desired-id") != link.desired_id
    ):
        raise PermissionError("refusing to remove a link not owned by Open Cinema")
    selected_shape = _managed_link_shape(shape)
    properties = {
        key: value
        for key, value in link.properties.items()
        if key not in _RESERVED_OBSERVED_LINK_PROPERTIES and isinstance(value, str)
    }
    create_arguments = _managed_link_arguments(
        desired_link_id=link.desired_id,
        shape=selected_shape,
        generation=runtime_generation,
        output_node_runtime_key=_node_runtime_key_from_generation(
            runtime_generation,
            link.output_node_id,
        ),
        output_port_runtime_key=_port_runtime_key_from_generation(
            runtime_generation,
            link.output_port_id,
        ),
        input_node_runtime_key=_node_runtime_key_from_generation(
            runtime_generation,
            link.input_node_id,
        ),
        input_port_runtime_key=_port_runtime_key_from_generation(
            runtime_generation,
            link.input_port_id,
        ),
        passive=link.properties.get("link.passive") == "true",
        properties=properties,
    )
    return DriverAction.create(
        identity=DriverActionIdentity(
            WirePlumberDriverAdapter.DRIVER_ID,
            "managed-link",
            link.desired_id,
            "remove-managed-link",
        ),
        command=DriverCommand(
            "remove-managed-link",
            {
                "owner": OPEN_CINEMA_LINK_OWNER,
                "desiredLinkId": link.desired_id,
                "shape": selected_shape.value,
                "runtimeGeneration": runtime_generation,
            },
        ),
        intent_scope=intent_scope,
        preconditions=_runtime_precondition(runtime_generation),
        timeout_seconds=timeout_seconds,
        verification=(
            ActionVerification(
                _managed_link_fact(link.desired_id, "present"),
                ActionAssertionOperator.EQUALS,
                False,
            ),
            ActionVerification(
                _managed_link_fact(link.desired_id, "conflict"),
                ActionAssertionOperator.EQUALS,
                False,
            ),
        ),
        recovery=ActionRecoveryPolicy(
            ActionRecoveryMode.INVERSE,
            "Recreate the exact previously observed owned link if cleanup fails later.",
            inverse=ActionRecoveryStep(
                DriverCommand("create-managed-link", create_arguments),
                (
                    ActionVerification(
                        _managed_link_fact(link.desired_id, "present"),
                        ActionAssertionOperator.EQUALS,
                        True,
                    ),
                    ActionVerification(
                        _managed_link_fact(link.desired_id, "conflict"),
                        ActionAssertionOperator.EQUALS,
                        False,
                    ),
                    ActionVerification(
                        _managed_link_fact(link.desired_id, "tagged"),
                        ActionAssertionOperator.EQUALS,
                        True,
                    ),
                ),
                "Recreate the removed Open Cinema-owned link.",
            ),
        ),
        metadata={
            "advancedShape": selected_shape.value,
            "explicitLinks": True,
            "owner": OPEN_CINEMA_LINK_OWNER,
            "runtimeIdentityIsEphemeral": True,
        },
    )


def _node_runtime_key_from_generation(generation: int, node_id: int) -> str:
    return f"runtime:{generation}:node:{node_id}"


def _port_runtime_key_from_generation(generation: int, port_id: int) -> str:
    return f"runtime:{generation}:port:{port_id}"
