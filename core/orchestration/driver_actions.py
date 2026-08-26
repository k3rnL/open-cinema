from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from wyreplumber.runtime import FrozenDict, freeze_json, thaw_json

from .execution_limits import ActionExecutionLimits
from .graph_documents import graph_content_digest

DRIVER_ACTION_SCHEMA_VERSION = 1


def _required_text(value: object, *, field: str, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value


def _frozen_mapping(value: Mapping[str, object], *, field: str) -> FrozenDict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    frozen = freeze_json(dict(value))
    if not isinstance(frozen, FrozenDict):  # pragma: no cover - guarded by Mapping.
        raise TypeError(f"{field} must be a mapping")
    return frozen


class ActionAssertionOperator(StrEnum):
    EXISTS = "exists"
    ABSENT = "absent"
    EQUALS = "equals"
    NOT_EQUALS = "not-equals"
    CONTAINS = "contains"


@dataclass(frozen=True, slots=True)
class DriverActionIdentity:
    driver: str
    resource_kind: str
    resource_id: str
    operation: str
    qualifier: str = "default"

    def __post_init__(self) -> None:
        for field in (
            "driver",
            "resource_kind",
            "resource_id",
            "operation",
            "qualifier",
        ):
            _required_text(getattr(self, field), field=field)

    @property
    def key(self) -> str:
        return graph_content_digest(self.to_document())

    @property
    def resource_key(self) -> str:
        return graph_content_digest(
            {
                "driver": self.driver,
                "resourceKind": self.resource_kind,
                "resourceId": self.resource_id,
            }
        )

    def to_document(self) -> dict[str, str]:
        return {
            "driver": self.driver,
            "resourceKind": self.resource_kind,
            "resourceId": self.resource_id,
            "operation": self.operation,
            "qualifier": self.qualifier,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> DriverActionIdentity:
        if not isinstance(document, Mapping):
            raise TypeError("action identity must be a mapping")
        return cls(
            driver=document.get("driver"),
            resource_kind=document.get("resourceKind"),
            resource_id=document.get("resourceId"),
            operation=document.get("operation"),
            qualifier=document.get("qualifier", "default"),
        )


@dataclass(frozen=True, slots=True)
class DriverCommand:
    operation: str
    arguments: FrozenDict

    def __post_init__(self) -> None:
        _required_text(self.operation, field="operation")
        object.__setattr__(
            self,
            "arguments",
            _frozen_mapping(self.arguments, field="command arguments"),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "arguments": self.arguments.to_dict(),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> DriverCommand:
        if not isinstance(document, Mapping):
            raise TypeError("driver command must be a mapping")
        return cls(
            operation=document.get("operation"),
            arguments=document.get("arguments", {}),
        )


@dataclass(frozen=True, slots=True)
class ActionPrecondition:
    subject: str
    operator: ActionAssertionOperator
    expected: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        _required_text(self.subject, field="precondition subject", maximum=1024)
        object.__setattr__(self, "operator", ActionAssertionOperator(self.operator))
        if self.description:
            _required_text(
                self.description,
                field="precondition description",
                maximum=2048,
            )
        object.__setattr__(self, "expected", freeze_json(self.expected))

    def to_document(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "operator": self.operator.value,
            "expected": thaw_json(self.expected),
            "description": self.description,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> ActionPrecondition:
        if not isinstance(document, Mapping):
            raise TypeError("action precondition must be a mapping")
        return cls(
            subject=document.get("subject"),
            operator=document.get("operator"),
            expected=document.get("expected"),
            description=document.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class ActionVerification:
    subject: str
    operator: ActionAssertionOperator
    expected: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        _required_text(self.subject, field="verification subject", maximum=1024)
        object.__setattr__(self, "operator", ActionAssertionOperator(self.operator))
        if self.description:
            _required_text(
                self.description,
                field="verification description",
                maximum=2048,
            )
        object.__setattr__(self, "expected", freeze_json(self.expected))

    def to_document(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "operator": self.operator.value,
            "expected": thaw_json(self.expected),
            "description": self.description,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> ActionVerification:
        if not isinstance(document, Mapping):
            raise TypeError("action verification must be a mapping")
        return cls(
            subject=document.get("subject"),
            operator=document.get("operator"),
            expected=document.get("expected"),
            description=document.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class ActionRecoveryStep:
    command: DriverCommand
    verification: tuple[ActionVerification, ...]
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.command, DriverCommand):
            raise TypeError("recovery command must be a DriverCommand")
        verification = tuple(self.verification)
        if not verification or any(
            not isinstance(item, ActionVerification) for item in verification
        ):
            raise ValueError("recovery verification must contain typed assertions")
        object.__setattr__(self, "verification", verification)
        _required_text(self.description, field="recovery description", maximum=2048)

    def to_document(self) -> dict[str, object]:
        return {
            "command": self.command.to_document(),
            "verification": [item.to_document() for item in self.verification],
            "description": self.description,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> ActionRecoveryStep:
        if not isinstance(document, Mapping):
            raise TypeError("action recovery step must be a mapping")
        verification = document.get("verification", ())
        if not isinstance(verification, Sequence) or isinstance(verification, (str, bytes)):
            raise TypeError("recovery verification must be an array")
        return cls(
            command=DriverCommand.from_document(document.get("command")),
            verification=tuple(ActionVerification.from_document(item) for item in verification),
            description=document.get("description"),
        )


class ActionRecoveryMode(StrEnum):
    NONE_REQUIRED = "none-required"
    INVERSE = "inverse"
    SAFE_FALLBACK = "safe-fallback"
    INVERSE_THEN_FALLBACK = "inverse-then-fallback"


@dataclass(frozen=True, slots=True)
class ActionRecoveryPolicy:
    mode: ActionRecoveryMode
    reason: str
    inverse: ActionRecoveryStep | None = None
    safe_fallback: ActionRecoveryStep | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", ActionRecoveryMode(self.mode))
        _required_text(self.reason, field="recovery reason", maximum=2048)
        if self.inverse is not None and not isinstance(self.inverse, ActionRecoveryStep):
            raise TypeError("inverse must be an ActionRecoveryStep or null")
        if self.safe_fallback is not None and not isinstance(
            self.safe_fallback, ActionRecoveryStep
        ):
            raise TypeError("safe_fallback must be an ActionRecoveryStep or null")
        requirements = {
            ActionRecoveryMode.NONE_REQUIRED: (False, False),
            ActionRecoveryMode.INVERSE: (True, False),
            ActionRecoveryMode.SAFE_FALLBACK: (False, True),
            ActionRecoveryMode.INVERSE_THEN_FALLBACK: (True, True),
        }
        needs_inverse, needs_fallback = requirements[self.mode]
        if (self.inverse is not None) is not needs_inverse:
            raise ValueError(f"recovery mode {self.mode.value!r} has invalid inverse")
        if (self.safe_fallback is not None) is not needs_fallback:
            raise ValueError(f"recovery mode {self.mode.value!r} has invalid safe fallback")

    def to_document(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "inverse": self.inverse.to_document() if self.inverse is not None else None,
            "safeFallback": (
                self.safe_fallback.to_document() if self.safe_fallback is not None else None
            ),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> ActionRecoveryPolicy:
        if not isinstance(document, Mapping):
            raise TypeError("action recovery policy must be a mapping")
        inverse = document.get("inverse")
        safe_fallback = document.get("safeFallback")
        return cls(
            mode=document.get("mode"),
            reason=document.get("reason"),
            inverse=(ActionRecoveryStep.from_document(inverse) if inverse is not None else None),
            safe_fallback=(
                ActionRecoveryStep.from_document(safe_fallback)
                if safe_fallback is not None
                else None
            ),
        )


def derive_action_idempotency_key(
    identity: DriverActionIdentity,
    command: DriverCommand,
    *,
    intent_scope: str,
) -> str:
    if not isinstance(identity, DriverActionIdentity):
        raise TypeError("identity must be a DriverActionIdentity")
    if not isinstance(command, DriverCommand):
        raise TypeError("command must be a DriverCommand")
    _required_text(intent_scope, field="intent_scope", maximum=1024)
    digest = graph_content_digest(
        {
            "schemaVersion": DRIVER_ACTION_SCHEMA_VERSION,
            "identity": identity.to_document(),
            "command": command.to_document(),
            "intentScope": intent_scope,
        }
    )
    return f"action-v1:{digest}"


@dataclass(frozen=True, slots=True)
class DriverAction:
    identity: DriverActionIdentity
    command: DriverCommand
    preconditions: tuple[ActionPrecondition, ...]
    idempotency_key: str
    timeout_seconds: float
    verification: tuple[ActionVerification, ...]
    recovery: ActionRecoveryPolicy
    metadata: FrozenDict = FrozenDict()
    schema_version: int = DRIVER_ACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DRIVER_ACTION_SCHEMA_VERSION:
            raise ValueError(f"unsupported driver action schema version {self.schema_version!r}")
        if not isinstance(self.identity, DriverActionIdentity):
            raise TypeError("identity must be a DriverActionIdentity")
        if not isinstance(self.command, DriverCommand):
            raise TypeError("command must be a DriverCommand")
        if self.identity.operation != self.command.operation:
            raise ValueError("action identity and command operations must match")
        preconditions = tuple(self.preconditions)
        if any(not isinstance(item, ActionPrecondition) for item in preconditions):
            raise TypeError("preconditions must contain ActionPrecondition values")
        object.__setattr__(self, "preconditions", preconditions)
        _required_text(
            self.idempotency_key,
            field="idempotency_key",
            maximum=255,
        )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number")
        maximum_timeout = ActionExecutionLimits.from_settings().max_timeout_seconds
        if self.timeout_seconds > maximum_timeout:
            raise ValueError(
                "timeout_seconds exceeds configured max_timeout_seconds "
                f"({maximum_timeout})"
            )
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        verification = tuple(self.verification)
        if not verification or any(
            not isinstance(item, ActionVerification) for item in verification
        ):
            raise ValueError("verification must contain typed assertions")
        object.__setattr__(self, "verification", verification)
        if not isinstance(self.recovery, ActionRecoveryPolicy):
            raise TypeError("recovery must be an ActionRecoveryPolicy")
        object.__setattr__(
            self,
            "metadata",
            _frozen_mapping(self.metadata, field="action metadata"),
        )

    @classmethod
    def create(
        cls,
        *,
        identity: DriverActionIdentity,
        command: DriverCommand,
        intent_scope: str,
        timeout_seconds: float,
        verification: Sequence[ActionVerification],
        recovery: ActionRecoveryPolicy,
        preconditions: Sequence[ActionPrecondition] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> DriverAction:
        return cls(
            identity=identity,
            command=command,
            preconditions=tuple(preconditions),
            idempotency_key=derive_action_idempotency_key(
                identity,
                command,
                intent_scope=intent_scope,
            ),
            timeout_seconds=timeout_seconds,
            verification=tuple(verification),
            recovery=recovery,
            metadata=FrozenDict(metadata or {}),
        )

    def to_document(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "identity": self.identity.to_document(),
            "command": self.command.to_document(),
            "preconditions": [item.to_document() for item in self.preconditions],
            "idempotencyKey": self.idempotency_key,
            "timeoutSeconds": self.timeout_seconds,
            "verification": [item.to_document() for item in self.verification],
            "recovery": self.recovery.to_document(),
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> DriverAction:
        if not isinstance(document, Mapping):
            raise TypeError("driver action must be a mapping")
        preconditions = document.get("preconditions", ())
        verification = document.get("verification", ())
        for field, value in (
            ("preconditions", preconditions),
            ("verification", verification),
        ):
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise TypeError(f"{field} must be an array")
        return cls(
            schema_version=document.get("schemaVersion"),
            identity=DriverActionIdentity.from_document(document.get("identity")),
            command=DriverCommand.from_document(document.get("command")),
            preconditions=tuple(ActionPrecondition.from_document(item) for item in preconditions),
            idempotency_key=document.get("idempotencyKey"),
            timeout_seconds=document.get("timeoutSeconds"),
            verification=tuple(ActionVerification.from_document(item) for item in verification),
            recovery=ActionRecoveryPolicy.from_document(document.get("recovery")),
            metadata=document.get("metadata", {}),
        )


class ActionFailureClassification(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    STALE_PRECONDITION = "stale-precondition"
    DEPENDENCY = "dependency"
    SAFETY = "safety"


@dataclass(frozen=True, slots=True)
class ActionFailure:
    classification: ActionFailureClassification
    code: str
    message: str
    details: FrozenDict = FrozenDict()
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "classification",
            ActionFailureClassification(self.classification),
        )
        _required_text(self.code, field="failure code")
        _required_text(self.message, field="failure message", maximum=4096)
        object.__setattr__(
            self,
            "details",
            _frozen_mapping(self.details, field="failure details"),
        )
        if self.retry_after_seconds is not None:
            if (
                isinstance(self.retry_after_seconds, bool)
                or not isinstance(self.retry_after_seconds, (int, float))
                or self.retry_after_seconds < 0
            ):
                raise ValueError("retry_after_seconds must be a non-negative number or null")
            if not self.retryable:
                raise ValueError("retry_after_seconds is valid only for retryable failure classes")
            object.__setattr__(
                self,
                "retry_after_seconds",
                float(self.retry_after_seconds),
            )

    @property
    def retryable(self) -> bool:
        return self.classification in {
            ActionFailureClassification.TRANSIENT,
            ActionFailureClassification.DEPENDENCY,
        }

    @property
    def requires_reresolution(self) -> bool:
        return self.classification is ActionFailureClassification.STALE_PRECONDITION

    @property
    def blocks_unsuppress(self) -> bool:
        return self.classification is ActionFailureClassification.SAFETY

    def to_document(self) -> dict[str, object]:
        return {
            "classification": self.classification.value,
            "code": self.code,
            "message": self.message,
            "details": self.details.to_dict(),
            "retryable": self.retryable,
            "requiresReresolution": self.requires_reresolution,
            "blocksUnsuppress": self.blocks_unsuppress,
            "retryAfterSeconds": self.retry_after_seconds,
        }


class DriverActionError(RuntimeError):
    def __init__(self, action: DriverAction, failure: ActionFailure) -> None:
        if not isinstance(action, DriverAction):
            raise TypeError("action must be a DriverAction")
        if not isinstance(failure, ActionFailure):
            raise TypeError("failure must be an ActionFailure")
        self.action = action
        self.failure = failure
        super().__init__(
            f"{failure.classification.value} driver action failure "
            f"{failure.code!r} for {action.identity.resource_id!r}: {failure.message}"
        )
