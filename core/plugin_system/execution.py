from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from enum import StrEnum

from wyreplumber.runtime import FrozenDict

from core.orchestration.execution_limits import ActionExecutionLimits

from .contracts import (
    PluginDiagnostic,
    ProcessingDriver,
    ProcessingDriverRequest,
    ProcessingDriverResult,
    ProcessingHookContext,
    ProcessingPlan,
    ProcessingPlugin,
    ProcessingValidationIssue,
)


@dataclass(frozen=True, slots=True)
class ProcessingValidationOutcome:
    issues: tuple[ProcessingValidationIssue, ...]
    diagnostic: PluginDiagnostic | None = None

    @property
    def succeeded(self) -> bool:
        return self.diagnostic is None


@dataclass(frozen=True, slots=True)
class ProcessingPlanningOutcome:
    plan: ProcessingPlan | None
    diagnostic: PluginDiagnostic | None = None

    @property
    def succeeded(self) -> bool:
        return self.plan is not None and self.diagnostic is None


class ProcessingHookRunner:
    """Failure-isolated invocation of side-effect-free validation and planning hooks."""

    @staticmethod
    def validate(
        plugin: ProcessingPlugin,
        context: ProcessingHookContext,
    ) -> ProcessingValidationOutcome:
        try:
            issues = tuple(plugin.validate(context))
            if any(not isinstance(item, ProcessingValidationIssue) for item in issues):
                raise TypeError("validate must return ProcessingValidationIssue values")
            return ProcessingValidationOutcome(issues)
        except Exception as error:
            return ProcessingValidationOutcome(
                (),
                PluginDiagnostic(
                    plugin.manifest.plugin_id,
                    "validation",
                    "processing-plugin-validation-failed",
                    str(error),
                    {"exception": type(error).__name__, "nodeInstanceId": context.node_instance_id},
                ),
            )

    @staticmethod
    def plan(
        plugin: ProcessingPlugin,
        context: ProcessingHookContext,
    ) -> ProcessingPlanningOutcome:
        try:
            plan = plugin.plan(context)
            if not isinstance(plan, ProcessingPlan):
                raise TypeError("plan must return ProcessingPlan")
            if plan.node_instance_id != context.node_instance_id:
                raise ValueError("processing plan belongs to another node instance")
            return ProcessingPlanningOutcome(plan)
        except Exception as error:
            return ProcessingPlanningOutcome(
                None,
                PluginDiagnostic(
                    plugin.manifest.plugin_id,
                    "planning",
                    "processing-plugin-planning-failed",
                    str(error),
                    {"exception": type(error).__name__, "nodeInstanceId": context.node_instance_id},
                ),
            )


class ProcessingDriverHook(StrEnum):
    PREPARE = "prepare"
    OBSERVE = "observe"
    ACTIVATE = "activate"
    RECONFIGURE = "reconfigure"
    DEACTIVATE = "deactivate"
    CLEANUP = "cleanup"


class ProcessingDriverFailureClassification(StrEnum):
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    INVALID_RESULT = "invalid-result"


@dataclass(frozen=True, slots=True)
class ProcessingDriverExecution:
    hook: ProcessingDriverHook
    attempts: int
    result: ProcessingDriverResult | None
    failure: ProcessingDriverFailureClassification | None = None
    diagnostic: PluginDiagnostic | None = None
    attempt_idempotency_keys: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.failure is None


class ProcessingDriverExecutor:
    def execute(
        self,
        *,
        plugin_id: str,
        driver: ProcessingDriver,
        hook: ProcessingDriverHook | str,
        request: ProcessingDriverRequest,
        timeout_seconds: float,
        max_attempts: int = 1,
    ) -> ProcessingDriverExecution:
        hook = ProcessingDriverHook(hook)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        limits = ActionExecutionLimits.from_settings()
        if timeout_seconds > limits.max_timeout_seconds:
            raise ValueError("timeout_seconds exceeds configured maximum")
        if max_attempts > limits.max_attempts:
            raise ValueError("max_attempts exceeds configured maximum")
        method = getattr(driver, hook.value, None)
        if not callable(method):
            return self._failure(
                plugin_id,
                hook,
                0,
                ProcessingDriverFailureClassification.INVALID_RESULT,
                f"driver does not implement {hook.value}",
                request,
                (),
            )
        keys = []
        for attempt in range(1, max_attempts + 1):
            keys.append(request.idempotency_key)
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(method, request)
            try:
                result = future.result(timeout=float(timeout_seconds))
            except FutureTimeoutError:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                return self._failure(
                    plugin_id,
                    hook,
                    attempt,
                    ProcessingDriverFailureClassification.TIMEOUT,
                    f"driver hook {hook.value} exceeded {timeout_seconds} seconds",
                    request,
                    tuple(keys),
                )
            except Exception as error:
                executor.shutdown(wait=True, cancel_futures=True)
                if attempt < max_attempts:
                    continue
                return self._failure(
                    plugin_id,
                    hook,
                    attempt,
                    ProcessingDriverFailureClassification.EXCEPTION,
                    str(error),
                    request,
                    tuple(keys),
                    exception=type(error).__name__,
                )
            else:
                executor.shutdown(wait=True)
            if not isinstance(result, ProcessingDriverResult):
                if attempt < max_attempts:
                    continue
                return self._failure(
                    plugin_id,
                    hook,
                    attempt,
                    ProcessingDriverFailureClassification.INVALID_RESULT,
                    "driver hook returned an invalid result",
                    request,
                    tuple(keys),
                    returnedType=type(result).__name__,
                )
            return ProcessingDriverExecution(
                hook,
                attempt,
                result,
                attempt_idempotency_keys=tuple(keys),
            )
        raise AssertionError("bounded driver attempts exhausted without an outcome")

    @staticmethod
    def _failure(
        plugin_id: str,
        hook: ProcessingDriverHook,
        attempts: int,
        failure: ProcessingDriverFailureClassification,
        message: str,
        request: ProcessingDriverRequest,
        keys: tuple[str, ...],
        **details: object,
    ) -> ProcessingDriverExecution:
        return ProcessingDriverExecution(
            hook,
            attempts,
            None,
            failure,
            PluginDiagnostic(
                plugin_id,
                f"driver:{hook.value}",
                f"processing-driver-{failure.value}",
                message,
                FrozenDict(
                    {
                        "nodeInstanceId": request.node_instance_id,
                        "idempotencyKey": request.idempotency_key,
                        **details,
                    }
                ),
            ),
            keys,
        )
